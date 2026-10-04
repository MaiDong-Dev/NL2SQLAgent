# =============================================================================
# 【协议枚举】SSE 事件协议与执行状态
# 作用：把散落在各节点与前端之间的字符串字面量收敛成枚举，消灭拼写错误。
#
# 为什么用 StrEnum 而不是普通 Enum：
#   这些值最终要 json.dumps 后经 SSE 发给前端，前端按字符串比较。
#   StrEnum 的成员**本身就是 str**，json.dumps({"type": EventType.PROGRESS})
#   序列化出来仍然是 {"type": "progress"}——与改造前的裸字符串完全一致，
#   因此前端、SSE 线协议、历史 CSV 都不需要任何改动。
#   （普通 Enum 序列化会变成 "EventType.PROGRESS"，那才是破坏性变更。）
#
# 为什么值得收敛：改造前 "progress"/"result"/"error" 在仓库里硬编码了 46 处、
#   "status": "running"/"success" 各 13 处、执行结论 "correct" 12 处。
#   把某处的 "success" 误写成 "sucess"，前端会不认这个状态、那一步永远转圈，
#   而 Python 不会有任何提示——这类错误只能靠枚举在赋值时就拦住。
# =============================================================================

from enum import StrEnum


class EventType(StrEnum):
    """SSE 事件类型（前端 frontend/src/App.vue 按此分发处理）

    协议约定（见 server/agent/nodes/execute_sql.py 与 query_service.py）：
      progress → 一条处理进度，字段 step + status
      result   → 最终查询结果，data 为 list[dict]
      error    → 链路异常，message 为错误描述
    result 与 error 互斥，同一次查询不应同时出现。
    """
    PROGRESS = "progress"
    RESULT = "result"
    ERROR = "error"


class RunStatus(StrEnum):
    """单个节点的执行状态（EventType.PROGRESS 事件的 status 字段）

    前端据此渲染时间轴：running 转圈、success 打勾、error 打叉。
    """
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ExecAccuracy(StrEnum):
    """执行准确性判定结论（评测指标 execution_accuracy 的取值）

    与 eval/run_ragas_eval.py 的 discrete_metric(allowed_values=...) 保持一致：
      correct    → 结果集一致
      incorrect  → 生成失败、结果不一致
      empty_both → 两边都返回 0 行，空集==空集不能证明等价，不计通过
    """
    CORRECT = "correct"
    INCORRECT = "incorrect"
    EMPTY_BOTH = "empty_both"
