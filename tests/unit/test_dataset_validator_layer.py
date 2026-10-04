# =============================================================================
# 【评测集校验层测试】scripts/dataset_checks
# 覆盖：出题规则里可以纯静态判定的部分（结构、只读 SQL、查重、时间歧义、期望行数）。
# 为什么值得单测：09 报告的复盘结论是「评测题必须答案唯一」——曾出现
# 「参考 SQL 跨年后语义已错」「标注了系统永远召不回的字段」这类问题，
# 都是靠事后人工复盘才发现。把规则固化成测试，出题时才能自动挡住。
# 特点：只依赖 server.agent.time_utils 的正则，零中间件、可离线跑。
# =============================================================================

import pytest

from scripts.dataset_checks import (
    check_declared_columns,
    check_duplicates,
    check_expected_rows,
    check_readonly_sql,
    check_structure,
    check_time_ambiguity,
    normalize_query,
    summarize_categories,
)


def _case(**overrides):
    """构造一条合法用例，再按需覆盖字段"""
    base = {
        "query": "各大区的销售额分别是多少",
        "reference_sql": "SELECT r.region_name, SUM(f.order_amount) FROM fact_order f "
                         "JOIN dim_region r ON f.region_id = r.region_id GROUP BY r.region_name",
        "reference_columns": ["fact_order.order_amount", "dim_region.region_name"],
    }
    base.update(overrides)
    return base


# -----------------------------------------------------------------------------
# 结构
# -----------------------------------------------------------------------------
def test_valid_case_has_no_issues():
    assert check_structure(_case()) == []


@pytest.mark.parametrize("missing_field", ["query", "reference_sql", "reference_columns"])
def test_missing_required_field_is_fail(missing_field):
    case = _case()
    del case[missing_field]
    levels = [level for level, _ in check_structure(case)]
    assert "FAIL" in levels


def test_empty_query_is_fail():
    assert check_structure(_case(query="   "))[0][0] == "FAIL"


def test_reference_columns_must_be_table_dot_column():
    issues = check_structure(_case(reference_columns=["region_name", "province"]))
    assert any("表.字段" in message for _, message in issues)


# -----------------------------------------------------------------------------
# 只读约束
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("sql", ["DELETE FROM fact_order", "UPDATE fact_order SET a = 1",
                                 "DROP TABLE fact_order"])
def test_write_sql_is_rejected(sql):
    levels = [level for level, _ in check_readonly_sql(_case(reference_sql=sql))]
    assert "FAIL" in levels


def test_select_and_cte_are_allowed():
    assert check_readonly_sql(_case(reference_sql="SELECT 1 FROM fact_order")) == []
    assert check_readonly_sql(_case(reference_sql="WITH t AS (SELECT 1) SELECT * FROM t")) == []


# -----------------------------------------------------------------------------
# 查重
# -----------------------------------------------------------------------------
def test_normalize_query_strips_punctuation_and_case():
    assert normalize_query("各大区的销售总额？") == normalize_query("各大区的销售总额")


def test_exact_duplicate_is_flagged():
    cases = [_case(query="总销售额是多少"), _case(query="总销售额是多少")]
    assert 1 in check_duplicates(cases)


def test_duplicate_differing_only_by_punctuation_is_flagged():
    cases = [_case(query="总销售额是多少"), _case(query="总销售额是多少？")]
    assert 1 in check_duplicates(cases)


def test_distinct_queries_are_not_flagged():
    cases = [_case(query="总销售额是多少"), _case(query="一共有多少笔订单")]
    assert check_duplicates(cases) == {}


# -----------------------------------------------------------------------------
# 时间歧义（本次不稳定的主要来源）
# -----------------------------------------------------------------------------
def test_time_query_without_year_is_warned():
    issues = check_time_ambiguity(_case(query="1月份的订单量是多少"))
    assert issues and issues[0][0] == "WARN"


def test_time_query_with_year_is_not_warned():
    assert check_time_ambiguity(_case(query="2025年1月份的订单量是多少")) == []


def test_non_time_query_is_not_warned():
    assert check_time_ambiguity(_case(query="各大区的销售额分别是多少")) == []


def test_threshold_number_is_not_mistaken_for_year():
    """「超过2000」里的 2000 是阈值不是年份，不能因此判定"已指定年份\""""
    assert check_time_ambiguity(_case(query="订单量超过2000的月份分别是哪几个")) != []


# -----------------------------------------------------------------------------
# 期望行数：抓分组粒度错误
# -----------------------------------------------------------------------------
def test_expected_rows_mismatch_is_fail():
    issues = check_expected_rows(_case(expected_rows=7), actual_rows=31)
    assert issues and issues[0][0] == "FAIL"


def test_expected_rows_match_passes():
    assert check_expected_rows(_case(expected_rows=7), actual_rows=7) == []


def test_expected_rows_absent_is_skipped():
    assert check_expected_rows(_case(), actual_rows=31) == []


# -----------------------------------------------------------------------------
# 字段标注必须真实存在于 meta
# -----------------------------------------------------------------------------
def test_columns_absent_from_meta_are_fail():
    issues = check_declared_columns(_case(), meta_columns={"fact_order.order_amount"})
    assert any("dim_region.region_name" in message for _, message in issues)


def test_columns_present_in_meta_pass():
    meta = {"fact_order.order_amount", "dim_region.region_name"}
    assert check_declared_columns(_case(), meta_columns=meta) == []


# -----------------------------------------------------------------------------
# 覆盖度统计
# -----------------------------------------------------------------------------
def test_summarize_categories_counts_and_defaults():
    cases = [_case(category="A"), _case(category="A"), _case()]
    assert summarize_categories(cases) == {"A": 2, "未分类": 1}
