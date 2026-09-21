# =============================================================================
# 【评测层测试】eval/run_ragas_eval.py 中的自定义指标
# 覆盖：execution_accuracy（执行准确性）的四类判定与数值归一化 _canon。
# 为什么值得单测：它是本次评测结论的「金标口径」——比较的是生成 SQL 与标准 SQL
#   的真实执行结果集；判定规则一旦写错（如把空集当通过），整份评测报告的结论都会失真。
# 说明：run_ragas_eval.py 依赖 ragas，未安装时整体跳过而不是失败。
# =============================================================================

from decimal import Decimal

import pytest

pytest.importorskip("ragas", reason="未安装 ragas，跳过评测层指标测试")


@pytest.fixture(scope="module")
def metrics():
    """惰性导入被测模块：其模块级代码会加载配置，失败时跳过而非报错"""
    try:
        from eval.run_ragas_eval import _canon, execution_accuracy
    except Exception as exc:  # pragma: no cover - 环境缺依赖时的兜底
        pytest.skip(f"无法导入 eval.run_ragas_eval：{exc}")
    return _canon, execution_accuracy


def _rows(*rows):
    return [dict(row) for row in rows]


def test_identical_results_are_correct(metrics):
    _, execution_accuracy = metrics
    rows = _rows({"region_name": "华东", "total": 100}, {"region_name": "华南", "total": 200})
    result = execution_accuracy(predicted_rows=rows, reference_rows=list(reversed(rows)))
    assert result.value == "correct"


def test_row_order_is_ignored(metrics):
    """结果集比较忽略行序：SQL 没写 ORDER BY 时行序不稳定，不应据此判错"""
    _, execution_accuracy = metrics
    predicted = _rows({"c": 1}, {"c": 2}, {"c": 3})
    reference = _rows({"c": 3}, {"c": 1}, {"c": 2})
    assert execution_accuracy(predicted_rows=predicted, reference_rows=reference).value == "correct"


def test_column_alias_difference_is_still_correct(metrics):
    """列名不同但数据一致 → 判通过（列别名不应判错）"""
    _, execution_accuracy = metrics
    predicted = _rows({"total_amount": 100})
    reference = _rows({"销售额": 100})
    assert execution_accuracy(predicted_rows=predicted, reference_rows=reference).value == "correct"


def test_decimal_and_int_are_treated_as_equal(metrics):
    """MySQL 聚合返回 Decimal、表达式运算返回 int，同为 9 不能判为不一致"""
    _, execution_accuracy = metrics
    predicted = _rows({"cnt": Decimal("9")})
    reference = _rows({"cnt": 9})
    assert execution_accuracy(predicted_rows=predicted, reference_rows=reference).value == "correct"


def test_different_values_are_incorrect(metrics):
    _, execution_accuracy = metrics
    predicted = _rows({"cnt": 10})
    reference = _rows({"cnt": 9})
    assert execution_accuracy(predicted_rows=predicted, reference_rows=reference).value == "incorrect"


def test_both_empty_is_not_counted_as_pass(metrics):
    """两边都 0 行 → empty_both（空集≠等价：过滤条件写错也会查不到数据）"""
    _, execution_accuracy = metrics
    assert execution_accuracy(predicted_rows=[], reference_rows=[]).value == "empty_both"


def test_sql_error_is_incorrect(metrics):
    _, execution_accuracy = metrics
    result = execution_accuracy(predicted_rows=None, reference_rows=[{"c": 1}], predicted_error="语法错误")
    assert result.value == "incorrect"


def test_canon_normalizes_numeric_types(metrics):
    _canon, _ = metrics
    assert _canon(Decimal("9")) == _canon(9) == 9.0
    assert _canon(True) is True, "布尔值不应被当成数值处理"
    assert _canon("华东") == "华东"
