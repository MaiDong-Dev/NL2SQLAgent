# =============================================================================
# 【实体层】字段-指标关联实体（ColumnMetric）
# 作用：定义「字段」与「指标」之间的多对多关联关系，用于记录某个指标的计算
#       依赖哪些字段。
#
# 组合关系（在架构中的位置，见 docs/architecture-02-class-diagram）：
#   - 上游来源：由 MetaKnowledgeService 依据 MetricConfig.relevant_columns 构建
#   - 存储映射：ColumnMetricMapper.to_model() → ColumnMetricMySQL（Meta MySQL 的
#              column_metric 表，column_id + metric_id 联合主键）
#   - 下游用途：merge_retrieved_info 节点在召回指标后，会通过 relevant_columns
#              关联字段，保证 SQL 生成时指标计算所需字段全部就位
#
# 设计意图：
#   指标（如"转正率"）的计算往往依赖多个字段（如"转正状态"+"入职日期"），
#   通过 ColumnMetric 显式记录这种依赖关系，RAG 召回指标时可自动带出所需字段。
# =============================================================================

from dataclasses import dataclass


@dataclass
class ColumnMetric:
    """字段-指标关联实体（多对多关系）

    字段说明：
    - column_id: 字段 ID（如 "dim_intern.转正状态"）
    - metric_id: 指标 ID（即指标 name，如 "转正率"）
    """
    column_id: str
    metric_id: str
