# =============================================================================
# 【Agent 层测试】server/agent/time_utils
# 覆盖：时间语义识别与时间维表判定。
# 为什么值得单测：这两个函数是「确定性规则」对向量召回的补偿——时间维表字段
# （year/quarter/month）语义弱、几乎召不回来，缺了它们 SQL 会退化成对日期键做
# 算术/格式化，导致口径错误（实测出现过 date_id DIV 100）。
# 特点：纯正则与集合运算，零依赖、毫秒级。
# =============================================================================

import pytest

from server.agent.time_utils import (
    extract_years,
    has_explicit_year,
    has_time_semantic,
    is_time_dimension_table,
)

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


# -----------------------------------------------------------------------------
# 显式年份识别（出题校验复用：含时间语义但没写年份 = 歧义题）
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query,expected",
    [
        ("2025年的销售额", [2025]),
        ("2024年和2025年的订单量分别是多少", [2024, 2025]),
        ("2024 年 1 月各大区的销量", [2024]),          # 年份与"年"之间有空格
        ("1月份的订单量是多少", []),                    # 没有年份
        ("订单金额超过5000元", []),                     # 五千不是年份
    ],
)
def test_extract_years(query, expected):
    assert extract_years(query) == expected


def test_threshold_number_is_not_treated_as_year():
    """回归护栏：四位数阈值不能被当成年份

    曾经用 `(?:19|20)\\d{2}` 匹配年份，导致「2025年订单量超过2000的月份」
    里的阈值 2000 被误判为年份，进而在评测集校验里报出"年份越界"的假 FAIL。
    现在要求四位数后必须跟"年"。
    """
    assert extract_years("2025年订单量超过2000的月份") == [2025]
    assert extract_years("订单量超过2000的月份") == []
    assert has_explicit_year("订单量超过2000的月份") is False
    assert has_explicit_year("2025年订单量超过2000的月份") is True


def test_has_explicit_year_distinguishes_ambiguous_time_queries():
    """这条判定直接决定出题校验会不会报「歧义题」WARN"""
    assert has_explicit_year("2025年3月每天的订单量分别是多少") is True
    assert has_explicit_year("1月份的订单量是多少") is False
    assert has_explicit_year("3月份销量最高的商品品类是哪个") is False


def test_extract_years_handles_none():
    """与 has_time_semantic 一致：上游可能传 None，不能抛异常"""
    assert extract_years(None) == []  # type: ignore[arg-type]
    assert has_explicit_year(None) is False  # type: ignore[arg-type]
