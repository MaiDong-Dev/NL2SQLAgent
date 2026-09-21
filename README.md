# NL2SQL Agent

基于 **LangGraph** 的元数据增强 Text-to-SQL 问数系统。用户以自然语言提问，系统通过
「关键词抽取 → 字段/指标/取值三路召回 → 过滤降噪 → 字段补全 → SQL 生成/校验/纠错 → 执行」
的流水线返回查询结果，并以 SSE 流式输出。

## 核心设计

- **元数据三路召回**：字段与指标走 Qdrant 向量检索（含 name/description/alias 多向量），
  字段取值走 Elasticsearch 全文倒排。向量召回解决「语义匹配」，ES 解决「枚举值精确命中」。
- **确定性规则补偿语义盲区**：主外键、时间维表字段（year/quarter/month）语义弱、几乎召不回来，
  用规则强制保留（`server/agent/time_utils.py`），避免 SQL 退化成对日期键做算术运算。
- **相对阈值降噪**：字段召回不用绝对相似度阈值（正确项与噪音项分数高度交错），
  改用「保留 >= 本次最高分 × ratio」的相对阈值，参数见 `conf/app_config.yaml` 的 `recall` 段。
- **评测闭环**：63 条标注集 + 双裁判（Jev 语义等价 / ragas 指标）对比，见 `docs/reports/`。

## 目录结构

```
NL2SQLAgent/
├── main.py                  FastAPI 应用入口（uvicorn 启动）
├── pyproject.toml           依赖与 pytest 配置（uv 管理）
├── conf/
│   ├── app_config.yaml      本地真实配置（含密码，**不入库**）
│   ├── app_config.example.yaml  配置模板（入库）
│   └── meta_config.yaml     元知识声明式配置（表/字段/指标定义）
├── prompts/                 提示词模板（与代码解耦，可独立调优）
│
├── server/                  后端服务（分层）
│   ├── api/                 接口层：FastAPI 依赖注入、路由、请求/响应 Schema
│   ├── services/            服务层：组装上下文并驱动 LangGraph
│   ├── agent/               Agent 层：LangGraph 图编排、状态、LLM、各处理节点
│   ├── repositories/        数据访问层：Meta/DW MySQL、Qdrant、ES
│   ├── models/ ORM 模型层   SQLAlchemy 模型（映射元数据库表）
│   ├── entities/ 实体层     领域实体（纯 dataclass，与存储解耦）
│   ├── clients/             中间件客户端管理器（连接与生命周期）
│   ├── prompt/  conf/  core/  提示词/配置/基础设施（日志、上下文、lifespan）
│   └── ...
├── meta_builder/            元知识构建（离线任务，独立于服务进程）
├── frontend/                前端（Vue 3 + Vite，聊天式问数界面）
├── deploy/                  部署：docker-compose 与中间件初始化
├── tests/                   测试：unit（离线）+ integration（需中间件）
├── eval/                    评测：流水线、标注集、结果
├── scripts/                 运维脚本（服务连通性检查、冒烟）
└── docs/
    ├── tutorial/            01~08 中文教程（项目概述/架构/环境/基础设施/元数据/智能体/API/联调）
    ├── reports/             评测报告（09 评测报告、10 双裁判对比报告）
    └── architecture-*.mmd|png  架构图（包依赖/类图/流水线/状态流转/DI 链/召回/Embedding）
```

## 快速开始

### 1. 配置

```bash
cp conf/app_config.example.yaml conf/app_config.yaml
# 编辑 conf/app_config.yaml，填写 MySQL 密码、各中间件地址、LLM Key
```

`conf/app_config.yaml` 含明文密码，已在 `.gitignore` 中，**不会提交**。
LLM Key 也可以留空并用环境变量注入（`DEEPSEEK_API_KEY`）。

### 2. 启动中间件

```bash
cd deploy && docker compose up -d
```

启动 MySQL（meta + dw，含初始化脚本）、Elasticsearch（含 IK 分词）、Kibana、Qdrant、Embedding 服务。
详见 `deploy/README.md`。

### 3. 安装依赖并构建元知识

```bash
uv sync
uv run python -m meta_builder.scripts.build_meta_knowledge   # 表/字段/指标同步到 MySQL+Qdrant+ES
```

### 4. 启动服务

```bash
uv run python main.py            # http://localhost:8000
```

### 5. 启动前端

```bash
cd frontend && npm install && npm run dev
```

前端开发服务器把 `/api` 代理到 `http://localhost:8000`（见 `frontend/vite.config.js`）。

## 测试

```bash
uv sync --extra dev
uv run pytest tests/unit                                  # 离线单测，无需中间件
set RUN_INTEGRATION=1 && uv run pytest tests/integration  # 全链路冒烟，需中间件
```

分层的测试清单与约定见 `tests/README.md`。

## 评测

- `eval/run_ragas_eval.py`：评测流水线，`--judge {jev,ragas,both}` 切换裁判（默认 Jev）
- `eval/dataset.jsonl`：63 条标注集；`eval/results_*.csv`：多轮评测结果
- **`docs/reports/10-两个裁判方案对比检测报告.md`**：两种裁判方案的完整对比
  （判定口径、准确率、延迟、成本、分歧逐条分析）
- `docs/reports/09-评测报告.md`：系统整体评测报告

## 文档

| 文档 | 内容 |
| --- | --- |
| `docs/tutorial/01~08` | 项目概述、架构、开发环境、基础设施、元数据知识库、问数智能体、API 接口、前后端联调 |
| `docs/architecture-*.png` | 包依赖、类图、LangGraph 流水线、状态流转、FastAPI DI 链、元知识构建、两阶段召回、Embedding 策略 |
| `docs/reports/` | 评测报告与裁判方案对比 |
