# 部署

本目录是中间件编排（原 `docker/`），用 Docker Compose 一键拉起服务依赖的全部中间件。

## 服务清单

| 服务 | 镜像 | 端口 | 作用 |
| --- | --- | --- | --- |
| mysql | `mysql:8.0` | 3306 | 元数据库 `meta` + 演示数据仓库 `dw` |
| elasticsearch | 本地构建（含 IK 分词插件） | 9200 | 字段取值全文倒排召回 |
| kibana | `kibana:8.19.10` | 5601 | ES 调试控制台 |
| qdrant | `qdrant/qdrant:v1.16` | 6333（HTTP）/ 6334（gRPC） | 字段 / 指标向量召回 |
| embedding | `text-embeddings-inference:cpu-1.8` | 8081 | `BAAI/bge-large-zh-v1.5` 向量化（1024 维） |

## 启动

```bash
cd deploy
docker compose up -d
docker compose ps                 # 确认 5 个服务都 up
docker compose logs -f mysql      # 首次启动看初始化是否报错
```

停止：`docker compose down`（加 `-v` 会连数据卷一起删除，下次 up 会重新初始化）。

## 前置准备

1. **Embedding 模型文件（必须）**：compose 把 `./embedding/bge-large-zh-v1.5` 挂载进容器，
   但模型权重未入库，需自行下载后放到该目录（含 `config.json`、`model.safetensors`、
   `tokenizer.json` 等），否则 embedding 服务起不来，向量召回全部失败。
2. **MySQL 初始化**：`mysql/meta.sql`、`mysql/dw.sql` 会在容器**首次启动**时自动执行
   （挂载到 `/docker-entrypoint-initdb.d`），建库建表并灌入 dw 演示数据。
   数据卷已存在时不会重跑，要重置执行 `docker compose down -v` 后再 up。
3. **配置对齐**：`conf/app_config.yaml` 中的地址与端口需与上表一致（本机部署即默认值）。
4. **扩充 dw 数据（推荐）**：`dw.sql` 的种子数据只有 2025 Q1 共 115 单，
   TopN 排名、各大区对比、同比环比这类问句没有区分度。执行：

   ```bash
   python -m scripts.generate_dw_data --dry-run   # 先看将要写入的规模
   python -m scripts.generate_dw_data --reset     # 重建为 50000 单 / 2024-2025 两年
   ```

   `--orders N` 调订单量，`--customers/--products` 调维度量。固定随机种子，可复现。
   原 115 单种子数据会原样保留。
5. **重建元知识库（扩数据后必做）**：新增的省份/品类/品牌等取值需要重新灌进
   ES 取值索引与 Qdrant 向量，否则这些取值的召回会失效：

   ```bash
   python -m meta_builder.scripts.build_meta_knowledge -c conf/meta_config.yaml
   ```

## 注意

- compose 里 MySQL 密码写死为 `Wuyun.123`，**该密码已出现在仓库历史提交中（视为泄露）**，
  仅作本地演示；请按自己环境修改 `conf/app_config.yaml`，不要带默认密码上生产。
- dw 演示数据默认只有 **2025 年 Q1 共 115 笔订单**，跨年 / 其他季度的问句会返回空结果，
  这不是系统 bug——跑上面的第 4 步扩充数据即可解决。
- **改数据后要重跑评测**：09 报告的准确率是在 115 单数据上测的，数据规模变了就不再有可比性。
- 服务进程本身不在容器内，仍由 `uv run python main.py` 启动（见根目录 README）。
