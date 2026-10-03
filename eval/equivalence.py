# =============================================================================
# 【评测·纯逻辑】SQL 等价的确定性判定
# 作用：在不调用任何 LLM 的前提下，判定"生成 SQL 的结果集"与"参考 SQL 的结果集"
#       是否**必然不等价**，以及是否可以直接下结论。
#
# 为什么需要它：LLM 裁判对"分组粒度错误"有盲区。实测 Jev 把一条
#   GROUP BY region_id（返回 31 行）判成与参考 SQL（返回 7 行）等价，概率 0.95——
#   它看到两张表的列名和过滤条件都对，没意识到分组粒度不同会改变结果集。
#
# 原理：两个行集合若相同，行数必相等、每行的列数也必相等。
#   因此"行数不一致 / 列数不一致"是"不等价"的**充分条件**，不需要 LLM 就能判定。
#   但反过来不成立——行数相同不代表等价（值可能不同），那种情况仍交给裁判。
#
# 本模块刻意不 import 任何重依赖（ragas / openai / app_config / 数据库），
# 这样判定逻辑可以离线单测（见 tests/unit/test_eval_equivalence_layer.py）。
# =============================================================================

from __future__ import annotations


def deterministic_equivalence(predicted_rows, reference_rows, predicted_error=None):
    """裁判之前的确定性校验

    返回 (verdict, reason)：
      verdict = "incorrect"   已可确定不等价，无需调裁判
      verdict = "empty_both"  两边都空，无法证明等价（与 execution_accuracy 口径一致）
      verdict = "undecided"   确定性方法判不了，交给裁判做语义判断
    """
    if predicted_error is not None:
        return "incorrect", f"生成 SQL 执行失败: {predicted_error}"

    if predicted_rows is None or reference_rows is None:
        return "incorrect", "执行结果为空，无法比较"

    if not predicted_rows and not reference_rows:
        return "empty_both", "两边均返回 0 行，无法证明等价"

    if not predicted_rows or not reference_rows:
        return ("incorrect",
                f"一侧为空：预期 {len(reference_rows)} 行 / 实际 {len(predicted_rows)} 行")

    if len(predicted_rows) != len(reference_rows):
        return ("incorrect",
                f"行数不一致：预期 {len(reference_rows)} 行 / 实际 {len(predicted_rows)} 行"
                f"（疑似分组粒度错误）")

    predicted_columns = len(predicted_rows[0])
    reference_columns = len(reference_rows[0])
    if predicted_columns != reference_columns:
        return ("incorrect",
                f"列数不一致：预期 {reference_columns} 列 / 实际 {predicted_columns} 列")

    return "undecided", "行数与列数一致，值层面的等价性交由裁判判断"
