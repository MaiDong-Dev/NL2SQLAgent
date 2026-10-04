# =============================================================================
# 【评测等价判定层测试】eval/equivalence
# 覆盖：裁判之前的确定性前置校验。
# 为什么值得单测：这条逻辑专门用来补 LLM 裁判的盲区——实测 Jev 把
# 「GROUP BY region_id 返回 31 行」判成与「返回 7 行」的参考 SQL 等价（概率 0.95）。
# 判定一旦写错，要么放过真错误（假阴性），要么冤枉正确结果（假阳性），
# 且它被用作"短路裁判"的依据，出错会直接污染整轮评测。
# 特点：纯函数，零依赖、可离线跑。
# =============================================================================

from eval.equivalence import deterministic_equivalence


def _rows(count: int, columns: int = 2):
    """构造 count 行、每行 columns 列的结果集"""
    return [{f"c{i}": i for i in range(columns)} for _ in range(count)]


# -----------------------------------------------------------------------------
# 能直接判否的情形
# -----------------------------------------------------------------------------
def test_row_count_mismatch_is_incorrect():
    """核心回归：过度分组（31 行 vs 7 行）必须被判否，这正是裁判漏掉的那类"""
    verdict, reason = deterministic_equivalence(_rows(31), _rows(7))
    assert verdict == "incorrect"
    assert "行数不一致" in reason


def test_column_count_mismatch_is_incorrect():
    """行数相同但列数不同（多返回一列）同样确定不等价"""
    verdict, reason = deterministic_equivalence(_rows(5, columns=3), _rows(5, columns=2))
    assert verdict == "incorrect"
    assert "列数不一致" in reason


def test_predicted_error_is_incorrect():
    verdict, reason = deterministic_equivalence(None, _rows(3), predicted_error="表不存在")
    assert verdict == "incorrect"
    assert "表不存在" in reason


def test_none_side_is_incorrect():
    assert deterministic_equivalence(None, _rows(3))[0] == "incorrect"
    assert deterministic_equivalence(_rows(3), None)[0] == "incorrect"


def test_one_side_empty_is_incorrect():
    assert deterministic_equivalence([], _rows(3))[0] == "incorrect"
    assert deterministic_equivalence(_rows(3), [])[0] == "incorrect"


def test_both_empty_is_empty_both():
    """空集==空集不能证明等价（过滤条件写错也可能查不到），与 execution_accuracy 口径一致"""
    assert deterministic_equivalence([], [])[0] == "empty_both"


# -----------------------------------------------------------------------------
# 判不了的情形：必须交回裁判，不能越权判对
# -----------------------------------------------------------------------------
def test_same_shape_is_undecided_not_correct():
    """行数列数一致 ≠ 等价（值可能不同），必须交裁判，绝不能直接判 correct"""
    verdict, reason = deterministic_equivalence(_rows(5), _rows(5))
    assert verdict == "undecided"
    assert "裁判" in reason


def test_undecided_for_differing_values_same_shape():
    predicted = [{"region": "华东", "amount": 1}]
    reference = [{"region": "华南", "amount": 999}]
    assert deterministic_equivalence(predicted, reference)[0] == "undecided"


# -----------------------------------------------------------------------------
# 边界
# -----------------------------------------------------------------------------
def test_single_row_single_column_is_undecided():
    assert deterministic_equivalence([{"v": 1}], [{"v": 1}])[0] == "undecided"


def test_error_takes_precedence_over_empty():
    """执行失败时即便两侧都空，也要按失败报，不能混成 empty_both"""
    assert deterministic_equivalence([], [], predicted_error="超时")[0] == "incorrect"
