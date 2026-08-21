# LangChain 框架详解（2026 年最新）

## 1. LangChain 概述

[LangChain](https://docs.langchain.com/) 是当前**全球最主流的 LLM 应用开发框架**，提供了一套完整的工具链，帮助开发者快速构建基于大语言模型（LLM）的应用和智能体（Agent）。

### 1.1 发展历程

| 时间 | 版本 | 里程碑 |
|------|------|--------|
| 2022.10 | v0.0.1 | 项目诞生，提供基础的 Chain 抽象 |
| 2023-2024 | v0.1~0.3 | 快速迭代，LCEL、LangGraph 诞生 |
| 2025.10 | LangGraph 1.0 GA | 图编排框架正式发布，400+ 企业生产使用 |
| 2025.Q4 | LangChain 1.0 | 全新架构：`create_agent`、Middleware、Content Blocks |
| 2026.03 | LangGraph 1.1 | 类型安全 v2 流式、每节点超时、优雅关闭 |
| 2026.04 | DeepAgents v0.5 | 开箱即用 Agent 框架，异步子智能体 |
| 2026.05 | DeepAgents v0.6 | Harness Profiles、Delta Channels |
| 2026.Q3 | LangChain v1.3 | v3 流式事件、MCP 全协议兼容 |

截至 2026 年，LangChain 已拥有 **97,000+ GitHub Star** 和 **50,000+ 生产应用**，生态包含 600+ 模型/工具提供商集成。

### 1.2 LangChain 生态全景

```
┌──────────────────────────────────────────────────────────────┐
│                   LangChain 生态 (2026)                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │  LangChain   │   │  LangGraph   │   │   DeepAgents     │  │
│  │  (工具集)     │   │  (运行时)     │   │   (开箱即用)      │  │
│  │              │   │              │   │                  │  │
│  │ • 模型集成    │   │ • 图编排      │   │ • 规划+文件系统   │  │
│  │ • LCEL 链式  │   │ • 状态管理    │   │ • 子智能体委派    │  │
│  │ • create_    │   │ • Checkpoint │   │ • 上下文管理      │  │
│  │   agent      │   │ • 人在环      │   │ • Harness 配置    │  │
│  │ • Middleware │   │ • 流式输出    │   │ • 代码执行沙箱    │  │
│  └──────────────┘   └──────────────┘   └──────────────────┘  │
│         │                  │                    │             │
│         └──────────────────┼────────────────────┘             │
│                            ▼                                  │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                   LangSmith (平台)                     │    │
│  │  • Fleet: 无代码 Agent 构建器                          │    │
│  │  • Engine: 自动检测问题 + 修复建议                      │    │
│  │  • Managed Deep Agents: 托管 Agent 运行时              │    │
│  │  • 追踪、评估、监控、Prompt 管理                        │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. LangChain 1.0 核心变革

LangChain 1.0 是一次**架构级别的重构**，核心变化：

### 2.1 `create_agent` — 统一的 Agent 入口

**过去**（v0.x）：碎片化的 Agent 创建方式：

```python
# ❌ 旧方式（已废弃）
from langchain.agents import initialize_agent, AgentExecutor, create_react_agent
# 每种 Agent 类型有不同的创建方式，混乱不堪
```

**现在**（v1.0+）：`create_agent` 是唯一推荐的方式：

```python
# ✅ 新方式（v1.0+）
from langchain.agents import create_agent

agent = create_agent(
    model="deepseek-chat",           # 底层 LLM 模型
    tools=[search_tool, calc_tool],  # 工具列表
    system_prompt="你是一个数据分析助手",
    middleware=[                      # 中间件（核心新增）
        SummarizationMiddleware(),
        HumanInTheLoopMiddleware(),
    ],
    checkpointer=memory_saver,       # 状态持久化
)
```

**`create_agent` 的核心优势**：

| 特性 | 说明 |
|------|------|
| 底层统一 | 内部基于 LangGraph 运行时，享受持久化、流式、人在环等能力 |
| 标准化主循环 | 调用模型 → 选择工具 → 执行工具 → 判断是否结束 |
| 中间件机制 | 可插拔的钩子系统，细粒度控制 Agent 每一步 |
| 开箱即用 | 10 行代码即可构建生产级 Agent |

### 2.2 Middleware（中间件）— v1.0 的核心创新

Middleware 是 `create_agent` 最强大的特性，提供**可插拔的钩子系统**，在 Agent 主循环的每个关键节点注入自定义逻辑。

```python
from langchain.agents.middleware import BaseMiddleware

class MyCustomMiddleware(BaseMiddleware):
    """自定义中间件"""

    async def before_model(self, state, runtime):
        """模型调用前：可以修改 prompt、动态选择工具"""
        # 注入当前时间上下文
        state["messages"].append({
            "role": "system",
            "content": f"当前时间：{datetime.now()}"
        })
        return state

    async def after_model(self, state, runtime):
        """模型调用后：可以校验输出、修改工具调用"""
        # 检查模型输出是否合法
        last_message = state["messages"][-1]
        if "危险操作" in str(last_message):
            raise ValueError("检测到危险操作！")
        return state

    async def wrap_tool_call(self, state, tool_call, handler):
        """工具调用前后：可以记录日志、修改参数、处理结果"""
        logger.info(f"调用工具: {tool_call['name']}")
        result = await handler(state, tool_call)  # 执行实际调用
        logger.info(f"工具返回: {result}")
        return result
```

**内置中间件**：

| 中间件 | 用途 |
|--------|------|
| `SummarizationMiddleware` | 长对话自动摘要，防止上下文超限 |
| `HumanInTheLoopMiddleware` | 关键操作需人工确认 |
| `PIIMaskingMiddleware` | 自动脱敏身份证、手机号等敏感信息 |
| `ToolFilterMiddleware` | 根据上下文动态控制工具可用性 |
| `DynamicPromptMiddleware` | 动态注入系统提示词 |

### 2.3 Content Blocks — 统一的多模态输出

**痛点**：不同模型厂商（OpenAI、Anthropic、DeepSeek）的输出格式各不相同，切换模型后流式输出、UI 渲染、记忆存储可能全部失效。

**解决方案**：LangChain 1.0 引入 `content_blocks` 属性，为所有模型输出定义统一标准：

```python
# 无论用哪个模型，输出结构统一
response = await agent.ainvoke("分析这张图片")

# 统一的 content_blocks 结构
for block in response.content_blocks:
    print(block)
    # 所有模型的输出都变成统一格式：
    # TextBlock(text="...")
    # ImageBlock(url="...")
    # ToolCallBlock(name="...", args={...})
    # ReasoningBlock(thinking="...")
```

**支持的内容块类型**：

| 类型 | 说明 |
|------|------|
| `TextBlock` | 纯文本 |
| `ImageBlock` | 图片（URL / Base64） |
| `AudioBlock` | 音频 |
| `ToolCallBlock` | 工具调用请求 |
| `ToolResultBlock` | 工具调用结果 |
| `ReasoningBlock` | 推理过程（思考链） |

### 2.4 简化的命名空间

LangChain 1.0 大幅简化了包结构：

```python
# v0.x（混乱）
from langchain.chains import LLMChain
from langchain.agents import initialize_agent
from langchain.tools import Tool
from langchain.memory import ConversationBufferMemory

# v1.0（简洁）
from langchain.agents import create_agent       # 统一 Agent 入口
from langchain.tools import tool                # 统一工具定义
from langchain.agents.middleware import BaseMiddleware  # 中间件
```

---

## 3. LCEL（LangChain Expression Language）

LCEL 是 LangChain 的**声明式链式编程语言**，使用 `|` 管道符连接组件。

### 3.1 基本语法

```python
from langchain_core.runnables import RunnablePassthrough

# LCEL 链式调用
chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt_template
    | llm
    | output_parser
)

# 调用
result = chain.invoke("什么是 RAG？")
```

### 3.2 LCEL 的核心优势

```python
# 1. 同步/异步统一
result = chain.invoke("hello")       # 同步
result = await chain.ainvoke("hello")  # 异步

# 2. 批量处理
results = chain.batch(["q1", "q2", "q3"])

# 3. 流式输出
async for chunk in chain.astream("hello"):
    print(chunk)

# 4. 自动并行
# 当多个步骤没有依赖关系时，LCEL 自动并行执行
chain = (
    {"summary": summarize_chain, "keywords": extract_chain}
    | merge_chain
)
```

### 3.3 内置 Runnable 类型

| Runnable | 用途 | 示例 |
|----------|------|------|
| `RunnablePassthrough` | 透传数据 | 保持原始输入不变 |
| `RunnableLambda` | 包装普通函数 | `RunnableLambda(lambda x: x.upper())` |
| `RunnableParallel` | 并行执行 | 同时执行多个子链 |
| `RunnableBranch` | 条件分支 | 根据条件选择不同路径 |
| `RunnableBinding` | 绑定参数 | 预设模型参数 |

---

## 4. LangGraph 1.0/1.1（Agent 运行时）

LangGraph 已成为 LangChain 生态中 **Agent 编排的核心运行时**（详见 [LangGraph 详解文档](LangGraph图编排框架详解.md)）。

### 4.1 LangGraph 1.1 新特性（2026.03）

| 特性 | 说明 |
|------|------|
| **类型安全 v2 流式** | 结构化事件流，前端可独立消费不同投影 |
| **每节点超时** | `add_node("step", func, timeout=30)` 防止节点卡死 |
| **优雅关闭** | 收到关闭信号后完成当前节点再退出 |
| **DeltaChannel** | 只存储增量而非全量快照，减少 100x 存储开销 |

### 4.2 LangChain vs LangGraph 的分工

| 维度 | LangChain | LangGraph |
|------|-----------|-----------|
| 定位 | 高层工具集 + 快速起步 | 底层运行时 + 精细控制 |
| 抽象层级 | 高（一行代码构建 Agent） | 低（显式定义节点和边） |
| 适用场景 | 快速原型、标准 Agent | 复杂工作流、多 Agent 协作 |
| 关系 | `create_agent` 内部调用 LangGraph | 独立的图编排引擎 |

---

## 5. MCP（Model Context Protocol）集成

MCP 是 Anthropic 提出的**跨模型工具调用协议**，LangChain 通过 `langchain-mcp-adapters` 实现全协议兼容。

```python
# 安装
# pip install langchain-mcp-adapters

from langchain_mcp_adapters import MCPToolAdapter

# 连接 MCP 服务器
mcp_tools = await MCPToolAdapter.from_server(
    "http://localhost:8000/mcp"  # MCP 服务器地址
)

# 将 MCP 工具注入 Agent
agent = create_agent(
    model="deepseek-chat",
    tools=mcp_tools,  # MCP 工具自动转换为 LangChain BaseTool
)
```

**MCP 的价值**：让不同框架（LangChain、LlamaIndex、Semantic Kernel）的工具可以**互通互用**，打破生态壁垒。

---

## 6. LangSmith 平台

LangSmith 是 LangChain 的**商业化平台**，提供从开发到生产的全链路支持。

### 6.1 Fleet（2026 年发布）

无代码 Agent 构建器，支持模板、集成和日常自动化：

- 拖拽式 Agent 编排
- 内置模板库（客服、数据分析、代码生成等）
- 一键部署到生产环境

### 6.2 Engine（2026 年发布）

自动检测 Agent 追踪中的问题并给出修复建议：

- 自动分析执行失败原因
- 生成修复 PR
- 性能瓶颈识别

### 6.3 Managed Deep Agents

托管式 Agent 运行时（私有 Beta），自动处理：
- 执行环境管理
- 上下文管理
- 沙箱隔离
- Checkpoint 持久化

---

## 7. 实战：用 LangChain 1.0 构建 Agent

```python
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver

# 1. 定义工具
@tool
def search_database(query: str) -> str:
    """搜索数据库中的信息"""
    return f"搜索结果: {query} 的相关数据..."

@tool
def calculate(expression: str) -> float:
    """执行数学计算"""
    return eval(expression)

# 2. 创建 Agent
agent = create_agent(
    model="deepseek-chat",
    tools=[search_database, calculate],
    system_prompt="你是一个数据分析助手，擅长从数据库中查询和计算数据。",
    middleware=[
        SummarizationMiddleware(
            max_tokens=4000,
            trigger_at=3000  # 超过 3000 token 自动摘要
        ),
    ],
    checkpointer=MemorySaver(),  # 支持对话记忆
)

# 3. 流式调用
async for event in agent.astream_events(
    {"messages": [{"role": "user", "content": "查询上月销售额，并计算同比增长率"}]},
    version="v3"  # 最新的 v3 流式事件
):
    print(event)
```

---

## 8. 总结

| 概念 | 一句话解释 |
|------|-----------|
| LangChain | 全球最主流的 LLM 应用开发框架（97K+ Star） |
| `create_agent` | v1.0 统一的 Agent 创建入口，底层基于 LangGraph |
| Middleware | 可插拔的钩子系统，细粒度控制 Agent 每一步 |
| Content Blocks | 跨模型厂商的统一输出格式 |
| LCEL | 声明式链式编程语言（`|` 管道符） |
| LangGraph | Agent 编排运行时（图编排、状态管理、持久化） |
| MCP | 跨框架工具调用协议，LangChain 全兼容 |
| LangSmith | 商业化平台（Fleet + Engine + Managed Deep Agents） |

**LangChain 的核心定位**：提供从模型集成、链式编排、Agent 构建到生产部署的**全栈 LLM 应用开发解决方案**。\