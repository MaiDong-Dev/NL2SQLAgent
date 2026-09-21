# =============================================================================
# 【评测脚本】用 Jev（typesafe/jev-latest）对已有评测结果重做 SQL 等价判定
#
# 与 eval/run_ragas_eval.py 的关系：
#   run_ragas_eval.py 跑系统 + 判定一步到位（--judge jev 默认走 Jev 裁判）；
#   本脚本**不跑系统**，只读上一轮的 results_*.csv，对已有的
#   query / reference_sql / predicted_sql 重新做一次等价判定。
#   用途：切换裁判口径、调阈值、做对照实验时，省掉 6~7 次/条的 LLM 调用
#   （一轮 63 条全量约 25 分钟，本脚本只需十几秒）。
#
# 判定逻辑共用 eval/jev_judge.py（那里有接口细节与"为什么用总体概率而非原子合成"的说明）。
#
# 三种对照基准：
#   ragas 的 sql_equivalence（LLM 裁判，非金标，看一致率）
#   execution_accuracy（真跑库比对结果集，最接近金标，算 P/R/F1）
#   jev_composite（原子合成的对照口径，实测不如总体判断，仅作参考）
#
# 用法（项目根目录）：
#   set OPENROUTER_API_KEY=...                     # 必填
#   python -m eval.jev_equivalence_judge                     # 默认取最新 results_*.csv
#   python -m eval.jev_equivalence_judge --results eval/results_20260919_171653.csv
#   python -m eval.jev_equivalence_judge --limit 10          # 冒烟
#   python -m eval.jev_equivalence_judge --threshold 0.6     # Noul 判定阈值
#   python -m eval.jev_equivalence_judge --with-ddl          # 把 DDL 也放进 state（需连 DW）
#   python -m eval.jev_equivalence_judge --dry-run           # 不调 API，用桩验证流程
#
# 产出：eval/jev_judge_<时间戳>.csv（逐条明细）+ 控制台汇总
# =============================================================================

import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

from eval.jev_judge import (
    ATOMIC_KEYS,
    DEFAULT_THRESHOLD,
    REQUEST_TIMEOUT,
    build_state,
    judge_equivalence,
)

EVAL_DIR = Path(__file__).parent
OUTPUT_DIR = EVAL_DIR

# 并发上限：63 条量级不打满限速，留余量
MAX_CONCURRENCY = 5


# =============================================================================
# 单条判定
# =============================================================================
async def judge_one(client: httpx.AsyncClient, row, ddl: str | None, sem: asyncio.Semaphore,
                    threshold: float) -> dict:
    started = time.perf_counter()
    async with sem:
        result = await judge_equivalence(
            client,
            query=row["query"],
            reference_sql=row["reference_sql"],
            predicted_sql=row["predicted_sql"],
            ddl=ddl,
            threshold=threshold,
        )
    elapsed = time.perf_counter() - started

    atoms = result["atoms"]
    # composite 口径：6 个原子全部为"是"才等价。实测不如总体判断，保留用于对照
    composite = all((atoms.get(key) is not None and atoms.get(key) >= threshold) for key in ATOMIC_KEYS)

    return {
        "jev_overall": result["probability"],
        "jev_overall_verdict": bool(result["equivalence"]),
        "jev_composite": composite,
        "jev_prob_tables": atoms.get("same_tables"),
        "jev_prob_agg": atoms.get("same_agg"),
        "jev_prob_filter": atoms.get("same_filter"),
        "jev_prob_group": atoms.get("same_group"),
        "jev_prob_limit": atoms.get("same_limit"),
        "jev_prob_columns": atoms.get("same_columns"),
        "jev_failed_atoms": "|".join(result["failed_atoms"]),
        "jev_reason": result["reason"],
        "jev_seconds": round(elapsed, 3),
        "jev_input_tokens": result["input_tokens"],
        "jev_cost": result["cost"],
        "jev_model": result["model"],
    }


def judge_dry_run(row, threshold: float) -> dict:
    """不调 API 的桩：用字符串相等做确定性伪概率，仅验证流程与统计链路"""
    pred, ref = str(row["predicted_sql"]), str(row["reference_sql"])
    norm = lambda s: "".join(s.split()).lower()
    same = 0.9 if norm(pred) == norm(ref) else 0.2
    probs = {key: same for key in ["same_result", *ATOMIC_KEYS]}
    composite = all(v >= threshold for v in (probs[k] for k in ATOMIC_KEYS))
    return {
        "jev_overall": probs["same_result"],
        "jev_overall_verdict": probs["same_result"] >= threshold,
        "jev_composite": composite,
        "jev_prob_tables": probs["same_tables"],
        "jev_prob_agg": probs["same_agg"],
        "jev_prob_filter": probs["same_filter"],
        "jev_prob_group": probs["same_group"],
        "jev_prob_limit": probs["same_limit"],
        "jev_prob_columns": probs["same_columns"],
        "jev_failed_atoms": "",
        "jev_reason": "dry-run",
        "jev_seconds": 0.0,
        "jev_input_tokens": 0,
        "jev_cost": 0.0,
        "jev_model": "dry-run",
    }


# =============================================================================
# 与既有基准对照
# =============================================================================
def score_vs_gold(df: pd.DataFrame, pred_col: str, gold_col: str) -> dict:
    """以 execution_accuracy==correct 为金标算 P/R/F1/accuracy"""
    tp = int(((df[pred_col]) & (df[gold_col])).sum())
    fp = int(((df[pred_col]) & (~df[gold_col])).sum())
    fn = int(((~df[pred_col]) & (df[gold_col])).sum())
    tn = int(((~df[pred_col]) & (~df[gold_col])).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "accuracy": (tp + tn) / len(df),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def report(df: pd.DataFrame, threshold: float, elapsed_total: float):
    gold = df["exec_correct"]
    print("\n" + "=" * 68)
    print(f"用例数: {len(df)}   Noul 阈值: {threshold}   总耗时: {elapsed_total:.1f}s "
          f"（单条均值 {df['jev_seconds'].mean():.2f}s）")

    if df["jev_input_tokens"].sum():
        print(f"Jev 用量: {int(df['jev_input_tokens'].sum())} input tokens, "
              f"总花费 ${df['jev_cost'].sum():.6f}（均值 ${df['jev_cost'].mean():.6f}/条）")

    # 1) 与 ragas（LLM 裁判）的一致性：两者都不是金标，看分歧率
    if df["ragas_eq"].notna().any():
        both = df[df["ragas_eq"].notna()]
        for col in ["jev_overall_verdict", "jev_composite"]:
            agree = (both[col] == (both["sql_equivalence"] >= 0.5)).mean()
            print(f"与 ragas 裁判一致率 {col:22s}: {agree:.2%}")

    # 2) 以执行结果为准的判定质量（execution_accuracy 最接近金标）
    print("\n以执行结果(execution_accuracy)为金标：")
    for col, name in [("jev_overall_verdict", "Jev 总体判断"),
                      ("jev_composite", "Jev 原子合成"),
                      ("ragas_eq_binary", "ragas 裁判(对照)")]:
        if col == "ragas_eq_binary" and df["ragas_eq"].isna().all():
            continue
        s = score_vs_gold(df, col, gold_col="exec_correct")
        print(f"  {name:16s} acc={s['accuracy']:.3f} P={s['precision']:.3f} "
              f"R={s['recall']:.3f} F1={s['f1']:.3f} (TP={s['tp']} FP={s['fp']} FN={s['fn']} TN={s['tn']})")

    # 3) 概率分布体检：若概率都糊在 0.5 附近，说明调阈值救不了
    valid = df["jev_overall"].dropna()
    if len(valid):
        print(f"\n总体 Noul 概率分布: min={valid.min():.2f} 中位数={valid.median():.2f} "
              f"max={valid.max():.2f}；落在 [0.4,0.6] 的纠结样本 {int(((valid >= 0.4) & (valid <= 0.6)).sum())}/{len(valid)} 条")

    # 4) 分歧明细：Jev 与执行结果不一致的用例，最值得人工复核
    diff = df[df["jev_overall_verdict"] != gold]
    print(f"\nJev 总体判断 与 执行结果 不一致: {len(diff)} 条")
    for _, r in diff.iterrows():
        print(f"  - {r['query']}\n      失败原子={r['jev_failed_atoms'] or '无'} "
              f"overall={r['jev_overall']:.2f} ragas={r['ragas_eq']} "
              f"exec={'correct' if r['exec_correct'] else 'incorrect'}")
    print("=" * 68)


# =============================================================================
async def main():
    parser = argparse.ArgumentParser(description="用 Jev 对已有评测结果重做 SQL 等价判定并与 ragas / 执行结果对照")
    parser.add_argument("-r", "--results", default=None, help="评测结果 CSV（默认取 eval 下最新 results_*.csv）")
    parser.add_argument("-n", "--limit", type=int, default=None, help="只判前 N 条（冒烟）")
    parser.add_argument("-t", "--threshold", type=float, default=DEFAULT_THRESHOLD, help="Noul 判定阈值")
    parser.add_argument("--with-ddl", action="store_true", help="从 DW 拉取 DDL 一并放入 state")
    parser.add_argument("--dry-run", action="store_true", help="不调 API，跑通流程与统计")
    args = parser.parse_args()

    results_path = Path(args.results) if args.results else max(
        EVAL_DIR.glob("results_*.csv"), key=lambda p: p.stat().st_mtime)
    df = pd.read_csv(results_path)
    df = df[df["predicted_sql"].notna() & (df["predicted_sql"].astype(str).str.strip() != "")]
    if args.limit:
        df = df.head(args.limit)
    print(f"裁判输入: {results_path.name}（{len(df)} 条）")

    ddl = None
    if args.with_ddl:
        from eval.run_ragas_eval import load_schema_ddl
        from server.clients.mysql_client_manager import dw_mysql_client_manager
        dw_mysql_client_manager.init()
        async with dw_mysql_client_manager.session_factory() as session:
            ddl = await load_schema_ddl(session)
        await dw_mysql_client_manager.close()
        print(f"已载入 DDL: {len(ddl)} 字符")

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    started = time.perf_counter()
    if args.dry_run:
        print("dry-run：不调用 Jev API")
        judged = [judge_dry_run(row, args.threshold) for _, row in df.iterrows()]
    else:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            judged = list(await asyncio.gather(*[
                judge_one(client, row, ddl, sem, args.threshold) for _, row in df.iterrows()
            ]))
    elapsed_total = time.perf_counter() - started

    df = df.reset_index(drop=True).join(pd.DataFrame(judged))
    df["ragas_eq"] = pd.to_numeric(df["sql_equivalence"], errors="coerce")
    df["ragas_eq_binary"] = df["ragas_eq"] >= 0.5
    df["exec_correct"] = df["execution_accuracy"] == "correct"

    report(df, args.threshold, elapsed_total)

    out = OUTPUT_DIR / f"jev_judge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"明细已写入: {out}")


if __name__ == "__main__":
    asyncio.run(main())
