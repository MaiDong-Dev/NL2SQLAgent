# =============================================================================
# 【模型映射层】指标信息 Mapper（MetricInfoMapper）
# 作用：实现「实体（MetricInfo）↔ ORM 模型（MetricInfoMySQL）」的双向转换。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   MetricInfoMapper ..> MetricInfo       （实体）
#   MetricInfoMapper ..> MetricInfoMySQL  （ORM 模型）
#   被 MetaMySQLRepository 调用，完成 Entity 与 Model 的桥接
# =============================================================================

from dataclasses import asdict

from app.entities.metric_info import MetricInfo
from app.models.metric_info_mysql import MetricInfoMySQL


class MetricInfoMapper:
    """指标信息实体与 ORM 模型的转换器"""

    @staticmethod
    def to_entity(model: MetricInfoMySQL) -> MetricInfo:
        """ORM 模型 → 业务实体（数据库记录读取时使用）

        参数：model  MetricInfoMySQL  ORM 模型实例
        返回：MetricInfo             指标信息业务实体
        """
        return MetricInfo(
            id=model.id,
            name=model.name,
            description=model.description,
            relevant_columns=model.relevant_columns,
            alias=model.alias
        )

    @staticmethod
    def to_model(entity: MetricInfo) -> MetricInfoMySQL:
        """业务实体 → ORM 模型（数据库写入时使用）

        参数：entity  MetricInfo        指标信息业务实体
        返回：MetricInfoMySQL           ORM 模型实例
        """
        return MetricInfoMySQL(**asdict(entity))
