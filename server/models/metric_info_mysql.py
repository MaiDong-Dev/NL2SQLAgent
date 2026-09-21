# =============================================================================
# 【模型层】指标信息 ORM 模型（MetricInfoMySQL）
# 作用：映射 Meta MySQL 数据库中的 metric_info 表，持久化存储指标元数据。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   - 继承 Base（models/base.py）
#   - 与实体 MetricInfo 通过 MetricInfoMapper 相互转换
#   - 由 MetaMySQLRepository 执行写入/查询
# =============================================================================

from sqlalchemy import String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class MetricInfoMySQL(Base):
    """指标信息表模型（对应 Meta MySQL 的 metric_info 表）"""
    __tablename__ = "metric_info"           # 数据库表名

    id: Mapped[str] = mapped_column(        # 指标编码（主键，即指标 name）
        String(64),
        primary_key=True,
        comment="指标编码"
    )
    name: Mapped[str | None] = mapped_column(   # 指标名称
        String(128),
        comment="指标名称"
    )
    description: Mapped[str | None] = mapped_column(    # 指标描述
        Text,
        comment="指标描述"
    )
    relevant_columns: Mapped[dict | list | None] = mapped_column(   # 关联字段（JSON 存储）
        JSON,
        comment="关联字段"
    )
    alias: Mapped[dict | list | None] = mapped_column(      # 指标别名（JSON 存储）
        JSON,
        comment="指标别名"
    )
