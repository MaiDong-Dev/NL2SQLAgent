# =============================================================================
# 【模型层】字段信息 ORM 模型（ColumnInfoMySQL）
# 作用：映射 Meta MySQL 数据库中的 column_info 表，持久化存储字段元数据。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   - 继承 Base（models/base.py）
#   - 与实体 ColumnInfo 通过 ColumnInfoMapper 相互转换
#   - 由 MetaMySQLRepository 执行写入/查询
# =============================================================================

from sqlalchemy import String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class ColumnInfoMySQL(Base):
    """字段信息表模型（对应 Meta MySQL 的 column_info 表）"""
    __tablename__ = "column_info"           # 数据库表名

    id: Mapped[str] = mapped_column(        # 列编号（主键），格式 "{表名}.{字段名}"
        String(64),
        primary_key=True,
        comment="列编号"
    )
    name: Mapped[str | None] = mapped_column(   # 列名称
        String(128),
        comment="列名称"
    )
    type: Mapped[str | None] = mapped_column(   # 数据类型（如 decimal、varchar）
        String(64),
        comment="数据类型"
    )
    role: Mapped[str | None] = mapped_column(   # 列角色：primary_key/foreign_key/measure/dimension
        String(32),
        comment="列类型(primary_key,foreign_key,measure,dimension)"
    )
    examples: Mapped[dict | list | None] = mapped_column(   # 数据示例（JSON 存储）
        JSON,
        comment="数据示例"
    )
    description: Mapped[str | None] = mapped_column(        # 列描述
        Text,
        comment="列描述"
    )
    alias: Mapped[dict | list | None] = mapped_column(      # 列别名（JSON 存储）
        JSON,
        comment="列别名"
    )
    table_id: Mapped[str | None] = mapped_column(           # 所属表编号
        String(64),
        comment="所属表编号"
    )
