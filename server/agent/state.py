# =============================================================================
# 【Agent 状态定义】DataAgentState
# 作用：定义 LangGraph 工作流中各节点之间共享的状态数据结构。每个节点读取
#       state 中的输入字段，处理后返回部分更新字段，实现节点间的数据传递。
# 上下文传递逻辑：
#   - State 是 LangGraph 的"数据总线"，每个节点通过函数参数接收当前 state
#   - 节点的返回值会与当前 state 合并（浅合并），传递给下游节点
#   - 例如：extract_keywords 返回 {"keywords": [...]}，下游节点即可读取
# =============================================================================

from typing import TypedDict

from server.entities.column_info import ColumnInfo
from server.entities.metric_info import MetricInfo
from server.entities.value_info import ValueInfo


class ColumnInfoState(TypedDict):
    """字段信息状态（精简版，用于传递给 LLM 的 Prompt）"""
    name: str
    type: str
    role: str
    examples: list
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    """表信息状态（精简版，用于传递给 LLM 的 Prompt）"""
    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class MetricInfoState(TypedDict):
    """指标信息状态（精简版，用于传递给 LLM 的 Prompt）"""
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]


class DateInfoState(TypedDict):
    """日期上下文信息——帮助 LLM 理解"今天"、"本月"等相对时间"""
    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict):
    """数据库环境信息——帮助 LLM 生成符合特定数据库方言的 SQL"""
    dialect: str
    version: str


class DataAgentState(TypedDict):
    """DataAgent 主状态——贯穿整个 Agent 工作流的数据总线
    
    各字段在 pipeline 中的流转：
    1. query          → 用户输入，全程不变
    2. keywords       → extract_keywords 节点生成，供召回节点使用
    3. retrieved_*    → 三个召回节点并行填充，供 merge 节点合并
    4. table_infos    → merge 节点生成，经 filter_table 裁剪后传给 generate_sql
    5. metric_infos   → merge 节点生成，经 filter_metric 裁剪后传给 generate_sql
    6. date_info      → add_extra_context 节点生成，传给 generate_sql
    7. db_info        → add_extra_context 节点生成，传给 generate_sql
    8. sql            → generate_sql 节点生成，经 validate→correct 循环后传给 execute_sql
    9. error          → validate_sql 节点设置，correct_sql 节点消费后清空
    """
    query: str  # 用户查询
    keywords: list[str]  # 用户查询的关键字

    retrieved_columns: list[ColumnInfo]  # 召回的字段信息
    retrieved_values: list[ValueInfo]  # 召回的值信息
    retrieved_metrics: list[MetricInfo]  # 召回的指标信息

    table_infos: list[TableInfoState]  # 表信息
    metric_infos: list[MetricInfoState]  # 指标信息

    date_info: DateInfoState  # 日期信息
    db_info: DBInfoState  # 数据库信息

    sql: str  # 生成的SQL

    error: str  # 验证SQL时的错误信息