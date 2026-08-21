# =============================================================================
# 【模型映射层】表信息 Mapper（TableInfoMapper）
# 作用：实现「实体（TableInfo）↔ ORM 模型（TableInfoMySQL）」的双向转换。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   TableInfoMapper ..> TableInfo       （实体）
#   TableInfoMapper ..> TableInfoMySQL  （ORM 模型）
#   被 MetaMySQLRepository 调用，完成 Entity 与 Model 的桥接
# =============================================================================

from dataclasses import asdict

from app.entities.table_info import TableInfo
from app.models.table_info_mysql import TableInfoMySQL


class TableInfoMapper:
    """表信息实体与 ORM 模型的转换器"""

    @staticmethod
    def to_entity(table_info_mysql: TableInfoMySQL) -> TableInfo:
        """ORM 模型 → 业务实体（数据库记录读取时使用）

        参数：table_info_mysql  TableInfoMySQL  ORM 模型实例
        返回：TableInfo         表信息业务实体
        """
        return TableInfo(
            id=table_info_mysql.id,
            name=table_info_mysql.name,
            role=table_info_mysql.role,
            description=table_info_mysql.description
        )

    @staticmethod
    def to_model(table_info: TableInfo) -> TableInfoMySQL:
        """业务实体 → ORM 模型（数据库写入时使用）

        参数：table_info  TableInfo        表信息业务实体
        返回：TableInfoMySQL               ORM 模型实例
        """
        return TableInfoMySQL(**asdict(table_info))
