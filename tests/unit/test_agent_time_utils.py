# =============================================================================
# 【Agent 层测试】server/agent/time_utils
# 覆盖：时间语义识别与时间维表判定。
# 为什么值得单测：这两个函数是「确定性规则」对向量召回的补偿——时间维表字段
# （year/quarter/month）语义弱、几乎召不回来，缺了它们 SQL 会退化成对日期键做
# 算术/格式化，导致口径错误（实测出现过 date_id DIV 100）。
# 特点：纯正则与集合运算，零依赖、毫秒级。
# =============================================================================

import pytest

from server.agent.time_utils import has_time_semantic, is_time_dimension_table

TIME_QUERIES = [
    "2025年每个月的订单量是多少",
    "最近30天的销售额",
    "今年Q1各地区的销量",
    "近3天新增客户数",
    "上个月各省份订单金额",
    "统计monthly revenue",
]

NON_TIME_QUERIES = [
    "各地区的销售总额",
    "客户会员等级分布",
    "销售额最高的商品",
    "一共有多少个客户",
    "",
]


@pytest.mark.parametrize("query", TIME_QUERIES)
def test_time_query_is_detected(query):
    assert has_time_semantic(query), f"应识别为时间语义：{query}"


@pytest.mark.parametrize("query", NON_TIME_QUERIES)
def test_non_time_query_is_not_detected(query):
    assert not has_time_semantic(query), f"不应识别为时间语义：{query}"


def test_age_is_not_treated_as_year():
    """「年龄」含「年」字，正则用 (?<!龄) 排除，避免误补时间维表"""
    assert not has_time_semantic("各年龄段客户数量")
    assert not has_time_semantic("客户平均年龄")


def test_has_time_semantic_handles_none():
    """节点可能传入 None（上游未产出），不能抛异常"""
    assert has_time_semantic(None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "columns,expected",
    [
        (["year", "month"], True),
        (["year", "quarter", "month"], True),
        (["year", "quarter"], True),
        (["year", "region_name"], False),   # 只命中 1 个时间粒度字段
        (["region_name", "province"], False),
        ([], False),
    ],
)
def test_time_dimension_table_detection(columns, expected):
    assert is_time_dimension_table(columns) is expected
