# =============================================================================
# 【数据库交互模块】SQL 执行节点
# 作用：在数据仓库中实际执行验证通过的 SQL 查询，并将结果以流式方式返回给用户。
#       这是整个 Pipeline 的终点节点。
# 上下文传递：
#   - 输入：state["sql"] → 已验证通过的 SQL
#   - 中间：runtime.context["dw_mysql_repository"] → 执行 SQL 查询
#   - 输出：通过 stream_writer 将结果写入 SSE 流（不更新 state）
# 设计意图：
#   - 使用 SSE（Server-Sent Events）流式返回结果，支持实时进度展示
#   - 结果以 dict 列表形式返回，每行数据为一个 dict
#   - 此节点不返回 state 更新（因为已到终点），直接通过 writer 输出
# =============================================================================

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import DataAgentState
from server.core.log import logger


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "执行SQL", "status": "running"})

    sql = state["sql"]

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    try:
        # 在数据仓库中执行 SQL 查询
        # 返回结果为 list[dict]，每行数据为 {列名: 值} 的字典
        result = await dw_mysql_repository.execute_sql(sql)

        writer({"type": "progress", "step": "执行SQL", "status": "success"})
        # 将查询结果通过 SSE 流返回给前端
        writer({"type": "result", "data": result})
        logger.info(f"执行SQL结果: {result}")


    except Exception as e:
        writer({"type": "progress", "step": "执行SQL", "status": "error"})
        logger.error(f"执行SQL失败:{str(e)}")
        raise