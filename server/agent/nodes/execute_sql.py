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
#
# 本节点的三道护栏（SQL 由 LLM 生成，不可信，必须兜底）：
#   1. 放弃路径：若上游 error 非空（修正次数用尽仍未通过校验），**不执行**，
#      直接把错误推给前端 —— 修正后的 SQL 从来没被重新验证过，不能盲目执行。
#   2. 只读门禁：执行前再校验一次（`check_read_only`）。这是最后一道硬门禁，
#      validate_sql 之后 SQL 还可能被 correct_sql 改写过。
#   3. 超时 + 行数上限：5 万单的库上，一句没聚合好的 SQL 可能返回数万行、
#      或跑几分钟，必须限时限量，否则会拖垮服务、撑爆前端与日志。
# =============================================================================

import asyncio

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.events import EventType, RunStatus
from server.agent.sql_guard import check_read_only
from server.agent.state import DataAgentState
from server.conf.app_config import app_config
from server.core.log import logger

# 日志里最多打印几行结果（完整结果集可能上万行，且含业务数据，不能全量落日志）
LOG_SAMPLE_ROWS = 3


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]) -> dict:
    writer = runtime.stream_writer
    writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.RUNNING})

    sql = state["sql"]

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    # 护栏 1：上游仍有未解决的错误（修正次数用尽）→ 放弃执行，只回传错误
    pending_error = state.get("error")
    if pending_error:
        writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.ERROR})
        logger.error(f"SQL校验未通过，放弃执行: {pending_error} | SQL: {sql}")
        writer({"type": EventType.ERROR, "message": f"SQL 校验未通过，已放弃执行：{pending_error}"})
        return {}

    # 护栏 2：只读门禁（最后一道，拦住任何绕过 validate_sql 的写操作）
    reject_reason = check_read_only(sql)
    if reject_reason is not None:
        writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.ERROR})
        logger.error(f"SQL只读校验未通过，拒绝执行: {reject_reason} | SQL: {sql}")
        writer({"type": EventType.ERROR, "message": f"SQL 只读校验未通过，已拒绝执行：{reject_reason}"})
        return {}

    try:
        # 护栏 3：超时保护 + 执行查询，返回结果为 list[dict]
        result = await asyncio.wait_for(
            dw_mysql_repository.execute_sql(sql),
            timeout=app_config.sql.execution_timeout_seconds,
        )

        # 行数上限：超出部分直接截断并告知前端，避免几万行撑爆内存/前端渲染
        max_rows = app_config.sql.max_result_rows
        truncated = len(result) > max_rows
        if truncated:
            result = result[:max_rows]

        writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.SUCCESS})
        # 将查询结果通过 SSE 流返回给前端
        writer({"type": EventType.RESULT, "data": result, "truncated": truncated})
        # 日志只记行数与少量样本：全量结果集既占空间又含业务数据
        logger.info(f"执行SQL成功: {len(result)} 行{'（已截断至上限）' if truncated else ''}"
                    f" | 样本: {result[:LOG_SAMPLE_ROWS]}")

    except TimeoutError:
        writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.ERROR})
        logger.error(f"执行SQL超时（>{app_config.sql.execution_timeout_seconds}s）: {sql}")
        writer({"type": EventType.ERROR,
                "message": f"SQL 执行超时（超过 {app_config.sql.execution_timeout_seconds} 秒），已中止"})
    except Exception as e:
        writer({"type": EventType.PROGRESS, "step": "执行SQL", "status": RunStatus.ERROR})
        logger.error(f"执行SQL失败:{str(e)}")
        raise
