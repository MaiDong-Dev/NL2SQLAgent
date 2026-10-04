# =============================================================================
# 【Agent 层】包级导出
# 作用：收敛状态类型、上下文与确定性工具，调用方写
#       `from server.agent import DataAgentState` 即可。
#
# ⚠️ 刻意**不导出 graph**：
#   `server/agent/graph.py` 会连带导入全部 12 个节点，节点又各自导入 LLM、仓储、
#   prompt 加载器……一旦把它写进本文件，任何一句 `from server.agent.state import ...`
#   都会先把整条 LangGraph 流水线加载一遍，代价是：
#     1. 每次 import 都变慢（评测脚本、单测全受影响）；
#     2. 显著提高循环导入的概率——节点反过来导入本包时会撞上「包尚未初始化完」。
#   正确做法是让调用方显式写 `from server.agent.graph import graph`，
#   把这个"重"依赖暴露在调用点，而不是藏在包初始化里。
#
# 本文件只导出**叶子模块**（state 依赖实体、context 依赖仓储、time_utils 只依赖 re），
# 三者都不反向依赖 agent 内部，因此不会成环。
# =============================================================================

from server.agent.context import DataAgentContext
from server.agent.state import (
    ColumnInfoState,
    DataAgentState,
    DateInfoState,
    DBInfoState,
    MetricInfoState,
    TableInfoState,
)
from server.agent.time_utils import has_explicit_year, has_time_semantic, is_time_dimension_table

__all__ = [
    # 上下文与状态
    "DataAgentContext",
    "DataAgentState",
    "DateInfoState",
    "DBInfoState",
    "ColumnInfoState",
    "TableInfoState",
    "MetricInfoState",
    # 确定性时间规则（时间维表的召回补偿，见 time_utils 模块说明）
    "has_time_semantic",
    "has_explicit_year",
    "is_time_dimension_table",
]
