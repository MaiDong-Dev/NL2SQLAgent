# =============================================================================
# 【实体层】指标信息实体（MetricInfo）
# 作用：定义「业务指标」的领域实体，是 RAG 系统中指标元数据在内存中的统一载体。
#
# 组合关系（在架构中的位置，见 docs/architecture-02-class-diagram）：
#   - 上游来源：由 MetaKnowledgeService 依据 MetricConfig 构建
#   - 存储映射：MetricInfoMapper.to_model() → MetricInfoMySQL（写入 Meta MySQL）
#              MetricQdrantRepository.upsert() → 作为 payload 存入 Qdrant 向量库
#   - 下游消费：召回节点（recall_metric）从 Qdrant 反序列化得到，流转于
#              DataAgentState.retrieved_metrics，最终由 merge 节点组装为
#              MetricInfoState 供 LLM 生成 SQL 时遵循指标口径
# =============================================================================

from dataclasses import dataclass


@dataclass
class MetricInfo:
    """业务指标信息实体

    字段说明：
    - id:               指标唯一标识（即指标 name，如 "转正率"）
    - name:             指标名称（如 "转正率"）
    - description:      指标业务描述（如 "实习生转正通过率"），用于语义召回
    - relevant_columns: 该指标计算所依赖的字段 ID 列表
    - alias:            指标别名列表（用于多维度向量召回覆盖）
    """
    id: str
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]
