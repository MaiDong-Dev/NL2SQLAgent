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

## 注意

- compose 里 MySQL 密码写死为 `Wuyun.123`，**该密码已出现在仓库历史提交中（视为泄露）**，
  仅作本地演示；请按自己环境修改 `conf/app_config.yaml`，不要带默认密码上生产。
- dw 演示数据只有 **2025 年 Q1 共 115 笔订单**，跨年 / 其他季度的问句会返回空结果，
  这不是系统 bug。
- 服务进程本身不在容器内，仍由 `uv run python main.py` 启动（见根目录 README）。
