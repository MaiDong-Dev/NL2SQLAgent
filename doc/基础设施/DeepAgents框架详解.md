# DeepAgents 框架详解（2026 年最新）

## 1. 什么是 DeepAgents？

[DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) 是 LangChain 官方推出的一套**开箱即用（Batteries Included）的 Agent 开发框架**，专门面向复杂任务、长流程执行、多步骤规划、多 Agent 协作以及需要上下文工程的应用场景。

### 1.1 一句话理解

> **如果你用 LangGraph 是"手动造车"（定义 State、Node、Edge），那 DeepAgents 就是"直接开走一辆配置好的跑车"（`create_deep_agent()` 一行搞定）。**

### 1.2 与传统 Agent 框架的对比

| 维度 | 传统 Agent（LangGraph 手写） | DeepAgents |
|------|---------------------------|------------|
| 构建方式 | 手动定义 StateGraph、节点、边 | `create_deep_agent()` 一行代码 |
| 任务规划 | 需要自己实现 | 内置 `write_todos` 规划工具 |
| 文件系统 | 需要自己集成 | 内置虚拟文件系统（读/写/编辑/搜索） |
| 子智能体 | 需要手动编排 | 内置 `task` 子智能体委派 |
| 上下文管理 | 需要自己处理 | 自动摘要 + 大结果自动落盘 |
| 代码执行 | 需要自己集成 | 内置沙箱 Shell + JS 解释器 |
| 中间件 | 需要自己实现 | 内置 + 可扩展中间件体系 |
| 多模态 | 需要自己处理 | 原生支持图片/音频/PDF |


### 1.3 发展历程

| 时间 | 版本 | 核心更新 |
|------|------|---------|
| 2025.Q4 | v0.1~0.4 | 初始版本，基础四大支柱 |
| 2026.04 | v0.5 | 异步子智能体、多模态文件系统扩展 |
| 2026.05 | **v0.6**（最新） | Harness Profiles、Delta Channels、代码解释器 |

---

## 2. 四大核心支柱

DeepAgents 围绕四个核心能力构建：

```
┌──────────────────────────────────────────────────────────────┐
│                DeepAgents 四大支柱                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 📋 任务规划   │  │ 📁 文件系统   │  │ 🤖 子智能体   │       │
│  │ write_todos  │  │ read/write/  │  │ task 委派     │       │
│  │ 结构化任务跟踪│  │ edit/search  │  │ 上下文隔离     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              🧠 上下文管理                             │    │
│  │  • 长对话自动摘要                                     │    │
│  │  • 大工具输出自动落盘（防止上下文窗口爆满）              │    │
│  │  • 跨会话持久化记忆（AGENTS.md）                       │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 任务规划（Planning）— `write_todos`

DeepAgents 内置了 `write_todos` 工具，Agent 可以自动维护结构化的任务列表：

```python
# Agent 会自动使用 write_todos 工具规划任务
# 内部任务列表结构：
todos = [
    {"id": "1", "content": "查询上月销售数据", "status": "completed"},
    {"id": "2", "content": "计算同比增长率", "status": "in_progress"},
    {"id": "3", "content": "生成分析报告", "status": "pending"},
    {"id": "4", "content": "发送邮件给领导", "status": "pending"},
]
```

**核心价值**：

- Agent 不会"忘记"自己要做什么（长任务必备）
- 用户可以随时查看进度
- 任务失败后可以从中断点恢复

### 2.2 文件系统（Filesystem）— 虚拟文件工具

DeepAgents 提供了一套**虚拟文件系统**，Agent 可以像操作本地文件一样读写：

```python
# Agent 可用的文件系统工具
tools = [
    "read",    # 读取文件
    "write",   # 写入文件
    "edit",    # 编辑文件（精确替换）
    "search",  # 搜索文件内容 (grep)
    "ls",      # 列出目录
    "glob",    # 模式匹配文件
]
```

**可插拔后端**：文件系统支持多种后端存储：

| 后端 | 用途 |
|------|------|
| `StateBackend` | 存在 State 中（默认） |
| `LocalBackend` | 本地文件系统 |
| `S3Backend` | AWS S3 云存储 |
| `CompositeBackend` | 组合多个后端 |

**权限控制**：

```python
agent = create_deep_agent(
    model="deepseek-chat",
    filesystem_permissions={
        "/workspace/": "read_write",   # 可读写
        "/data/": "read_only",         # 只读
        "/secrets/": "deny",           # 禁止访问
    }
)
```

### 2.3 子智能体委派（Sub-agent Delegation）

这是 DeepAgents 最强大的特性之一。主 Agent 可以通过 `task` 工具将子任务委派给**独立的子智能体**：

```python
# 主 Agent 内部流程：
# 1. 使用 task 工具委派子任务
agent_thinking = """
我需要同时分析三个部门的销售数据。让我委派子智能体并行处理：
- task("分析市场部销售数据", subagent_type="data_analyst")
- task("分析研发部销售数据", subagent_type="data_analyst")
- task("分析销售部销售数据", subagent_type="data_analyst")
"""
```

**子智能体的四大优势**：

| 优势 | 说明 |
|------|------|
| **上下文隔离** | 每个子智能体有独立的 Context Window，不污染主 Agent |
| **并行执行** | **v0.5 新增**：异步子智能体，可以并行处理多个子任务 |
| **专业化** | 可以为不同子智能体配置不同的工具和提示词 |
| **结果汇总** | 子智能体只返回最终结果，不返回中间步骤 |

**对比传统做法**：

```
传统做法（无子智能体）：
主 Agent → 分析部门A → 分析部门B → 分析部门C → 汇总
（串行执行，上下文越来越长，最后可能丢失早期信息）

DeepAgents 做法：
主 Agent → task("部门A") ─┐
         → task("部门B") ─┤ 并行执行
         → task("部门C") ─┘
         → 汇总三个结果
（并行执行，每个子智能体上下文独立，主 Agent 只看到结果摘要）
```

### 2.4 上下文管理（Context Management）

Agent 在处理长对话时会遇到**上下文窗口爆满**问题。DeepAgents 有两层机制应对：

**机制一：自动摘要**

```python
# 当对话历史超过阈值时，自动将早期对话压缩为摘要
# 配置：max_tokens=4000, trigger_at=3000
# 超过 3000 token 时，自动将前 2000 token 压缩为一段摘要
```

**机制二：大结果自动落盘**

```python
# 当工具返回的结果过大时，自动保存到文件而非放在上下文中
# 例如：查询返回 10000 行数据 → 保存为 /results/query_output.json
# Agent 上下文只保留：文件路径 + 前 10 行预览
```

**机制三：跨会话记忆（AGENTS.md）**

```python
# DeepAgents 支持持久化记忆，跨会话保存
# 记忆存储在 AGENTS.md 文件中
# 内容示例：
"""
# 用户偏好
- 用户喜欢表格格式的输出
- 用户是中文使用者
- 数据分析时优先使用图表展示

# 历史上下文
- 上次分析了 2025 年 Q4 的销售数据
- 用户关注的核心指标是 GMV 和客单价
"""
```

---

## 3. Harness（执行环境）

Harness 是 DeepAgents 的**执行环境抽象层**，定义了 Agent 的运行边界和能力。

### 3.1 四层架构

```
┌─────────────────────────────────────────────┐
│               Harness 四层架构                │
├─────────────────────────────────────────────┤
│  1. Tools（工具层）                           │
│     自定义函数、API、数据库、MCP 工具          │
├─────────────────────────────────────────────┤
│  2. Virtual Filesystem（虚拟文件系统）         │
│     read/write/edit/search + 权限控制         │
├─────────────────────────────────────────────┤
│  3. Code Execution（代码执行）                 │
│     沙箱 Shell + 进程内 JS 解释器（v0.6 新增） │
├─────────────────────────────────────────────┤
│  4. Filesystem Permissions（权限控制）        │
│     声明式路径访问控制                         │
└─────────────────────────────────────────────┘
```

### 3.2 Harness Profiles（v0.6 新增）

Harness Profiles 是 v0.6 的核心创新，允许为不同模型**打包配置**：

```python
# 内置的模型配置模板
from deepagents import create_deep_agent, register_harness_profile

# 使用内置 Profile
agent = create_deep_agent(
    model="qwen/qwen3-235b",  # 使用开源模型
    harness_profile="qwen3"    # 自动加载针对 Qwen3 优化的配置
)

# 自定义 Profile
@register_harness_profile("my_profile")
class MyProfile:
    model_config = {
        "temperature": 0.1,
        "max_tokens": 8000,
    }
    middleware = [
        SummarizationMiddleware(max_tokens=4000),
        PIIMaskingMiddleware(),
    ]
    tools = [search_database, calculate]
```

**内置 Profiles**：

| Profile | 适用模型 | 特点 |
|---------|---------|------|
| `deepseek` | DeepSeek-V3/R1 | 优化的推理配置 |
| `qwen3` | Qwen3 系列 | 开源模型最佳实践 |
| `kimi` | Kimi K2 | 长上下文优化 |
| `claude` | Claude 4 系列 | 工具调用优化 |
| `gpt` | GPT-5 系列 | 多模态优化 |

**核心价值**：让开源模型（Qwen、DeepSeek、Kimi）也能达到**接近闭源模型的生产级性能**，同时成本降低 20 倍以上。

### 3.3 Delta Channels（v0.6 新增）

传统 LangGraph 在每个 Checkpoint 存储**完整的状态快照**，对于长时间运行的 Agent，存储开销巨大。

Delta Channels 只存储**增量变化**：

```python
# 传统方式：每个步骤存储完整快照
Step 1: { messages: [...100条], state: {...} }  # 100KB
Step 2: { messages: [...101条], state: {...} }  # 101KB
Step 3: { messages: [...102条], state: {...} }  # 102KB
# 总计: 303KB

# Delta Channels：只存储增量
Step 1: { messages: [...100条], state: {...} }  # 100KB
Step 2: { messages: [+1条], state: {delta} }    # 1KB
Step 3: { messages: [+1条], state: {delta} }    # 1KB
# 总计: 102KB（减少 100x）
```

---

## 4. 快速入门

### 4.1 安装

```bash
pip install deepagents
```

### 4.2 最小示例

```python
from deepagents import create_deep_agent

# 创建 Agent
agent = create_deep_agent(
    model="deepseek-chat",
    system_prompt="你是一个数据分析助手，可以读写文件、搜索数据。"
)

# 调用
result = await agent.ainvoke({
    "messages": [{"role": "user", "content": "分析 data/sales.csv 的销售趋势"}]
})
```

### 4.3 完整示例：数据分析 Agent

```python
from deepagents import create_deep_agent
from deepagents.middleware import SummarizationMiddleware

# 1. 定义工具
async def query_database(sql: str) -> str:
    """执行 SQL 查询"""
    return await db.execute(sql)

async def send_email(to: str, subject: str, body: str):
    """发送邮件"""
    await email_service.send(to, subject, body)

# 2. 创建 Agent
agent = create_deep_agent(
    model="deepseek-chat",
    tools=[query_database, send_email],
    system_prompt="""你是一个数据分析助手。
    1. 先用 write_todos 规划任务
    2. 查询数据库获取数据
    3. 将分析结果写入文件
    4. 发送邮件通知
    """,
    middleware=[
        SummarizationMiddleware(max_tokens=4000),
    ],
    filesystem_permissions={
        "/workspace/": "read_write",
        "/data/": "read_only",
    },
    harness_profile="deepseek",  # 使用 DeepSeek 优化配置
)

# 3. 流式执行
async for event in agent.astream_events(
    {
        "messages": [{
            "role": "user",
            "content": "分析上月各部门销售数据，生成报告，发送给 manager@company.com"
        }]
    },
    version="v3"
):
    print(event)
```

---

## 5. 流式事件（Streaming）

DeepAgents 提供**类型化的流式事件**，前端可以精确渲染不同类型的输出：

```python
async for event in agent.astream_events(version="v3"):
    match event["event"]:
        case "on_chat_model_stream":
            # LLM 输出的 token 流
            print(event["data"]["chunk"])

        case "on_tool_start":
            # 工具调用开始
            print(f"🔧 调用工具: {event['name']}")

        case "on_tool_end":
            # 工具调用完成
            print(f"✅ 工具返回: {event['data']['output']}")

        case "on_subagent_start":
            # 子智能体开始执行
            print(f"🤖 子智能体启动: {event['name']}")

        case "on_subagent_end":
            # 子智能体完成
            print(f"✅ 子智能体完成: {event['data']['output']}")

        case "on_todo_update":
            # 任务状态更新
            print(f"📋 任务: {event['data']}")
```

**事件类型映射**：

| 事件 | 前端渲染 |
|------|---------|
| `on_chat_model_stream` | 打字机效果的文本 |
| `on_tool_start/end` | 工具调用状态指示器 |
| `on_subagent_start/end` | 子任务进度条 |
| `on_todo_update` | 任务清单更新 |
| `on_custom_event` | 自定义进度推送 |

---

## 6. DeepAgents vs LangGraph 的选择

| 场景 | 推荐方案 | 原因 |
|------|---------|------|
| 快速原型 / MVP | **DeepAgents** | 一行代码构建，开箱即用 |
| 标准 Agent（规划+文件+工具） | **DeepAgents** | 内置四大支柱，无需手写 |
| 多 Agent 协作 | **DeepAgents** | 内置子智能体委派 |
| 需要精细控制流程 | **LangGraph** | 显式定义节点和边 |
| 非标准工作流 | **LangGraph** | 完全自定义图结构 |
| 已有 LangGraph 代码 | **LangGraph** | 迁移成本考虑 |

**它们的关系**：

```
DeepAgents = LangGraph + 预置节点 + 预置工具 + 预置中间件 + 最佳实践
```

DeepAgents 底层仍然运行在 LangGraph 上，只是把常见的 Agent 模式**封装成了开箱即用的组件**。

---

## 7. Managed Deep Agents（托管服务）

LangChain 在 2026 年推出了 **Managed Deep Agents**（私有 Beta），这是一个**API 优先的托管运行时**：

```python
# 本地开发 → 一行命令部署到 LangSmith
# deepagents deploy

# 生产环境调用
import requests

response = requests.post(
    "https://api.langsmith.com/deep-agents/run",
    json={
        "agent_id": "my-data-analyst",
        "input": "分析上月销售数据",
        "stream": True
    },
    headers={"Authorization": "Bearer ls_..."}
)
```

**自动处理**：

- 执行环境管理（无需自建服务器）
- 上下文持久化（无需自建数据库）
- 沙箱隔离（安全执行代码）
- 自动扩缩容

---

## 8. 总结

| 概念 | 一句话解释 |
|------|-----------|
| DeepAgents | LangChain 官方的"开箱即用"Agent 框架 |
| `create_deep_agent()` | 一行代码创建功能完整的 Agent |
| 四大支柱 | 规划（write_todos）+ 文件系统 + 子智能体 + 上下文管理 |
| Harness | 执行环境抽象（工具 + 文件系统 + 代码执行 + 权限） |
| Harness Profiles | 模型优化配置模板（v0.6），开源模型也能达到生产级性能 |
| 子智能体 | 独立的子任务执行器，上下文隔离，v0.5 支持异步并行 |
| Delta Channels | 增量状态存储（v0.6），减少 100x 存储开销 |
| Managed Deep Agents | LangSmith 托管运行时（私有 Beta） |

**DeepAgents 的核心价值**：让开发者**专注于业务逻辑**，而不是纠结于 Agent 的基础设施（规划、文件、上下文、子智能体委派）。它把 LangChain 社区的最佳实践**封装为默认行为**，让构建复杂 Agent 像搭积木一样简单。\