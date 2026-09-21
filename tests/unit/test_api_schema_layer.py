# =============================================================================
# 【接口层测试】server/api/schemas
# 覆盖：请求模型 QuerySchema 的字段校验行为（必填、类型）。
# 特点：只测 Pydantic 校验，不启动 FastAPI、不连中间件。
# =============================================================================

import pytest
from pydantic import ValidationError

from server.api.schemas.query_schema import QuerySchema


def test_query_schema_accepts_natural_language():
    schema = QuerySchema(query="统计2025年每个月的订单量")
    assert schema.query == "统计2025年每个月的订单量"


def test_query_is_required():
    """query 必填：不传应校验失败（否则路由会拿到空问句去召回）"""
    with pytest.raises(ValidationError):
        QuerySchema()  # type: ignore[call-arg]


def test_query_must_be_string():
    with pytest.raises(ValidationError):
        QuerySchema(query=123)  # type: ignore[arg-type]


def test_query_accepts_empty_string_boundary():
    """空字符串属于业务层问题，schema 层不做长度约束（保持与线上行为一致）"""
    assert QuerySchema(query="").query == ""
