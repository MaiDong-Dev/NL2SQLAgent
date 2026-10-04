# =============================================================================
# 【数据库交互模块】SQL 验证节点
# 作用：在数据仓库中执行 EXPLAIN 语句验证 SQL 语法正确性，但不实际执行查询。
#       这是整个 Pipeline 的"质量门禁"，只有验证通过的 SQL 才能进入执行阶段。
# 上下文传递：
#   - 输入：state["sql"] → 待验证的 SQL
#   - 中间：runtime.context["dw_mysql_repository"] → 执行 EXPLAIN 验证
#   - 输出：{"error": None | "error_message"} → 决定条件分支走向
# 验证策略：
#   - 第一道：**SQL 只读门禁**（`check_read_only`），拦截写操作/DDL/多语句。
#     必须先做这一步：`EXPLAIN DELETE` 在 MySQL 里是合法语句、能解析通过，
#     光靠 EXPLAIN 拦不住写操作。
#   - 第二道：EXPLAIN 验证语法（不实际执行，零副作用）
#   - 通过 → error=None，流程进入 execute_sql
#   - 失败 → error=异常信息，流程进入 correct_sql（修正后重新执行）
# 设计意图：
#   - 在实际执行前做语法检查，避免 LLM 生成的错误 SQL 直接打到生产库
#   - EXPLAIN 比直接执行更安全，不会产生数据变更或耗时查询
# =============================================================================

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.events import EventType, RunStatus
from server.agent.sql_guard import check_read_only
from server.agent.state import DataAgentState
from server.core.log import logger


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]) -> dict:
    writer = runtime.stream_writer
    writer({"type": EventType.PROGRESS, "step": "验证SQL", "status": RunStatus.RUNNING})

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    sql = state["sql"]

    # 第一道门禁：只读校验（EXPLAIN 拦不住 DELETE/UPDATE，必须在代码层先拦）
    reject_reason = check_read_only(sql)
    if reject_reason is not None:
        writer({"type": EventType.PROGRESS, "step": "验证SQL", "status": RunStatus.ERROR})
        logger.error(f"SQL只读校验未通过: {reject_reason} | SQL: {sql}")
        return {"error": f"SQL 只读校验未通过：{reject_reason}"}

    try:
        # 使用 EXPLAIN 验证 SQL 语法（不实际执行查询）
        # mysql 中 EXPLAIN 会解析 SQL 并返回执行计划，格式错误会抛异常
        await dw_mysql_repository.validate_sql(sql)
        writer({"type": EventType.PROGRESS, "step": "验证SQL", "status": RunStatus.SUCCESS})
        logger.info(f"SQL验证成功: {sql}")
        return {"error": None}
    except Exception as e:
        writer({"type": EventType.PROGRESS, "step": "验证SQL", "status": RunStatus.ERROR})
        # 带上异常本体 e：只有 SQL 文本看不出失败原因，排查时很痛苦
        logger.error(f"SQL验证失败: {sql} | 原因: {e}")
        return {"error": str(e)}
