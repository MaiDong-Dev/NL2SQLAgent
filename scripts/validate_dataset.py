# =============================================================================
# 【评测集校验】validate_dataset
# 作用：新题入库前把能自动查出来的问题一次性列出来，避免重蹈 09 报告的覆辙
#       （曾出现"标注了系统永远召不回的字段""参考 SQL 跨年后语义已错"这类问题，
#        都是靠人工复盘才发现的）。
#
# 与 scripts/dataset_checks.py 的分工：
#   - dataset_checks：纯规则，不连库（结构/只读SQL/查重/时间歧义）
#   - 本脚本：编排 + 需要连库的检查（参考 SQL 能否执行且非空、
#             reference_columns 是否真实存在于 meta.column_info、时间是否越界）
#
# 检查项：
#   1. 用例结构完整（query / reference_sql / reference_columns）
#   2. 参考 SQL 只读，且在 dw 上可执行、结果非空
#   3. reference_columns 全部存在于 meta.column_info
#   4. 问句不与已有题目重复（含仅标点不同的实质重复）
#   5. 含时间语义但未显式写年份 → WARN，提醒出题人确认
#   6. 声明了 expected_rows 的题，与实际返回行数比对（抓分组粒度错误）
#   7. 问句中的年份是否落在数据真实范围内
#
# 运行方式（项目根目录）：
#   python -m scripts.validate_dataset                     # 默认 eval/dataset.jsonl
#   python -m scripts.validate_dataset -d eval/dataset_v2.jsonl
#   python -m scripts.validate_dataset --quiet             # 只打印问题，不逐条列 PASS
#
# 退出码：无 FAIL 返回 0，存在 FAIL 返回 1（可用于出题流程卡口）。
# =============================================================================

from __future__ import annotations

import asyncio
import sys
from argparse import ArgumentParser
from pathlib import Path

# 保证 `python scripts/validate_dataset.py` 与 `python -m scripts.validate_dataset` 都能 import
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from scripts.dataset_checks import (  # noqa: E402
    check_declared_columns,
    check_duplicates,
    check_expected_rows,
    check_readonly_sql,
    check_structure,
    check_time_ambiguity,
    load_cases,
    summarize_categories,
)
from server.agent.time_utils import extract_years  # noqa: E402
from server.clients.mysql_client_manager import (  # noqa: E402
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository  # noqa: E402

DEFAULT_DATASET = "eval/dataset.jsonl"


def _resolve_dataset(raw: str) -> Path:
    """解析评测集路径：相对路径优先按当前目录找，找不到再按项目根找"""
    path = Path(raw)
    if path.is_absolute():
        return path
    return path if path.exists() else ROOT / path


async def validate(dataset_path: Path) -> int:
    """执行全部检查，返回 FAIL 数量"""
    cases = load_cases(dataset_path)

    print("=" * 78)
    print(f"  评测集校验：{dataset_path}")
    print(f"  共 {len(cases)} 条用例")
    print("=" * 78)
    print()

    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    fail_count = 0
    warn_count = 0

    try:
        # 预取校验所需的库侧数据
        async with meta_mysql_client_manager.session_factory() as meta_session:
            rows = (await meta_session.execute(text("select id from column_info"))).fetchall()
            meta_columns = {row[0] for row in rows}

        async with dw_mysql_client_manager.session_factory() as dw_session:
            repository = DWMySQLRepository(dw_session)
            data_range = await repository.get_data_date_range()

            duplicate_issues = check_duplicates(cases)

            for index, case in enumerate(cases):
                problems: list[tuple[str, str]] = []
                problems += check_structure(case)
                problems += check_readonly_sql(case)

                # 结构有问题就不硬跑 SQL，避免抛一堆无关异常
                if not any(level == "FAIL" for level, _ in problems):
                    problems += check_declared_columns(case, meta_columns)

                    try:
                        result_rows = await repository.execute_sql(case["reference_sql"])
                        if not result_rows:
                            problems.append(("FAIL", "参考 SQL 执行成功但结果为空（可能是废题）"))
                        else:
                            problems += check_expected_rows(case, len(result_rows))
                    except Exception as e:
                        problems.append(("FAIL", f"参考 SQL 执行失败: {type(e).__name__}: {e}"))

                    problems += check_time_ambiguity(case)

                    # 年份越界：问句写的年份不在数据范围内
                    if data_range["start"] and data_range["end"]:
                        start_year = int(data_range["start"][:4])
                        end_year = int(data_range["end"][:4])
                        for year in extract_years(case.get("query", "")):
                            if not (start_year <= year <= end_year):
                                problems.append(
                                    ("FAIL", f"问句中的年份 {year} 超出数据范围 "
                                             f"{data_range['start']} ~ {data_range['end']}，会返回空结果"))

                problems += duplicate_issues.get(index, [])

                if problems:
                    for level, message in problems:
                        if level == "FAIL":
                            fail_count += 1
                        else:
                            warn_count += 1
                        print(f"[{level}] 第 {index + 1} 条：{case.get('query', '（无问句）')}")
                        print(f"        {message}")
                    print()
    finally:
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()

    # 覆盖度报告
    print("-" * 78)
    print("【题型覆盖度】")
    for category, count in sorted(summarize_categories(cases).items()):
        print(f"  {category:<24} {count:>3} 条")

    print("-" * 78)
    if fail_count == 0:
        print(f"结果：无 FAIL，{warn_count} 条 WARN，共 {len(cases)} 条用例")
    else:
        print(f"结果：{fail_count} 条 FAIL，{warn_count} 条 WARN，共 {len(cases)} 条用例")
    print("=" * 78)

    return fail_count


async def main():
    parser = ArgumentParser(description="校验评测集（结构、参考 SQL、字段标注、歧义）")
    parser.add_argument("-d", "--dataset", default=DEFAULT_DATASET,
                        help=f"评测集 jsonl 路径（默认 {DEFAULT_DATASET}）")
    args = parser.parse_args()

    fail_count = await validate(_resolve_dataset(args.dataset))
    sys.exit(1 if fail_count else 0)


if __name__ == "__main__":
    asyncio.run(main())
