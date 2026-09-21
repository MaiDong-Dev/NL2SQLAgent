# =============================================================================
# 【模型层】表信息 ORM 模型（TableInfoMySQL）
# 作用：映射 Meta MySQL 数据库中的 table_info 表，持久化存储表元数据。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   - 继承 Base（models/base.py）
#   - 与实体 TableInfo 通过 TableInfoMapper 相互转换
#   - 由 MetaMySQLRepository 执行写入/查询
# =============================================================================

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class TableInfoMySQL(Base):
    """表信息表模型（对应 Meta MySQL 的 table_info 表）"""
    __tablename__ = "table_info"            # 数据库表名

    id: Mapped[str] = mapped_column(        # 表编号（主键，即表 name）
        String(64),
        primary_key=True,
        comment="表编号"
    )
    name: Mapped[str | None] = mapped_column(   # 表名称
        String(128),
        comment="表名称"
    )
    role: Mapped[str | None] = mapped_column(   # 表角色：fact（事实表）/ dim（维度表）
        String(32),
        comment="表类型(fact/dim)"
    )
    description: Mapped[str | None] = mapped_column(    # 表描述
        Text,
        comment="表描述"
    )
