# =============================================================================
# 【模型层】ORM 基类（Base）
# 作用：定义 SQLAlchemy ORM 的声明式基类（DeclarativeBase），是所有数据库模型
#       类的公共父类。
#
# 组合关系（见 docs/architecture-02-class-diagram）：
#   Base <|-- ColumnInfoMySQL
#   Base <|-- TableInfoMySQL
#   Base <|-- MetricInfoMySQL
#   Base <|-- ColumnMetricMySQL
#
# 说明：
#   - 所有 models/* 下的模型类均继承自 Base，从而共享 SQLAlchemy 的 ORM 能力
#     （表映射、字段声明、会话管理、元数据注册等）
#   - 模型层（models/）与实体层（entities/）的区别：
#     * entities/* 是纯 Python dataclass，作为业务数据在内存中流转（与存储解耦）
#     * models/*   是 ORM 模型，直接映射 Meta MySQL 数据库表结构（与存储绑定）
#     * 二者通过 repositories/mysql/meta/mappers/* 中的 Mapper 相互转换
# =============================================================================

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy ORM 声明式基类

    所有数据库模型类继承此类，自动获得：
    - 表结构定义能力（__tablename__、mapped_column）
    - 元数据注册（用于 create_all 建表）
    - ORM 会话管理（增删改查）
    """
    pass
