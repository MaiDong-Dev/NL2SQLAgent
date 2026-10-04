# =============================================================================
# 【评测集校验·纯逻辑层】dataset_checks
# 作用：评测集（dataset.jsonl）的静态检查规则，**全部为纯函数，不依赖任何中间件**。
#       这样规则本身可以离线单测（见 tests/unit/test_dataset_validator_layer.py），
#       需要连库的部分（参考 SQL 能不能跑、字段在不在 meta 里）放在 validate_dataset.py。
#
# 为什么要把规则抽出来：
#   09 报告的复盘结论是「评测题必须答案唯一」——凡是参考 SQL 里的格式化、
#   输出列数量、行式还是列式，都必须在问句里显式约束，否则测的是"猜标准答案"。
#   这类问题全靠人工盯容易漏，做成规则才能每次出题都过一遍。
#
# 检查分级：
#   FAIL  必须修，否则这条题不可用（缺字段、参考 SQL 可写、回不了库的字段标注）
#   WARN  需要出题人确认，不一定是错的（最典型的是"含时间语义但没写年份"）
# =============================================================================

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from server.agent.time_utils import has_explicit_year, has_time_semantic

# 每条用例必须具备的字段
REQUIRED_FIELDS = ("query", "reference_sql", "reference_columns")

# 参考 SQL 必须只读：以 SELECT 或 WITH 开头，且不含写操作关键字
_READONLY_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke)\b",
    re.IGNORECASE,
)

# 归一化问句查重时去掉的字符：空白与中英文常见标点
_PUNCTUATION = re.compile(r"[\s，。？！、,\.\?!：:；;（）()《》<>“”\"'‘’·\-—]+")


def load_cases(path: Path) -> list[dict]:
    """逐行读取 jsonl 评测集，跳过空行"""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def normalize_query(query: str) -> str:
    """归一化问句用于查重：去掉空白与标点，统一小写

    不能只用原文比对——「各大区的销售总额」与「各大区的销售总额？」是同一道题。
    """
    return _PUNCTUATION.sub("", query or "").lower()


def check_structure(case: dict) -> list[tuple[str, str]]:
    """检查必需字段是否存在且类型正确"""
    issues: list[tuple[str, str]] = []

    for field in REQUIRED_FIELDS:
        if field not in case:
            issues.append(("FAIL", f"缺少必需字段 {field}"))

    query = case.get("query")
    if not isinstance(query, str) or not query.strip():
        issues.append(("FAIL", "query 必须是非空字符串"))

    sql = case.get("reference_sql")
    if not isinstance(sql, str) or not sql.strip():
        issues.append(("FAIL", "reference_sql 必须是非空字符串"))

    columns = case.get("reference_columns")
    if not isinstance(columns, list) or not columns:
        issues.append(("FAIL", "reference_columns 必须是非空数组"))
    elif not all(isinstance(c, str) and "." in c for c in columns):
        issues.append(("FAIL", "reference_columns 每项都必须是「表.字段」形式"))

    return issues


def check_readonly_sql(case: dict) -> list[tuple[str, str]]:
    """参考 SQL 必须是一条只读查询"""
    sql = case.get("reference_sql", "") or ""
    issues: list[tuple[str, str]] = []

    if not _READONLY_PREFIX.match(sql):
        issues.append(("FAIL", "参考 SQL 必须以 SELECT 或 WITH 开头"))
    if _WRITE_KEYWORDS.search(sql):
        issues.append(("FAIL", "参考 SQL 含有写操作关键字（insert/update/delete/drop…）"))

    return issues


def check_time_ambiguity(case: dict) -> list[tuple[str, str]]:
    """含时间语义但未显式写出年份 —— 答案取决于模型如何推断年份

    实测这类题是不稳定的主要来源：问"1月份的订单量"，模型可能按系统当前年份
    补成 year=2026（数据只到 2025），也可能不加年份过滤，两种结果完全不同。
    所以这类题要么在问句里补上年份，要么显式声明为"考年份推断"的专项题。
    """
    query = case.get("query", "") or ""
    if has_time_semantic(query) and not has_explicit_year(query):
        return [("WARN", "含时间语义但未显式写出年份，答案依赖模型推断，请确认是否有意为之")]
    return []


def check_declared_columns(case: dict, meta_columns: set[str]) -> list[tuple[str, str]]:
    """标注的 reference_columns 必须都真实存在于 meta.column_info

    否则等于标注了系统永远召不回的字段，会凭空冤枉系统。
    """
    missing = [c for c in case.get("reference_columns", []) or [] if c not in meta_columns]
    return [("FAIL", f"reference_columns 中的 {c} 不在 meta.column_info 里") for c in missing]


def check_expected_rows(case: dict, actual_rows: int) -> list[tuple[str, str]]:
    """用例若声明了 expected_rows，则与参考 SQL 的实际行数比对

    这是抓"过度分组"这类粒度错误最直接的手段：问"各大区"就该是 7 行，
    参考 SQL 若写成按省份分组会返回 31 行，这里立刻报出来。
    """
    expected = case.get("expected_rows")
    if expected is None:
        return []
    if expected != actual_rows:
        return [("FAIL", f"声明期望 {expected} 行，参考 SQL 实际返回 {actual_rows} 行")]
    return []


def check_duplicates(cases: list[dict]) -> dict[int, list[tuple[str, str]]]:
    """查重：问句完全重复，或归一化（去标点/空白）后重复

    返回 {用例下标: 问题列表}，只给出重复组里除第一个之外的位置。
    """
    issues: dict[int, list[tuple[str, str]]] = {}
    exact: dict[str, int] = {}
    normalized: dict[str, int] = {}

    for index, case in enumerate(cases):
        query = case.get("query", "") or ""

        if query in exact:
            issues.setdefault(index, []).append(
                ("FAIL", f"问句与第 {exact[query] + 1} 条完全重复"))
        else:
            exact[query] = index

        key = normalize_query(query)
        if key and key in normalized:
            issues.setdefault(index, []).append(
                ("FAIL", f"问句与第 {normalized[key] + 1} 条实质重复（仅标点/空白不同）"))
        elif key:
            normalized[key] = index

    return issues


def summarize_categories(cases: list[dict]) -> dict[str, int]:
    """按用例的 category 字段统计题量，用于检查能力覆盖是否有缺口"""
    counter: Counter = Counter()
    for case in cases:
        counter[case.get("category") or "未分类"] += 1
    return dict(counter)


def count_by_level(issues: list[tuple[str, str]]) -> tuple[int, int]:
    """统计 (FAIL 数, WARN 数)"""
    fails = sum(1 for level, _ in issues if level == "FAIL")
    warns = sum(1 for level, _ in issues if level == "WARN")
    return fails, warns
