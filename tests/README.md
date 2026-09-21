# 测试说明

按「分层开发」组织，`tests/unit/` 覆盖各层的纯逻辑（离线可跑），
`tests/integration/` 覆盖需要真实中间件的链路（默认跳过）。

## 目录与覆盖范围

```
tests/
├── conftest.py                          # 把项目根加入 sys.path
├── unit/
│   ├── test_conf_layer.py               # 配置层：app_config / meta_config 解析与约束
│   ├── test_entities_models_layer.py    # 实体层 + 模型层 + 映射层：Entity ↔ ORM 往返
│   ├── test_api_schema_layer.py         # 接口层：QuerySchema 请求校验
│   ├── test_prompt_layer.py             # 提示词层：prompts/*.prompt 加载
│   ├── test_agent_time_utils.py         # Agent 层：时间语义识别 / 时间维表判定
│   └── test_eval_metrics_layer.py       # 评测层：execution_accuracy 判定规则
└── integration/
    └── test_api_query.py                # 接口层：POST /api/query 全链路冒烟
```

## 运行

```bash
# 安装测试依赖（首次）
uv sync --extra dev

# 只跑离线单测（不需要任何中间件）
uv run pytest tests/unit

# 含集成测试（需先启动 deploy/docker-compose.yaml 里的中间件）
set RUN_INTEGRATION=1 && uv run pytest tests/integration -m integration
```

## 约定

- **单测不得依赖中间件**：配置、映射、模板、正则规则等纯逻辑放 `unit/`，
  任何需要 MySQL / ES / Qdrant / Embedding 的断言放 `integration/`。
- **集成测试必须带 `RUN_INTEGRATION` 开关**：CI 或未起中间件的机器上不能红。
- **被测行为优先选「会静默出错」的点**：如 `_canon` 的数值归一化
  （Decimal 9 与 int 9 不等价会误判整份评测结论）、时间维表判定
  （漏召回会导致 SQL 退化成日期键算术，口径错误但不报错）。
- 新增分层时同步补 `unit/` 下对应文件，命名 `test_<层名>_layer.py`。
