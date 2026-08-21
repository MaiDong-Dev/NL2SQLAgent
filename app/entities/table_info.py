# =============================================================================
# 【实体层】表信息实体（TableInfo）
# 作用：定义「数据表」的领域实体，是 RAG 系统中表元数据在内存中的统一载体。
#
# 组合关系（在架构中的位置，见 docs/architecture-02-class-diagram）：
#   - 上游来源：由 MetaKnowledgeService 依据 TableConfig 构建
#   - 存储映射：TableInfoMapper.to_model() → TableInfoMySQL（写入 Meta MySQL）
#   - 下游消费：merge_retrieved_info 节点通过 MetaMySQLRepository.get_table_info_by_id
#              查询补全，组装为 TableInfoState 供 LLM 生成 SQL
# =============================================================================

from dataclasses import dataclass


@dataclass
class TableInfo:
    """数据表信息实体

    字段说明：
    - id:          表唯一标识（即表 name，如 "fact_order"）
    - name:        表名
    - role:        表角色：fact（事实表）/ dim（维度表）
    - description: 表业务描述
    """
    id: str
    name: str
    role: str
    description: str
