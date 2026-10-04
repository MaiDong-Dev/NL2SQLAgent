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
#   enrich_metric_columns（按筛选后的指标补全其关联字段）
#     ↓
#   add_extra_context（补充日期、DB环境信息）
#     ↓
#   generate_sql（LLM 生成 SQL）
#     ↓
#   validate_sql（EXPLAIN 验证）
#     ↓
#   ┌─ error is None? ──→ execute_sql ──→ END
#   │
#   └─ error exists? ──→ correct_sql ──→ 回到 validate_sql 重新验证
#                        （LLM修正SQL）   （最多 N 次；用尽则进 execute_sql 放弃执行）
# =============================================================================


from langgraph.constants import END, START
from langgraph.graph import StateGraph

from server.agent.context import DataAgentContext
from server.agent.nodes.add_extra_context import add_extra_context
from server.agent.nodes.correct_sql import correct_sql
from server.agent.nodes.enrich_metric_columns import enrich_metric_columns
from server.agent.nodes.execute_sql import execute_sql
from server.agent.nodes.extract_keywords import extract_keywords
from server.agent.nodes.filter_metric import filter_metric
from server.agent.nodes.filter_table import filter_table
from server.agent.nodes.generate_sql import generate_sql
from server.agent.nodes.merge_retrieved_info import merge_retrieved_info
from server.agent.nodes.recall_column import recall_column
from server.agent.nodes.recall_metric import recall_metric
from server.agent.nodes.recall_value import recall_value
from server.agent.nodes.validate_sql import validate_sql
from server.agent.state import DataAgentState
from server.conf.app_config import app_config

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
graph_builder.add_node("enrich_metric_columns", enrich_metric_columns)  # 步骤4c：补全选中指标的关联字段
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

# --- 阶段4：过滤 → 补全指标关联字段 → 补充上下文 → 生成 SQL ---
# enrich_metric_columns 是两个过滤节点的 fan-in：必须等指标筛完、表裁完，
# 才能按「保留下来的指标」补全其关联字段
graph_builder.add_edge("filter_table", "enrich_metric_columns")
graph_builder.add_edge("filter_metric", "enrich_metric_columns")
graph_builder.add_edge("enrich_metric_columns", "add_extra_context")
graph_builder.add_edge("add_extra_context", "generate_sql")

# --- 阶段5：SQL 验证 → 条件分支 ---
graph_builder.add_edge("generate_sql", "validate_sql")


def route_after_validate(state: DataAgentState) -> str:
    """validate_sql 之后往哪走

    - 验证通过（error 为 None）→ 执行
    - 验证失败且还没修够次数 → 交给 LLM 修正，修完**重新验证**（见下方回环边）
    - 验证失败且修正次数已用尽 → 仍走 execute_sql，由它判断 error 非空后
      放弃执行并回传错误（避免图里再引一个终态节点，也保证用户能收到反馈）
    """
    if state.get("error") is None:
        return "execute_sql"
    if state.get("sql_retry_count", 0) >= app_config.sql.max_correction_attempts:
        return "execute_sql"
    return "correct_sql"


graph_builder.add_conditional_edges(
    "validate_sql",
    route_after_validate,
    {
        "execute_sql": "execute_sql",
        "correct_sql": "correct_sql"
    }
)

# --- 阶段6：SQL 校正 → 重新验证（回环）→ 执行 → 结束 ---
# 注意：修正后的 SQL 必须再走一遍 validate_sql。原先这里直接连 execute_sql，
# 意味着 LLM 改写的 SQL 从未经过校验（连只读门禁都可能被绕过）就直接执行了。
graph_builder.add_edge("correct_sql", "validate_sql")
graph_builder.add_edge("execute_sql", END)

# 编译图为可执行的工作流
graph = graph_builder.compile()


if __name__ == '__main__':
    #async def test():
    #    lifespan()
#
    #    async with meta_mysql_client_manager.session_factory() as meta_session, dw_mysql_client_manager.session_factory() as dw_session:
    #        meta_mysql_repository = MetaMySQLRepository(meta_session)
    #        dw_mysql_repository = DWMySQLRepository(dw_session)
    #        column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
    #        value_es_repository = ValueESRepository(es_client_manager.client)
    #        metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)
#
    #        context = DataAgentContext(
    #            embedding_client=embedding_client_manager.client,
    #            column_qdrant_repository=column_qdrant_repository,
    #            value_es_repository=value_es_repository,
    #            metric_qdrant_repository=metric_qdrant_repository,
    #            meta_mysql_repository=meta_mysql_repository,
    #            dw_mysql_repository=dw_mysql_repository
    #        )
    #        state = DataAgentState(query="统计去年各地区的销售总额")
    #        async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
    #            print(chunk)
#
    #    await qdrant_client_manager.close()
    #    await es_client_manager.close()
    #    await meta_mysql_client_manager.close()
    #    await dw_mysql_client_manager.close()
#
#
    #asyncio.run(test())

    print(graph.get_graph().draw_mermaid())
