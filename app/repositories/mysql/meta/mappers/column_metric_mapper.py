# =============================================================================
# 【模型映射层】字段-指标关联 Mapper（ColumnMetricMapper）
# 作用：实现「实体（ColumnMetric）↔ ORM 模型（ColumnMetricMySQL）」的双向转换。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   ColumnMetricMapper ..> ColumnMetric       （实体）
#   ColumnMetricMapper ..> ColumnMetricMySQL  （ORM 模型）
#   被 MetaMySQLRepository.save_column_metrics() 调用，完成写入转换
# =============================================================================

from dataclasses import asdict

from app.entities.column_metric import ColumnMetric
from app.models.column_metric_mysql import ColumnMetricMySQL


class ColumnMetricMapper:
    """字段-指标关联实体与 ORM 模型的转换器"""

    @staticmethod
    def to_entity(column_metric_mysql: ColumnMetricMySQL) -> ColumnMetric:
        """ORM 模型 → 业务实体（数据库记录读取时使用）"""
        return ColumnMetric(
            column_id=column_metric_mysql.column_id,
            metric_id=column_metric_mysql.metric_id
        )

    @staticmethod
    def to_model(column_metric: ColumnMetric) -> ColumnMetricMySQL:
        """业务实体 → ORM 模型（数据库写入时使用）

        说明：利用 asdict() 将 dataclass 转为 dict 后展开为 ORM 构造参数
        """
        return ColumnMetricMySQL(**asdict(column_metric))
