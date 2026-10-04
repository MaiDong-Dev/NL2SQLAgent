# =============================================================================
# 【评测脚本】使用 Ragas 对 NL2SQL 系统进行评测
#
# 作用：跑一遍 eval/dataset.jsonl 中的问句，用 Ragas 指标量化系统表现。
#
# 评测的三个层次（对应系统的三段流水线）：
#   1. 召回质量（recall_column / recall_value / recall_metric）
#      → IDBasedContextPrecision / IDBasedContextRecall
#      把「字段 ID」当作文档 ID（如 "fact_order.order_amount"），
#      与标注的标准字段集合比对，不需要 LLM，成本为 0、结果确定。
#   2. SQL 语义等价性（generate_sql / correct_sql）
#      → 两种裁判可切（--judge）：
#        · jev（默认）：typesafe/jev-latest，System One 决策模型，不生成文本、
#          只返回校准概率；一次请求并行评估多个问题，成本约 $0.00005/条。
#        · ragas：SQLSemanticEquivalence，由裁判 LLM（DeepSeek）生成解释+结构化结论。
#        · both：两个都跑，用于对照（实测一致率 90.5%，分歧处 Jev 更准）。
#      两者都拿到建表 DDL 作为 schema 上下文，保证对照公平。
#   3. 执行结果准确性（端到端最终指标）
#      → 自定义 discrete_metric：execution_accuracy
#      真正执行两条 SQL，按"行集合"比较结果（忽略行序、浮点数取 6 位精度），
#      这是 NL2SQL 领域公认的主指标（Execution Accuracy）。
#
# 使用方式（必须在项目根目录执行）：
#   uv add ragas                                  # 首次安装
#   python -m eval.run_ragas_eval                 # 跑全量（默认 Jev 裁判）
#   python -m eval.run_ragas_eval --limit 3       # 只跑前 3 条（冒烟）
#   python -m eval.run_ragas_eval --skip-llm      # 跳过所有裁判（只算召回质量 + 执行准确性）
#   python -m eval.run_ragas_eval --judge ragas   # 切回 ragas（DeepSeek）裁判
#   python -m eval.run_ragas_eval --judge both    # 两个裁判都跑，输出一致率
#
# 密钥（两个来源任一即可）：
#   Jev    conf/app_config.yaml → eval.judge.openrouter_api_key（留空时回退环境变量 OPENROUTER_API_KEY）
#   ragas  走 app_config.llm 配置（其 api_key 默认取环境变量 DEEPSEEK_API_KEY）
#
# 产出：eval/results_<时间戳>.csv，每行一个用例的各指标得分与失败原因。
# =============================================================================

import argparse
import asyncio
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import llm_factory
from sqlalchemy import text

from eval.equivalence import deterministic_equivalence
from eval.jev_judge import (
    DEFAULT_THRESHOLD as JEV_DEFAULT_THRESHOLD,
)
from eval.jev_judge import (
    REQUEST_TIMEOUT as JEV_REQUEST_TIMEOUT,
)
from eval.jev_judge import (
    judge_equivalence,
    resolve_api_key,
)
from server.agent.events import ExecAccuracy

try:  # 新版 collections 尚未提供 ID-based 指标，直接按模块路径导入可避开弃用警告
    from ragas.metrics._context_precision import IDBasedContextPrecision
    from ragas.metrics._context_recall import IDBasedContextRecall
except ImportError:  # 未来版本变动时回退到公开入口
    from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall
from ragas.metrics.collections import SQLSemanticEquivalence
from ragas.metrics.collections.sql_semantic_equivalence.util import SQLEquivalencePrompt
from ragas.metrics.discrete import discrete_metric
from ragas.metrics.result import MetricResult

from server.agent.context import DataAgentContext
from server.agent.graph import graph
from server.clients.embedding_client_manager import embedding_client_manager
from server.clients.es_client_manager import es_client_manager
from server.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from server.clients.qdrant_client_manager import qdrant_client_manager
from server.conf.app_config import app_config
from server.repositories.es.value_es_repository import ValueESRepository
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from server.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from server.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from server.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
OUTPUT_DIR = Path(__file__).parent

# 裁判 LLM 单次输出上限：ragas 默认 1024，SQL 等价性要输出结构化结果+两段解释，
# 太小会被截断（instructor 抛 IncompleteOutputException）
JUDGE_MAX_TOKENS = 4096


# =============================================================================
# 指标 2 的裁判 Prompt：对齐「执行结果」的比较口径
#
# ragas 自带 prompt 只说"别名差异不影响等价"，实测会把 `region_name AS 大区`
# 这类别名差异判为不等价，导致 sql_equivalence(0.56) 远低于 execution_accuracy(0.78)。
# 这里换成显式规则：以「同一库状态下返回的数据集合是否一致」为唯一标准。
# =============================================================================
class Nl2SqlEquivalencePrompt(SQLEquivalencePrompt):
    instruction: str = """你是 SQL 语义等价性裁判。基于给定的数据库 schema，先分别解释两条 SQL（reference = 标准 SQL，response = 生成 SQL）的语义，再判断二者是否等价。

判定标准：两条 SQL 在同一数据库状态下返回的「数据集合」相同即等价。
以下差异一律视为「不影响等价性」：
1. 列别名不同（如 `region_name AS 大区` 与 `region_name`、`total_amount` 与 `销售额`）；
2. SELECT 列的顺序不同；
3. 结果行的顺序不同：一方有 ORDER BY 另一方没有、或排序键/排序方向不同，只要数据集合本身相同（排序只影响展示顺序）。但若一方含 LIMIT/TopN 而另一方不含，则以 LIMIT 规则为准；
4. 同一时间口径的不同写法（如 `DATE_FORMAT(date_id,'%Y-%m')` 与 `month` 列、`YEAR(d.date)=2025` 与 `d.year=2025`），只要表达的粒度与取值范围一致；
5. 语法糖差异：INNER JOIN 与 JOIN、USING 与 ON、子查询与等价 JOIN、隐式类型转换（1 与 true）。

以下差异构成「不等价」：
1. 聚合函数不同（SUM / COUNT / AVG / COUNT DISTINCT 等），或多做/少做了聚合；
2. 过滤条件不同、缺失或多余（含时间范围与维度取值）；
3. 分组维度（GROUP BY）不同或粒度不一致；
4. JOIN 的表或关联键不同；LEFT JOIN 与 INNER JOIN 在可能改变结果集时视为不等价；
5. SELECT 的实质列数量不同（多返回或少返回一个非别名列，例如多出一列排名列）；
6. LIMIT / TopN 的条数不同。

不要因为代码格式、命名风格、注释或关键字大小写差异判为不等价。"""


# =============================================================================
# 通用工具：兼容 ragas 不同的返回类型
# =============================================================================
def _value_of(score):
    """提取指标得分

    ragas 返回值有两种形态，这里统一：
      - 新版指标（SQLSemanticEquivalence 等）→ MetricResult，取 .value
      - legacy 指标（IDBased*，标注为 1.0 移除）→ 直接返回 float/int 裸值
    """
    return score.value if hasattr(score, "value") else score


def _reason_of(score) -> str:
    """提取指标的判定理由，裸值形态没有 reason"""
    return str(getattr(score, "reason", "") or "")


# =============================================================================
# 指标 3：执行准确性（自定义离散指标）
# =============================================================================
def _canon(value):
    """统一数值类型：Decimal/float/int 统一为 float 并保留 6 位小数

    为什么 int 也要转 float：MySQL 的 SUM/COUNT 聚合返回 Decimal，而表达式运算
    （如 COUNT(...) - COUNT(...)）返回 int。同一个数值 9 会表现成 Decimal('9') 与 9，
    字符串化后是 '9.0' 与 '9'，导致本应一致的结果被误判为不一致。
    """
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return round(float(value), 6)
    return value


def _row_values(row: dict):
    """把一行 dict 转成可比较的元组（含列名 + 值）"""
    return tuple(sorted((str(k), _canon(v)) for k, v in row.items()))


@discrete_metric(name="execution_accuracy", allowed_values=[m.value for m in ExecAccuracy])
def execution_accuracy(predicted_rows, reference_rows, predicted_error=None):
    """比较「生成 SQL」与「标准 SQL」的实际执行结果

    判定规则：
      - 生成 SQL 执行失败          → incorrect
      - 两边都返回 0 行            → empty_both（空集==空集不能证明等价，
                                     如过滤条件写错也可能查不到数据，故不计入通过）
      - 结果集（忽略行序）完全一致 → correct
      - 列名不同但数据一致         → correct（列名别名不应判错）
    """
    if predicted_error is not None:
        return MetricResult(value=ExecAccuracy.INCORRECT, reason=f"生成 SQL 执行失败: {predicted_error}")

    if predicted_rows is None or reference_rows is None:
        return MetricResult(value=ExecAccuracy.INCORRECT, reason="执行结果为空，无法比较")

    if not predicted_rows and not reference_rows:
        return MetricResult(
            value=ExecAccuracy.EMPTY_BOTH,
            reason="两边均返回 0 行，无法证明等价（不计通过，需人工复核）",
        )

    pred = sorted(_row_values(row) for row in predicted_rows)
    ref = sorted(_row_values(row) for row in reference_rows)

    if pred == ref:
        return MetricResult(value=ExecAccuracy.CORRECT, reason=f"结果一致（{len(ref)} 行）")

    # 退一步：只比较值，不比较列别名，也不比较列的顺序
    # （值统一转字符串再排序，避免 str/float 混合类型无法比较）
    pred_values = sorted(tuple(sorted(str(v) for _, v in row)) for row in pred)
    ref_values = sorted(tuple(sorted(str(v) for _, v in row)) for row in ref)
    if pred_values == ref_values:
        return MetricResult(value=ExecAccuracy.CORRECT, reason=f"数据一致但列名不同（{len(ref)} 行）")

    return MetricResult(
        value=ExecAccuracy.INCORRECT,
        reason=f"结果不一致：预期 {len(ref)} 行 / 实际 {len(pred)} 行；预期首行={ref[:1]} 实际首行={pred[:1]}",
    )


# 裁判之前的确定性前置校验（行数/列数不一致直接判否，补裁判的"分组粒度"盲区）。
# 实现放在 eval/equivalence.py，那里的版本不 import 重依赖，可以离线单测。
# =============================================================================
# 跑系统：一条问句 → (生成 SQL, 执行结果, 错误信息, 召回字段 ID)
# =============================================================================
async def run_agent(context: DataAgentContext, query: str):
    """调用 LangGraph 图执行一条查询，同时抓取执行结果与召回字段 ID

    说明：
      - stream_mode 同时传 "custom" 和 "updates"，一次运行既能拿到最终执行结果
        （execute_sql 通过 writer 输出），也能拿到各节点的 state 更新（召回字段、SQL）
      - 多 stream_mode 时 astream 产出 (mode, chunk) 元组
    """
    predicted_sql = None
    predicted_rows = None
    error = None
    retrieved_ids: set[str] = set()
    metric_column_ids: set[str] = set()

    async for mode, chunk in graph.astream(
        input={"query": query}, context=context, stream_mode=["custom", "updates"]
    ):
        if mode == "custom":
            if chunk.get("type") == "result":
                predicted_rows = chunk.get("data")
            elif chunk.get("type") == "error":
                error = chunk.get("message")
            continue

        # mode == "updates"：chunk 形如 {节点名: 该节点返回的 state 更新}
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            if "sql" in update:
                predicted_sql = update["sql"]
            for column_info in update.get("retrieved_columns", []):
                retrieved_ids.add(column_info.id)
            for value_info in update.get("retrieved_values", []):
                retrieved_ids.add(value_info.column_id)
            # 指标关联字段取「filter_metric 之后」的 metric_infos：
            # 系统只会把通过筛选的指标的字段并入候选（见 enrich_metric_columns），
            # 被裁掉的指标（如问"销售额"时的 AOV）其字段不会进入 prompt，
            # 因此也不该计入召回集合。merge 节点也会返回未裁剪的 metric_infos，
            # 会被 filter_metric 的结果覆盖，故这里用赋值而非 update。
            if "metric_infos" in update:
                metric_column_ids = {column_id for metric_info in update["metric_infos"]
                                     for column_id in metric_info["relevant_columns"]}

    return predicted_sql, predicted_rows, error, sorted(retrieved_ids | metric_column_ids)


async def load_schema_ddl(session) -> str:
    """从 DW 实时导出所有表的 DDL，作为 SQL 等价性判断的 schema 上下文"""
    result = await session.execute(text("show tables"))
    tables = [row[0] for row in result.fetchall()]

    ddl_list = []
    for table in tables:
        result = await session.execute(text(f"show create table {table}"))
        ddl_list.append(result.fetchone()[1])
    return "\n\n".join(ddl_list)


async def evaluate_case(context, dw_repository, case: dict, ddl: str, scorers: dict,
                        judge_cfg: dict | None = None):
    """评测单条用例，返回一行结果 dict

    judge_cfg 不为 None 时启用 Jev 裁判：{"client": httpx.AsyncClient, "threshold": float}

    耗时字段（agent_seconds / judge_seconds / case_seconds）用于定位瓶颈：
    业务链路是 6~7 次 LLM 调用，通常占大头；裁判只占 1 次。
    """
    case_started = time.perf_counter()

    query = case["query"]
    reference_sql = case["reference_sql"]
    reference_columns = case["reference_columns"]

    # 1) 跑系统
    agent_started = time.perf_counter()
    predicted_sql, predicted_rows, error, retrieved_ids = await run_agent(context, query)
    agent_seconds = time.perf_counter() - agent_started

    # 2) 执行标准 SQL 拿到参考结果
    try:
        reference_rows = await dw_repository.execute_sql(reference_sql)
    except Exception as e:
        reference_rows = None
        error = f"{error or ''} | 标准 SQL 执行失败: {e}".strip(" |")

    # 3) 指标1/2：Schema Linking 召回质量（基于 ID，无需 LLM）
    linking_sample = SingleTurnSample(
        user_input=query,
        retrieved_context_ids=retrieved_ids,
        reference_context_ids=reference_columns,
    )
    id_precision = _value_of(await scorers["precision"].single_turn_ascore(linking_sample))
    id_recall = _value_of(await scorers["recall"].single_turn_ascore(linking_sample))

    # 4) 指标3：SQL 语义等价性（裁判：ragas 的 LLM 裁判 / Jev 决策模型）
    sql_equivalence = float("nan")
    equivalence_reason = ""
    if scorers["equivalence"] is not None and predicted_sql:
        try:
            score = await scorers["equivalence"].ascore(
                response=predicted_sql,
                reference=reference_sql,
                reference_contexts=[ddl],
            )
            sql_equivalence = _value_of(score)
            equivalence_reason = _reason_of(score)
        except Exception as e:  # 裁判 LLM 失败不应中断整轮评测
            equivalence_reason = f"裁判 LLM 调用失败: {type(e).__name__}: {e}"

    # 4) 裁判之前的确定性前置校验：行数/列数不一致可直接判否，不必花裁判调用
    det_verdict, det_reason = deterministic_equivalence(predicted_rows, reference_rows, error)

    # 4') Jev 裁判：与 ragas 拿到同样的 DDL 上下文，判定用单点总体概率（见 jev_judge 模块说明）
    jev_equivalence = float("nan")
    jev_probability = float("nan")
    jev_reason = ""
    jev_cost = 0.0
    jev_input_tokens = 0
    judge_seconds = 0.0
    if judge_cfg is not None and predicted_sql:
        if det_verdict != "undecided":
            # 确定性方法已经判出结论：直接用它的结论，短路掉裁判调用（省一次 API 且不会被裁判的盲区带偏）
            if det_verdict == "incorrect":
                jev_equivalence = 0.0
            jev_reason = f"确定性校验判定：{det_reason}"
        else:
            judge_started = time.perf_counter()
            try:
                result = await judge_equivalence(
                    judge_cfg["client"],
                    query=query,
                    reference_sql=reference_sql,
                    predicted_sql=predicted_sql,
                    ddl=ddl,
                    threshold=judge_cfg["threshold"],
                )
                jev_equivalence = result["equivalence"]
                jev_probability = result["probability"]
                jev_reason = result["reason"]
                jev_cost = result["cost"]
                jev_input_tokens = result["input_tokens"]
            except Exception as e:  # 裁判失败不应中断整轮评测
                jev_reason = f"Jev 裁判调用失败: {type(e).__name__}: {e}"
            judge_seconds = time.perf_counter() - judge_started

    # 5) 指标4：执行准确性（真正跑库比对结果）
    exec_score = await execution_accuracy.ascore(
        predicted_rows=predicted_rows,
        reference_rows=reference_rows,
        predicted_error=error,
    )

    return {
        "query": query,
        "predicted_sql": predicted_sql or "",
        "reference_sql": reference_sql,
        "retrieved_ids": "|".join(retrieved_ids),
        "reference_ids": "|".join(reference_columns),
        "linking_precision": id_precision,
        "linking_recall": id_recall,
        "sql_equivalence": sql_equivalence,
        "sql_equivalence_reason": equivalence_reason,
        "jev_equivalence": jev_equivalence,
        "jev_probability": jev_probability,
        "jev_reason": jev_reason,
        "execution_accuracy": _value_of(exec_score),
        "execution_reason": _reason_of(exec_score),
        "det_verdict": det_verdict,
        "det_reason": det_reason,
        "predicted_rows": len(predicted_rows) if predicted_rows is not None else -1,
        "agent_seconds": round(agent_seconds, 3),
        "judge_seconds": round(judge_seconds, 3),
        "case_seconds": round(time.perf_counter() - case_started, 3),
        "jev_input_tokens": jev_input_tokens,
        "jev_cost": jev_cost,
    }


def _error_row(case: dict, error: Exception) -> dict:
    """用例执行异常时的占位行，保证 CSV 字段对齐、整轮评测不中断"""
    return {
        "query": case["query"],
        "predicted_sql": "",
        "reference_sql": case["reference_sql"],
        "retrieved_ids": "",
        "reference_ids": "|".join(case["reference_columns"]),
        "linking_precision": 0.0,
        "linking_recall": 0.0,
        "sql_equivalence": float("nan"),
        "sql_equivalence_reason": "",
        "jev_equivalence": float("nan"),
        "jev_probability": float("nan"),
        "jev_reason": "",
        "execution_accuracy": "error",
        "execution_reason": f"用例执行异常: {type(error).__name__}: {error}",
        "det_verdict": "incorrect",
        "det_reason": f"用例执行异常: {type(error).__name__}: {error}",
        "predicted_rows": -1,
        "agent_seconds": 0.0,
        "judge_seconds": 0.0,
        "case_seconds": 0.0,
        "jev_input_tokens": 0,
        "jev_cost": 0.0,
    }


# =============================================================================
# 终端过程输出
#
# 设计意图：评测一轮 63 条约 25 分钟，中途必须能看到"跑到哪、每条什么结果、
# 时间花在哪"，否则卡住了也判断不出是链路慢还是裁判慢。
# 所有输出都 flush，保证重定向到文件或管道时也能实时看到。
# =============================================================================
LINE = "─" * 78


def _one_line(text, limit: int = 96) -> str:
    """压成单行并截断，避免生成的 SQL 把终端刷爆"""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _secs(seconds: float) -> str:
    """人可读耗时：<60s 显示秒，否则显示分"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m{rest:04.1f}s"


def _missing_columns(row: dict) -> list[str]:
    """漏召回的字段：标注里有、召回结果里没有的（漏了就必然生成不出正确 SQL）"""
    retrieved = set(filter(None, str(row.get("retrieved_ids", "")).split("|")))
    reference = set(filter(None, str(row.get("reference_ids", "")).split("|")))
    return sorted(reference - retrieved)


def setup_quiet_logging() -> Path:
    """把节点级 INFO 日志从控制台挪到文件，让终端只留评测过程

    一轮 63 条会产生上千行节点日志（抽取关键词、召回字段、过滤表、生成的 SQL、
    执行结果各一条），直接打出来会把评测过程本身冲散。完整日志仍写入
    logs/eval_<时间戳>.log 留档，排查单条失败时可以回查；
    需要实时看节点日志时用 --verbose-logs。
    """
    log_path = Path("logs") / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    from loguru import logger as loguru_logger

    loguru_logger.remove()                                    # 去掉 log.py 加的控制台/文件 sink
    loguru_logger.add(sys.stderr, level="WARNING")            # 控制台只留警告及以上
    loguru_logger.add(log_path, level="INFO", rotation="10 MB", encoding="utf-8")
    return log_path


def print_case(index: int, total: int, row: dict, elapsed_total: float,
               passed: int, failed: int) -> None:
    """打印单条用例的完整过程"""
    verdict = row["execution_accuracy"]
    mark, label = {
        "correct": ("✓", "correct"),
        "incorrect": ("✗", "incorrect"),
        "empty_both": ("∅", "empty_both"),
    }.get(verdict, ("!", str(verdict)))

    # 判定摘要：Jev 概率（或 ragas 分数）
    bits = []
    if row["jev_probability"] == row["jev_probability"]:
        bits.append(f"Jev={row['jev_probability']:.2f}")
    if row["sql_equivalence"] == row["sql_equivalence"]:
        bits.append(f"ragas={row['sql_equivalence']:.2f}")
    judge_note = "  ".join(bits)

    print(f"[{index:>2}/{total}] {row['query']}")
    print(f"        召回   P={row['linking_precision']:.3f}  R={row['linking_recall']:.3f}"
          f"   ({len(str(row['retrieved_ids']).split('|')) if row['retrieved_ids'] else 0} 字段)")

    missing = _missing_columns(row)
    if missing:
        print(f"              漏召回: {', '.join(missing)}")

    print(f"        SQL    {_one_line(row['predicted_sql']) or '（未生成）'}")

    rows_count = row.get("predicted_rows", -1)
    count_note = f"{rows_count} 行" if rows_count >= 0 else "未执行"
    print(f"        执行   {count_note}")

    print(f"        判定   {mark} {label}" + (f"    {judge_note}" if judge_note else "")
          + f"    耗时 {_secs(row['case_seconds'])}"
            f"  (链路 {_secs(row['agent_seconds'])} / 裁判 {_secs(row['judge_seconds'])})")

    # 失败用例补上裁判/执行给出的原因，最值得人工看
    if verdict != ExecAccuracy.CORRECT:
        print(f"        原因   {_one_line(row['execution_reason'], 150)}")
        if row["jev_reason"]:
            print(f"        裁判   {_one_line(row['jev_reason'], 150)}")

    done = index
    rate = passed / done * 100
    avg = elapsed_total / done
    eta = avg * (total - done)
    print(f"    {LINE[:70]}")
    print(f"    进度 {done}/{total}  通过 {passed}  失败 {failed}  "
          f"准确率 {rate:.1f}%  均 {_secs(avg)}  剩余 ≈ {_secs(eta)}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="使用 Ragas 评测 NL2SQL 系统")
    parser.add_argument("-d", "--dataset", default=str(DATASET_PATH), help="评测集 jsonl 路径")
    parser.add_argument("-n", "--limit", type=int, default=None, help="只评测前 N 条")
    parser.add_argument("--skip-llm", action="store_true", help="跳过所有裁判（含 Jev 与 ragas）")
    parser.add_argument(
        "--judge",
        choices=["ragas", "jev", "both"],
        default="jev",
        help="SQL 等价性裁判：jev=决策模型（默认，便宜且更准）/ ragas=DeepSeek 裁判 / both=两者都跑并输出一致率",
    )
    parser.add_argument(
        "--jev-threshold",
        type=float,
        default=JEV_DEFAULT_THRESHOLD,
        help=f"Jev Noul 判定阈值（默认 {JEV_DEFAULT_THRESHOLD}，实测概率两极分化，结果对阈值不敏感）",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        help="保留节点级 INFO 日志（默认压到 WARNING，完整日志另写 logs/eval_*.log）",
    )
    args = parser.parse_args()

    # 日志：默认把节点级 INFO 挪到独立文件，终端只留评测过程本身
    eval_log_path = None if args.verbose_logs else setup_quiet_logging()

    # 裁判依赖的环境变量尽早失败，避免跑到一半才发现
    if not args.skip_llm and args.judge in ("jev", "both") and not resolve_api_key():
        raise SystemExit("未拿到 Jev 密钥：请在 conf/app_config.yaml 配置 eval.judge.openrouter_api_key，"
                         "或设置环境变量 OPENROUTER_API_KEY；也可改用 --judge ragas / --skip-llm")

    cases = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]

    print(LINE)
    print("  NL2SQL 全量评测")
    print(f"  评测集   : {Path(args.dataset).name}（{len(cases)} 条）")
    print(f"  业务 LLM : {app_config.llm.model_name} @ {app_config.llm.base_url}")
    if args.skip_llm:
        print("  SQL 裁判 : 已跳过（--skip-llm）")
    else:
        print(f"  SQL 裁判 : {args.judge}"
              + (f"（阈值 {args.jev_threshold}）" if args.judge in ("jev", "both") else ""))
    if eval_log_path:
        print(f"  节点日志 : {eval_log_path}（终端只显示评测过程，加 --verbose-logs 可实时输出）")
    print(LINE)
    print()

    # 初始化基础设施（与 FastAPI lifespan / build_meta_knowledge 脚本一致）
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    # Jev 裁判的 HTTP 客户端：在异步上下文之外创建，最后统一关闭
    http_client = None
    if not args.skip_llm and args.judge in ("jev", "both"):
        http_client = httpx.AsyncClient(timeout=JEV_REQUEST_TIMEOUT)

    rows = []
    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        meta_repository = MetaMySQLRepository(meta_session)
        dw_repository = DWMySQLRepository(dw_session)

        context = DataAgentContext(
            embedding_client=embedding_client_manager.client,
            column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
            value_es_repository=ValueESRepository(es_client_manager.client),
            metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
            meta_mysql_repository=meta_repository,
            dw_mysql_repository=dw_repository,
        )

        scorers = {
            "precision": IDBasedContextPrecision(),
            "recall": IDBasedContextRecall(),
            "equivalence": None,
        }
        if not args.skip_llm and args.judge in ("ragas", "both"):
            # 裁判 LLM：复用 app_config 里的 OpenAI 兼容端点（DeepSeek）
            judge_client = AsyncOpenAI(api_key=app_config.llm.api_key, base_url=app_config.llm.base_url)
            equivalence = SQLSemanticEquivalence(
                llm=llm_factory(app_config.llm.model_name,
                                 provider="openai",
                                 client=judge_client,
                                 max_tokens=JUDGE_MAX_TOKENS)
            )
            # 换用自定义裁判口径（别名/行序不影响等价），与 execution_accuracy 对齐
            equivalence.equivalence_prompt = Nl2SqlEquivalencePrompt()
            scorers["equivalence"] = equivalence

        # Jev 裁判：httpx 直连 OpenRouter 决策接口（不走 chat/completions）
        judge_cfg = None
        if not args.skip_llm and args.judge in ("jev", "both"):
            judge_cfg = {"client": http_client, "threshold": args.jev_threshold}

        ddl = await load_schema_ddl(dw_session)

        # 打印数据仓库规模与 DDL 长度：数据范围直接决定哪些问句会返回空结果
        stats = (await dw_session.execute(text(
            "SELECT COUNT(*), MIN(date_id), MAX(date_id) FROM fact_order"))).fetchone()
        print(f"  数据仓库 : {stats[0]} 单，{stats[1]} ~ {stats[2]}")
        print(f"  建表 DDL : {len(ddl)} 字符")
        print()

        passed = failed = 0
        run_started = time.perf_counter()
        for index, case in enumerate(cases, start=1):
            try:
                row = await evaluate_case(context, dw_repository, case, ddl, scorers, judge_cfg)
            except Exception as e:  # 单条用例异常（如 MySQL 连接中断）不应中断整轮评测
                row = _error_row(case, e)
            rows.append(row)

            if row["execution_accuracy"] == "correct":
                passed += 1
            else:
                failed += 1
            print_case(index, len(cases), row, time.perf_counter() - run_started, passed, failed)

    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()

    if http_client is not None:
        await http_client.aclose()

    # =========================================================================
    # 汇总报告
    # =========================================================================
    total = len(rows)
    run_elapsed = time.perf_counter() - run_started
    acc = sum(1 for r in rows if r["execution_accuracy"] == ExecAccuracy.CORRECT)
    empty = sum(1 for r in rows if r["execution_accuracy"] == ExecAccuracy.EMPTY_BOTH)
    broken = sum(1 for r in rows if r["execution_accuracy"] == "error")

    print(LINE)
    print(f"  评测完成：{total} 条，总耗时 {_secs(run_elapsed)}")
    print(LINE)

    # ---- 指标 ----
    print("\n【指标】")
    print(f"  字段召回精确率 linking_precision : {sum(r['linking_precision'] for r in rows) / total:.3f}")
    print(f"  字段召回召回率 linking_recall    : {sum(r['linking_recall'] for r in rows) / total:.3f}")
    if not args.skip_llm:
        if args.judge in ("ragas", "both"):
            valid = [r["sql_equivalence"] for r in rows if r["sql_equivalence"] == r["sql_equivalence"]]
            if valid:
                print(f"  SQL 等价率 sql_equivalence(ragas): {sum(valid) / len(valid):.3f}")
        if args.judge in ("jev", "both"):
            valid = [r["jev_equivalence"] for r in rows if r["jev_equivalence"] == r["jev_equivalence"]]
            if valid:
                print(f"  SQL 等价率 jev_equivalence       : {sum(valid) / len(valid):.3f}")
        if args.judge == "both":
            pairs = [(r["jev_equivalence"], r["sql_equivalence"]) for r in rows
                     if r["jev_equivalence"] == r["jev_equivalence"]
                     and r["sql_equivalence"] == r["sql_equivalence"]]
            if pairs:
                agree = sum(1 for jev, ragas in pairs if (jev >= 0.5) == (ragas >= 0.5)) / len(pairs)
                print(f"  两个裁判一致率                   : {agree:.2%}（{len(pairs)} 条可比）")
    print(f"  执行准确率 execution_accuracy    : {acc / total:.2%} ({acc}/{total})")
    if empty:
        print(f"    ⚠ 双空结果（不计通过，需人工复核）: {empty} 条")
    if broken:
        print(f"    ⚠ 评测过程异常（连接中断等）: {broken} 条")

    # ---- 裁判：确定性前置校验的覆盖与裁判偏差 ----
    if not args.skip_llm and args.judge in ("jev", "both"):
        # 确定性校验能直接判否的（行数/列数不一致），不必再看裁判
        short_circuit = sum(1 for r in rows if r.get("det_verdict") == "incorrect")
        to_judge = total - short_circuit
        print(f"\n【裁判】确定性前置校验短路 {short_circuit}/{total} 条"
              f"（行数或列数不一致，直接判否），其余 {to_judge} 条交裁判")

        # 裁判与执行结果的分歧：判等价但执行不对 = 裁判假阳性，最需要关注
        false_positive = [r for r in rows
                          if r["execution_accuracy"] != "correct"
                          and r["jev_equivalence"] == 1.0]
        false_negative = [r for r in rows
                          if r["execution_accuracy"] == ExecAccuracy.CORRECT
                          and r["jev_equivalence"] == 0.0]
        if false_positive:
            print(f"  ⚠ 裁判假阳性 {len(false_positive)} 条（判等价但执行结果不对）:")
            for r in false_positive:
                print(f"      - {_one_line(r['query'], 60)}")
        if false_negative:
            print(f"  ⚠ 裁判假阴性 {len(false_negative)} 条（判不等价但执行结果正确）:")
            for r in false_negative:
                print(f"      - {_one_line(r['query'], 60)}")

    # ---- 耗时 ----
    print("\n【耗时】")
    agent_total = sum(r["agent_seconds"] for r in rows)
    judge_total = sum(r["judge_seconds"] for r in rows)
    print(f"  业务链路合计 {_secs(agent_total)}（均 {_secs(agent_total / total)}/条）")
    if judge_total:
        print(f"  裁判合计     {_secs(judge_total)}（均 {_secs(judge_total / total)}/条）")
    print(f"  整轮墙钟     {_secs(run_elapsed)}（均 {_secs(run_elapsed / total)}/条）")

    # ---- 裁判成本 ----
    jev_cost = sum(r.get("jev_cost", 0.0) for r in rows)
    if jev_cost:
        tokens = sum(r.get("jev_input_tokens", 0) for r in rows)
        print(f"  Jev 裁判成本 ${jev_cost:.6f}（{tokens} input tokens，输出免费）")

    # ---- 失败明细 ----
    failures = [r for r in rows if r["execution_accuracy"] != "correct"]
    if failures:
        print(f"\n【失败明细】{len(failures)} 条")
        for r in failures:
            tag = {"empty_both": "双空结果", "error": "执行异常"}.get(r["execution_accuracy"], "结果不一致")
            print(f"  ✗ [{tag}] {r['query']}")
            print(f"      {_one_line(r['execution_reason'], 160)}")
            if r["jev_reason"]:
                print(f"      裁判: {_one_line(r['jev_reason'], 160)}")
    else:
        print("\n【失败明细】无，全部通过")

    # ---- 召回缺陷 ----
    # 漏召回意味着生成 SQL 时看不到该字段，必然出错，比精确率更值得优先修
    miss_counter = Counter()
    for r in rows:
        miss_counter.update(_missing_columns(r))
    no_miss = sum(1 for r in rows if not _missing_columns(r))
    print(f"\n【字段召回】无漏召回 {no_miss}/{total} 条")
    if miss_counter:
        top = "、".join(f"{col}({n})" for col, n in miss_counter.most_common(8))
        print(f"  漏召回最多的字段: {top}")

    # ---- 结果的可复现性说明 ----
    # 实测：同一份数据、同一套代码连跑两次，会有 3~5 条用例判定翻转，
    # 只有少数几条是稳定失败。所以单次运行之间的差异属于噪声，不能据此判断系统好坏。
    print("\n【可复现性】")
    print("  LLM 在 temperature=0 下也无法保证逐字复现（实测同问句连跑 5 次可出多个写法），")
    print("  因此单次运行之间 1~3 条用例的翻转属于噪声，不可作为「改动有效/系统退化」的依据。")
    print("  要比较两次改动的效果，请重复多轮取稳定结论，或只关注多轮都失败的用例。")

    print("\n" + LINE)

    output_path = OUTPUT_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"逐条明细已写入: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
