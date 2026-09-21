# =============================================================================
# 【模型层】字段-指标关联 ORM 模型（ColumnMetricMySQL）
# 作用：映射 Meta MySQL 数据库中的 column_metric 表，持久化存储「字段↔指标」
#       的多对多关联关系。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   - 继承 Base（models/base.py）
#   - 与实体 ColumnMetric 通过 ColumnMetricMapper 相互转换
#   - 由 MetaMySQLRepository 执行写入
# =============================================================================

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class ColumnMetricMySQL(Base):
    """字段-指标关联表模型（对应 Meta MySQL 的 column_metric 表）

    说明：column_id 与 metric_id 组成联合主键，保证同一「字段-指标」对唯一。
    """
    __tablename__ = "column_metric"         # 数据库表名

    column_id: Mapped[str] = mapped_column( # 列编号（联合主键之一）
        String(64),
        primary_key=True,
        comment="列编号"
    )
    metric_id: Mapped[str] = mapped_column( # 指标编号（联合主键之一）
        String(64),
        primary_key=True,
        comment="指标编号"
    )
