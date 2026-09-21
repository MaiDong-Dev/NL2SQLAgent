# =============================================================================
# 【配置层】元知识配置（MetaConfig）
# 作用：定义「元知识库构建」所需的配置结构，即描述数据仓库中有哪些表、字段、
#       指标，以及每个字段/指标的业务语义（名称、角色、描述、别名等）。
#
# 用途（组合关系）：
#   - 被 MetaKnowledgeService.build() 使用（见 meta_builder/services/meta_knowledge_service.py）
#   - 由命令行脚本（meta_builder/scripts/build_meta_knowledge.py）加载，
#     依据 meta_config.yaml 将表/字段/指标定义同步到三大存储引擎：
#       1. Meta MySQL   —— 结构化元数据（表/字段/指标定义）
#       2. Qdrant       —— 字段与指标的 Embedding 向量索引
#       3. Elasticsearch—— 字段取值的全文倒排索引
#
# 配置结构层级（与 meta_config.yaml 对应）：
#   MetaConfig
#   ├── tables: list[TableConfig]       表定义列表
#   │   └── columns: list[ColumnConfig] 每张表的字段定义列表
#   └── metrics: list[MetricConfig]     指标定义列表
#
# 与实体层（entities/）的对应关系：
#   TableConfig  → TableInfo
#   ColumnConfig → ColumnInfo
#   MetricConfig → MetricInfo
# 配置是「声明式输入」，实体是「运行时载体」，由 MetaKnowledgeService 完成转换。
# =============================================================================

from dataclasses import dataclass
from typing import Optional


@dataclass
class ColumnConfig:
    """字段定义配置（描述数据仓库中某张表的一个字段）

    字段说明：
    - name:        字段名（如 "order_amount"）
    - role:        字段角色，取值：primary_key / foreign_key / measure / dimension
                   （主键 / 外键 / 度量 / 维度）
    - description: 字段业务描述（如 "订单金额"），用于生成 Embedding 做语义召回
    - alias:       字段别名列表（如 ["销售额", "成交额"]），用于多维度召回覆盖
    - sync:        是否将该字段的取值同步到 Elasticsearch 建立全文索引
                   （仅对离散枚举值/实体名类型的字段设为 True）
    """
    name: str
    role: str
    description: str
    alias: list[str]
    sync: bool


@dataclass
class TableConfig:
    """表定义配置（描述数据仓库中的一张表）

    字段说明：
    - name:        表名（如 "fact_order"）
    - role:        表角色：fact（事实表）/ dim（维度表）
    - description: 表业务描述
    - columns:     该表包含的字段定义列表
    """
    name: str
    role: str
    description: str
    columns: list[ColumnConfig]


@dataclass
class MetricConfig:
    """指标定义配置（描述一个业务指标的计算口径）

    字段说明：
    - name:             指标名（如 "转正率"）
    - description:      指标描述（如 "实习生转正通过率"），用于语义召回
    - relevant_columns: 该指标计算所依赖的字段 ID 列表（如 ["dim_intern.转正状态"]）
                        —— 召回该指标时，这些字段会被强制加入，保证 SQL 可生成
    - alias:            指标别名列表（如 ["转正比例"]），用于多维度召回覆盖
    """
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]


@dataclass
class MetaConfig:
    """元知识总配置：聚合表定义与指标定义

    说明：
    - tables/metrics 均为 Optional，允许只配置表或只配置指标
    - MetaKnowledgeService.build() 会分别判断二者是否存在再处理
    """
    tables: Optional[list[TableConfig]] = None
    metrics: Optional[list[MetricConfig]] = None
