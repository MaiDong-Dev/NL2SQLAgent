# =============================================================================
# 【实体层】字段信息实体（ColumnInfo）
# 作用：定义「数据表字段」的领域实体，是 RAG 系统中字段元数据在内存中的统一载体。
#
# 组合关系（在架构中的位置，见 docs/architecture-02-class-diagram）：
#   - 上游来源：由 MetaKnowledgeService 依据 MetaConfig（ColumnConfig）构建
#   - 存储映射：ColumnInfoMapper.to_model() → ColumnInfoMySQL（写入 Meta MySQL）
#              ColumnQdrantRepository.upsert() → 作为 payload 存入 Qdrant 向量库
#   - 下游消费：召回节点（recall_column）从 Qdrant 反序列化得到，流转于
#              DataAgentState.retrieved_columns，最终由 merge 节点组装为
#              ColumnInfoState 供 LLM 使用
#
# 说明：本实体为「纯数据类」（dataclass），无业务逻辑，仅作为数据传递载体，
#       贯穿「构建 → 存储 → 召回 → 生成 SQL」全链路。
# =============================================================================

from dataclasses import dataclass
from typing import Any


@dataclass
class ColumnInfo:
    """数据表字段信息实体

    字段说明：
    - id:          字段全局唯一标识，格式 "{表名}.{字段名}"（如 "fact_order.order_amount"）
    - name:        字段名（如 "order_amount"）
    - type:        字段数据类型（如 "decimal(10,2)"、"varchar(255)"）
    - role:        字段角色：primary_key / foreign_key / measure / dimension
    - examples:    字段示例取值列表（用于帮助 LLM 理解数据分布）
    - description: 字段业务描述（如 "订单金额"）
    - alias:       字段别名列表（用于多维度向量召回覆盖）
    - table_id:    所属表 ID（即所属表的 name，如 "fact_order"）
    """
    id: str
    name: str
    type: str
    role: str
    examples: list[Any]
    description: str
    alias: list[str]
    table_id: str
