# =============================================================================
# 【实体层 / 模型层 / 映射层测试】
# 覆盖：entities（纯 dataclass）→ models（SQLAlchemy ORM）→ mappers 的双向转换，
#      以及 ORM 表结构元数据（表名、主键）是否与元数据库设计一致。
# 特点：不连接数据库，只验证映射关系与表定义。
# =============================================================================

import pytest

from server.entities.column_info import ColumnInfo
from server.entities.table_info import TableInfo
from server.models.base import Base
from server.models.column_info_mysql import ColumnInfoMySQL
from server.models.column_metric_mysql import ColumnMetricMySQL
from server.models.metric_info_mysql import MetricInfoMySQL
from server.models.table_info_mysql import TableInfoMySQL
from server.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper


def _sample_column() -> ColumnInfo:
    """构造一个典型的度量字段实体（含 JSON 型 examples/alias）"""
    return ColumnInfo(
        id="fact_order.order_amount",
        name="order_amount",
        type="decimal(10,2)",
        role="measure",
        examples=[100.5, 200],
        description="订单金额",
        alias=["销售额", "成交额"],
        table_id="fact_order",
    )


# -----------------------------------------------------------------------------
# 映射层：实体 ↔ ORM
# -----------------------------------------------------------------------------
def test_entity_to_model_keeps_all_fields():
    entity = _sample_column()
    model = ColumnInfoMapper.to_model(entity)

    assert isinstance(model, ColumnInfoMySQL)
    assert model.id == entity.id
    assert model.role == "measure"
    assert model.examples == [100.5, 200]
    assert model.alias == ["销售额", "成交额"]


def test_entity_model_roundtrip_is_lossless():
    """to_model → to_entity 往返后应与原实体完全相等（字段漏映射会在此暴露）"""
    entity = _sample_column()
    assert ColumnInfoMapper.to_entity(ColumnInfoMapper.to_model(entity)) == entity


# -----------------------------------------------------------------------------
# 模型层：表结构元数据
# -----------------------------------------------------------------------------
def test_column_info_table_definition():
    assert ColumnInfoMySQL.__tablename__ == "column_info"
    assert list(ColumnInfoMySQL.__table__.primary_key.columns.keys()) == ["id"]


def test_all_meta_tables_registered():
    """四张元数据表都应注册到同一份 metadata（建表脚本依赖它）"""
    expected = {"table_info", "column_info", "metric_info", "column_metric"}
    registered = set(Base.metadata.tables)

    missing = expected - registered
    assert not missing, f"以下表未注册到 Base.metadata：{missing}"

    for model in (TableInfoMySQL, ColumnInfoMySQL, MetricInfoMySQL, ColumnMetricMySQL):
        assert issubclass(model, Base)


# -----------------------------------------------------------------------------
# 实体层：构造与默认语义
# -----------------------------------------------------------------------------
def test_table_info_entity():
    table = TableInfo(
        id="fact_order",
        name="fact_order",
        role="fact",
        description="订单事实表",
    )
    assert table.role in {"fact", "dim"}
    assert table.id == table.name, "表实体的 id 约定等于表名"


def test_column_info_requires_core_fields():
    """核心字段缺失时应抛 TypeError（dataclass 必填项校验）"""
    with pytest.raises(TypeError):
        ColumnInfo(id="fact_order.order_amount", name="order_amount")  # type: ignore[call-arg]
