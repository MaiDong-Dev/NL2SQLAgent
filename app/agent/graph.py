# =============================================================================
# 【Agent 工作流编排】LangGraph 图定义
# 作用：使用 LangGraph 框架定义 NL2SQL 的完整处理流水线，将各个节点
#       （提取关键词→多路召回→合并→过滤→补充上下文→生成SQL→验证→校正→执行）
#       编排为有向无环图（DAG）并编译为可执行的工作流。
#
# 上下文传递逻辑：
#   - State（DataAgentState）：节点间传递的业务数据，在图中自动流转
#   - Context（DataAgentContext）：基础设施依赖，在 graph.astream(context=...) 时注入
#   - 每个节点函数签名：(state, runtime) -> dict，返回的 dict 与 state 合并
#
# 工作流拓扑（Pipeline 结构）：
#   START
#     ↓
#   extract_keywords（关键词提取）
#     ↓
#   ┌─────────────────┬─────────────────┐
#   ↓                 ↓                 ↓
#   recall_column    recall_value     recall_metric
#   （字段向量召回）  （取值ES召回）    （指标向量召回）
#     ↓                 ↓                 ↓
#   └─────────────────┴─────────────────┘
#     ↓
#   merge_retrieved_info（合并召回结果，补全元数据）
#     ↓
#   ┌─────────────────┐
#   ↓                 ↓
#   filter_table     filter_metric
#   （LLM裁剪表/字段）（LLM裁剪指标）
#     ↓                 ↓
#   └─────────────────┘
#     ↓
#   add_extra_context（补充日期、DB环境信息）
#     ↓
#   generate_sql（LLM 生成 SQL）
#     ↓
#   validate_sql（EXPLAIN 验证）
#     ↓
#   ┌─ error is None? ──→ execute_sql（执行并返回结果）
#   │                                     ↓
#   └─ error exists? ──→ correct_sql ────→ END
#                        （LLM修正SQL）
# =============================================================================

import asyncio

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from app.agent.context import DataAgentContext
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

# 构建 LangGraph 状态图，指定 state 和 context 的类型
graph_builder = StateGraph(state_schema=DataAgentState, context_schema=DataAgentContext)

# =============================================================================
# 注册所有节点
# =============================================================================
graph_builder.add_node("extract_keywords", extract_keywords)       # 步骤1：提取关键词
graph_builder.add_node("recall_column", recall_column)             # 步骤2a：向量召回字段
graph_builder.add_node("recall_value", recall_value)               # 步骤2b：ES 召回字段取值
graph_builder.add_node("recall_metric", recall_metric)             # 步骤2c：向量召回指标
graph_builder.add_node("merge_retrieved_info", merge_retrieved_info)  # 步骤3：合并召回结果
graph_builder.add_node("filter_metric", filter_metric)             # 步骤4a：LLM 裁剪指标
graph_builder.add_node("filter_table", filter_table)               # 步骤4b：LLM 裁剪表/字段
graph_builder.add_node("add_extra_context", add_extra_context)     # 步骤5：补充上下文
graph_builder.add_node("generate_sql", generate_sql)               # 步骤6：LLM 生成 SQL
graph_builder.add_node("validate_sql", validate_sql)               # 步骤7：EXPLAIN 验证 SQL
graph_builder.add_node("correct_sql", correct_sql)                 # 步骤8：LLM 修正 SQL
graph_builder.add_node("execute_sql", execute_sql)                 # 步骤9：执行 SQL

# =============================================================================
# 定义节点间的边（数据流向）
# =============================================================================

# --- 阶段1：关键词提取 → 三路并行召回 ---
graph_builder.add_edge(START, "extract_keywords")
graph_builder.add_edge("extract_keywords", "recall_column")
graph_builder.add_edge("extract_keywords", "recall_value")
graph_builder.add_edge("extract_keywords", "recall_metric")

# --- 阶段2：三路召回 → 合并 ---
graph_builder.add_edge("recall_column", "merge_retrieved_info")
graph_builder.add_edge("recall_value", "merge_retrieved_info")
graph_builder.add_edge("recall_metric", "merge_retrieved_info")

# --- 阶段3：合并 → 并行过滤（表/指标） ---
graph_builder.add_edge("merge_retrieved_info", "filter_table")
graph_builder.add_edge("merge_retrieved_info", "filter_metric")

# --- 阶段4：过滤 → 补充上下文 → 生成 SQL ---
graph_builder.add_edge("filter_table", "add_extra_context")
graph_builder.add_edge("filter_metric", "add_extra_context")
graph_builder.add_edge("add_extra_context", "generate_sql")

# --- 阶段5：SQL 验证 → 条件分支 ---
graph_builder.add_edge("generate_sql", "validate_sql")

# 条件边：根据 validate_sql 的结果决定下一步
#   - error 为 None（验证通过）→ 执行 SQL
#   - error 不为 None（验证失败）→ 进入 SQL 校正流程
graph_builder.add_conditional_edges("validate_sql",
                                    lambda state: "execute_sql" if state["error"] is None else "correct_sql",
                                    {"execute_sql": "execute_sql", "correct_sql": "correct_sql"})

# --- 阶段6：SQL 校正 → 执行 → 结束 ---
graph_builder.add_edge("correct_sql", "execute_sql")
graph_builder.add_edge("execute_sql", END)

# 编译图为可执行的工作流
graph = graph_builder.compile()


if __name__ == '__main__':
    async def test():
        embedding_client_manager.init()
        qdrant_client_manager.init()
        es_client_manager.init()
        meta_mysql_client_manager.init()
        dw_mysql_client_manager.init()

        async with meta_mysql_client_manager.session_factory() as meta_session, dw_mysql_client_manager.session_factory() as dw_session:
            meta_mysql_repository = MetaMySQLRepository(meta_session)
            dw_mysql_repository = DWMySQLRepository(dw_session)
            column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
            value_es_repository = ValueESRepository(es_client_manager.client)
            metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)

            context = DataAgentContext(
                embedding_client=embedding_client_manager.client,
                column_qdrant_repository=column_qdrant_repository,
                value_es_repository=value_es_repository,
                metric_qdrant_repository=metric_qdrant_repository,
                meta_mysql_repository=meta_mysql_repository,
                dw_mysql_repository=dw_mysql_repository
            )
            state = DataAgentState(query="统计去年各地区的销售总额")
            async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
                print(chunk)

        await qdrant_client_manager.close()
        await es_client_manager.close()
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()


    asyncio.run(test())