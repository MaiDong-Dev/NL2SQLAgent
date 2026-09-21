# =============================================================================
# 【Jev 裁判】SQL 语义等价判定（typesafe/jev-latest，经 OpenRouter 决策接口）
#
# Jev 是 System One 模型：不生成文本，只把一段 state + 一组预先定义好的问题
# 转成带校准概率的类型化答案。SQL 等价性本质是判断题，正好适合它。
#
# 接口（不是 chat/completions，是决策接口）：
#   POST https://openrouter.ai/api/alpha/decisions
#   请求体: {"model": "~typesafe/jev-latest", "state": str, "questions": {...}}
#   响应体: {"model": ..., "answers": {"<key>": {"type": "noul", "noul": 0.97}, ...},
#            "usage": {"input_tokens": 561, "output_tokens": 39, "cost": 0.0000235}}
#   鉴权: 环境变量 OPENROUTER_API_KEY
#
# 判定口径：**用单点总体概率，不用原子合成**。
# 实测（63 条，见 09-评测报告.md 7.3 节）：总体判断 F1 0.984，而"6 个原子全部为是
# 才等价"的 Composite scoring 只有 0.931——因为子查询 vs JOIN、日期函数 vs 年月列
# 这类**等价写法**会被原子问题判为不一致，而它们查出的数据集合是相同的。
# 所以原子问题只用来归因（说明"为什么不等价"），不参与判定。
# =============================================================================

import json
import os

import httpx

# OpenRouter 决策接口（alpha）
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
# `~` 前缀表示允许 OpenRouter 自行选择该模型的部署
MODEL = "~typesafe/jev-latest"

# Noul 判定阈值：返回 0~1 的"为真的概率"，>= 阈值视为"是"。
# 实测概率中位数 0.97、仅 2/63 落在 [0.4,0.6]，判定结果对阈值不敏感。
DEFAULT_THRESHOLD = 0.5

REQUEST_TIMEOUT = 60

# 原子维度（仅用于归因输出，不参与判定）
ATOMIC_KEYS = ["same_tables", "same_agg", "same_filter", "same_group", "same_limit", "same_columns"]


def _noul(instructions: str, true: str, false: str) -> dict:
    """构造一个 noul 型问题（decisions 接口格式）

    criteria 写**具体情境**而非"轻微/严重"这类抽象档位——官方明确说抽象档位
    会把概率往 0.5 摊平。
    """
    return {"type": "noul", "instructions": instructions,
            "criteria": {"true": true, "false": false}}


def build_questions() -> dict:
    """1 个总体判断 + 6 个原子维度；同一 state 下并行评估，加问题几乎不加延迟"""
    return {
        # ---- 总体判断：唯一参与判定的问题，口径与 execution_accuracy 对齐 ----
        "same_result": _noul(
            "在同一份数据库数据上，reference（标准 SQL）与 response（生成 SQL）返回的数据集合是否相同？只比较数据本身，不比较写法。",
            "两条 SQL 查出的是同一批数据：值相同、行数相同、粒度相同。仅列别名、SELECT 列顺序、行顺序、时间口径的等价写法不同，仍算相同。",
            "两条 SQL 查出的数据不同：聚合口径不同、过滤条件不同、分组粒度不同、JOIN 的表或关联键不同、SELECT 的实质列数量不同、LIMIT 条数不同。",
        ),
        # ---- 以下仅用于归因 ----
        "same_tables": _noul(
            "两条 SQL 涉及的表集合与 JOIN 关联键是否语义一致？",
            "用到的表相同，关联键相同；INNER JOIN 与 JOIN、USING 与 ON、子查询与等价 JOIN 视为一致。",
            "多 JOIN 或少 JOIN 一张表；关联键不同；LEFT JOIN 与 INNER JOIN 的差别会导致结果集变化时，视为不一致。",
        ),
        "same_agg": _noul(
            "两条 SQL 的聚合方式与聚合口径是否一致？",
            "聚合函数相同（同为 SUM/COUNT/AVG/COUNT DISTINCT 等），聚合的对象列相同；两边都不聚合也算一致。",
            "聚合函数不同；一方聚合另一方不聚合；聚合对象列不同；多做或少做一层聚合。",
        ),
        "same_filter": _noul(
            "两条 SQL 的过滤条件（WHERE/HAVING，含时间范围与维度取值）是否语义等价？",
            "筛选出的记录集合相同：同一时间口径的不同写法（日期函数与年月列）、IN 与等价 OR、取值范围一致均算等价。",
            "过滤条件缺失、多余或取值不同；时间范围不同；HAVING 阈值不同。",
        ),
        "same_group": _noul(
            "两条 SQL 的分组维度与分组粒度是否一致？",
            "GROUP BY 的维度相同（含都不分组）；按年/按月等时间粒度相同。",
            "分组维度不同或数量不同；粒度不同（一方按年、另一方按月）；一方分组另一方不分组。",
        ),
        "same_limit": _noul(
            "两条 SQL 的 LIMIT / TopN 条数是否一致？",
            "都不限制返回条数，或限制条数相同。",
            "一方有 LIMIT 另一方没有；条数不同（如 Top3 与 Top5）。",
        ),
        "same_columns": _noul(
            "两条 SQL 的 SELECT 实质列（忽略别名与排列顺序）是否一致？",
            "实质列数量与内容相同，仅别名不同（`region_name AS 大区` 与 `region_name`）或顺序不同。",
            "多返回或少返回一个实质列（如多出一列排名列、少一列销售额）。",
        ),
    }


def build_state(query: str, reference_sql: str, predicted_sql: str, ddl: str | None = None) -> str:
    """state 只放判断真正需要的信息（官方：无关内容会拉低准确率）

    用纯文本拼装：示例接口以字符串 state 调用，且中文 SQL 场景下字符串比
    JSON 对象更省 token、也更不易被嵌套结构干扰。
    """
    parts = [
        f"用户问句: {query}",
        f"标准SQL(reference):\n{reference_sql}",
        f"生成SQL(response):\n{predicted_sql}",
    ]
    if ddl:
        parts.append(f"数据库DDL:\n{ddl}")
    return "\n\n".join(parts)


async def judge_equivalence(
    client: httpx.AsyncClient,
    query: str,
    reference_sql: str,
    predicted_sql: str,
    ddl: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """判一条：返回判定结果、总体概率、原子归因与用量

    返回字段：
      equivalence   1.0 / 0.0（总体概率过阈值）
      probability   总体 Noul 概率
      atoms         各原子维度概率（dict）
      failed_atoms  未达到阈值的原子维度（list，仅用于归因）
      reason        人可读的判定理由
      model / input_tokens / cost
    """
    body = {
        "model": MODEL,
        "state": build_state(query, reference_sql, predicted_sql, ddl),
        "questions": build_questions(),
    }
    response = await client.post(
        DECISIONS_URL,
        headers={
            "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
            "Content-Type": "application/json",
        },
        content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    )
    response.raise_for_status()
    payload = response.json()

    answers = payload.get("answers", {}) or {}
    probs = {key: float(value["noul"]) for key, value in answers.items()
             if isinstance(value, dict) and value.get("noul") is not None}

    overall = probs.get("same_result", float("nan"))
    atoms = {key: probs.get(key) for key in ATOMIC_KEYS}
    failed_atoms = [key for key, value in atoms.items() if value is None or value < threshold]
    equivalent = overall >= threshold

    if equivalent:
        reason = f"Jev 判定等价（总体概率 {overall:.2f}）"
        if failed_atoms:
            # 等价但原子不一致 = 写法不同但数据相同，值得记一笔（这正是 ragas 判错的那类）
            reason += f"；写法差异维度: {', '.join(failed_atoms)}"
    else:
        reason = f"Jev 判定不等价（总体概率 {overall:.2f}）"
        if failed_atoms:
            reason += f"；不成立维度: {', '.join(failed_atoms)}"

    usage = payload.get("usage", {}) or {}
    return {
        "equivalence": 1.0 if equivalent else 0.0,
        "probability": overall,
        "atoms": atoms,
        "failed_atoms": failed_atoms,
        "reason": reason,
        "model": payload.get("model", ""),
        "input_tokens": usage.get("input_tokens", 0),
        "cost": usage.get("cost", 0.0),
    }
