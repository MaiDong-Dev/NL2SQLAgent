# =============================================================================
# 【数据库交互模块】SQL 验证节点
# 作用：在数据仓库中执行 EXPLAIN 语句验证 SQL 语法正确性，但不实际执行查询。
#       这是整个 Pipeline 的"质量门禁"，只有验证通过的 SQL 才能进入执行阶段。
# 上下文传递：
#   - 输入：state["sql"] → 待验证的 SQL
#   - 中间：runtime.context["dw_mysql_repository"] → 执行 EXPLAIN 验证
#   - 输出：{"error": None | "error_message"} → 决定条件分支走向
# 验证策略：
#   - 使用 MySQL 的 EXPLAIN 命令验证 SQL 语法（不实际执行，零副作用）
#   - 验证通过 → error=None，流程进入 execute_sql
#   - 验证失败 → error=异常信息，流程进入 correct_sql（修正后重新执行）
# 设计意图：
#   - 在实际执行前做语法检查，避免 LLM 生成的错误 SQL 直接打到生产库
#   - EXPLAIN 比直接执行更安全，不会产生数据变更或耗时查询
# =============================================================================

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import DataAgentState
from server.core.log import logger


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "验证SQL", "status": "running"})

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    sql = state["sql"]

    try:
        # 使用 EXPLAIN 验证 SQL 语法（不实际执行查询）
        # mysql 中 EXPLAIN 会解析 SQL 并返回执行计划，格式错误会抛异常
        await dw_mysql_repository.validate_sql(sql)
        writer({"type": "progress", "step": "验证SQL", "status": "success"})
        logger.info(f"SQL验证成功: {sql}")
        return {"error": None}
    except Exception as e:
        writer({"type": "progress", "step": "验证SQL", "status": "error"})
        logger.error(f"SQL验证失败: {sql}")
        return {"error": str(e)}