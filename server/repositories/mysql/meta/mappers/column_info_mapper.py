# =============================================================================
# 【模型映射层】字段信息 Mapper（ColumnInfoMapper）
# 作用：实现「实体（ColumnInfo）↔ ORM 模型（ColumnInfoMySQL）」的双向转换。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   ColumnInfoMapper ..> ColumnInfo        （实体）
#   ColumnInfoMapper ..> ColumnInfoMySQL   （ORM 模型）
#   被 MetaMySQLRepository 调用，完成 Entity 与 Model 的桥接
#
# 设计意图：
#   - 实体层（entities/）与存储解耦，模型层（models/）与存储绑定
#   - Mapper 层负责二者转换，使 Repository 只操作实体，数据库细节被隔离
#   - to_entity 用于「读」：数据库记录 → 业务实体（供召回/补全使用）
#   - to_model  用于「写」：业务实体 → 数据库记录（供元数据构建写入使用）
# =============================================================================

from dataclasses import asdict

from server.entities.column_info import ColumnInfo
from server.models.column_info_mysql import ColumnInfoMySQL


class ColumnInfoMapper:
    """字段信息实体与 ORM 模型的转换器"""

    @staticmethod
    def to_entity(column_info_mysql: ColumnInfoMySQL) -> ColumnInfo:
        """ORM 模型 → 业务实体（数据库记录读取时使用）

        参数：column_info_mysql  数据库查询得到的 ORM 模型实例
        返回：ColumnInfo         字段信息业务实体
        """
        return ColumnInfo(
            id=column_info_mysql.id,
            name=column_info_mysql.name,
            type=column_info_mysql.type,
            role=column_info_mysql.role,
            examples=column_info_mysql.examples,
            description=column_info_mysql.description,
            alias=column_info_mysql.alias,
            table_id=column_info_mysql.table_id,
        )

    @staticmethod
    def to_model(column_info: ColumnInfo) -> ColumnInfoMySQL:
        """业务实体 → ORM 模型（数据库写入时使用）

        参数：column_info  字段信息业务实体
        返回：ColumnInfoMySQL  ORM 模型实例
        说明：利用 asdict() 将 dataclass 转为 dict，再展开为 ORM 构造参数
        """
        return ColumnInfoMySQL(**asdict(column_info))
