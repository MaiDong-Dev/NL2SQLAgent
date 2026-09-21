# =============================================================================
# 【实体层】字段取值实体（ValueInfo）
# 作用：定义「字段具体取值」的领域实体，用于 Elasticsearch 全文检索召回。
#
# 组合关系（在架构中的位置，见 docs/architecture-02-class-diagram）：
#   - 上游来源：由 MetaKnowledgeService._save_value_info_to_es() 依据配置中
#              sync=true 的字段，从 DW 查询 distinct 取值构建
#   - 存储映射：ValueESRepository.index() → 写入 Elasticsearch（app_config.es.index_name 索引）
#   - 下游消费：recall_value 节点从 ES 反序列化得到，流转于
#              DataAgentState.retrieved_values，最终由 merge 节点将取值追加到
#              对应字段的 examples 中
#
# 为什么字段取值单独建模？
#   取值（如"北京"/"在职"）是离散枚举值，适合 ES 倒排索引精确匹配；
#   而字段/指标（抽象概念）适合 Qdrant 向量语义匹配，故分层建模、分层存储。
# =============================================================================

from dataclasses import dataclass


@dataclass
class ValueInfo:
    """字段取值实体

    字段说明：
    - id:        取值唯一标识，格式 "{字段ID}.{取值}"（如 "dim_intern.转正状态.已转正"）
    - value:     具体取值内容（如 "已转正"）
    - column_id: 所属字段 ID（如 "dim_intern.转正状态"）
    """
    id: str
    value: str
    column_id: str
