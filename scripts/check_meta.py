# =============================================================================
# 【运维脚本】元知识库状态体检
# 作用：把「元知识库当前到底是什么状态」一次性打印出来，并检查它与
#       `conf/meta_config.yaml` 的声明是否一致。
#
# 与 `scripts/check_services.py` 的分工：
#   - check_services：外部依赖**通不通**（能不能连、服务版本、LLM 能不能调）
#   - check_meta    ：元知识**对不对、全不全**（条目数、示例值、向量数、取值索引）
#   两者互补，排查问题时建议先跑 check_services，再跑 check_meta。
#
# 检查项：
#   1. 配置文件声明的 表 / 字段 / 指标 数量
#   2. Meta MySQL 四张表的实际行数，与配置对账（缺字段 / 多字段 / 孤儿字段）
#   3. 每个字段的 examples 是否为空（空说明没从 DW 取到值，会影响生成 SQL 的质量）
#   4. Qdrant 两个 Collection 的向量条数（正常：字段数 × 每个字段的向量维度数）
#   5. ES 字段取值索引的总条数与按字段分布
#
# 运行方式（三种都可以，配置文件会自动按项目根定位，与当前目录无关）：
#   python -m scripts.check_meta                   # 推荐
#   python scripts/check_meta.py                   # 直接跑文件
#   IDE 右键运行本文件                              # cwd 在 scripts/ 下也能跑
# 常用参数：
#   -c /path/to/meta_config.yaml                   # 指定配置文件（默认 conf/meta_config.yaml）
#   --examples                                     # 打印每个字段的示例值
#   --es-detail                                    # 打印 ES 按字段的取值分布
#
# 退出码：全部一致返回 0，存在不一致返回 1（可用于 CI / shell 判断）。
# =============================================================================

from __future__ import annotations

import asyncio
import sys
from argparse import ArgumentParser
from pathlib import Path

# 保证 `python scripts/check_meta.py` 与 `python -m scripts.check_meta` 都能 import server 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omegaconf import OmegaConf  # noqa: E402
from sqlalchemy import text  # noqa: E402

from server.clients.es_client_manager import es_client_manager  # noqa: E402
from server.clients.mysql_client_manager import meta_mysql_client_manager  # noqa: E402
from server.clients.qdrant_client_manager import qdrant_client_manager  # noqa: E402
from server.repositories.es.value_es_repository import ValueESRepository  # noqa: E402
from server.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository  # noqa: E402
from server.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository  # noqa: E402

# Meta 库四张表（与 deploy/mysql/meta.sql 一致）
META_TABLES = ["table_info", "column_info", "metric_info", "column_metric"]

# 默认配置文件路径（相对项目根，避免受当前工作目录影响）
DEFAULT_CONF = "conf/meta_config.yaml"


def _resolve_conf(raw: str) -> Path:
    """解析配置文件路径：绝对路径直接用；相对路径优先按当前目录找，找不到再按项目根找。

    这样 `python scripts/check_meta.py`、`python -m scripts.check_meta`、
    以及 IDE 直接右键运行（cwd 可能在 scripts/ 下）三种方式都能定位到配置。
    """
    p = Path(raw)
    if p.is_absolute():
        return p
    if p.exists():
        return p
    return ROOT / p


def _load_expected(config_path: Path) -> tuple[set[str], set[str], set[str]]:
    """从配置文件解析出「声明了哪些表 / 字段 / 指标」

    字段 id 规则与构建脚本一致：`{表名}.{字段名}`（如 fact_order.order_amount）
    """
    conf = OmegaConf.load(config_path)
    tables = {t.name for t in conf.tables}
    columns = {f"{t.name}.{c.name}" for t in conf.tables for c in t.columns}
    metrics = {m.name for m in conf.metrics}
    return tables, columns, metrics


def _mark(ok: bool) -> str:
    return "[PASS]" if ok else "[FAIL]"


async def check(config_path: Path, show_examples: bool, show_es_detail: bool) -> bool:
    """体检主流程，返回是否存在不一致"""
    all_ok = True

    # ========== 配置文件声明 ==========
    expected_tables, expected_columns, expected_metrics = _load_expected(config_path)
    print(f"配置文件 {config_path}：声明 {len(expected_tables)} 张表 / "
          f"{len(expected_columns)} 个字段 / {len(expected_metrics)} 个指标")

    meta_mysql_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()

    # ========== 1. Meta MySQL 行数 ==========
    print("\n=== Meta MySQL ===")
    async with meta_mysql_client_manager.session_factory() as session:
        counts = {}
        for table in META_TABLES:
            counts[table] = (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
        print(f"{_mark(counts['table_info'] == len(expected_tables))} table_info    "
              f"{counts['table_info']} 行（配置声明 {len(expected_tables)}）")
        print(f"{_mark(counts['column_info'] == len(expected_columns))} column_info   "
              f"{counts['column_info']} 行（配置声明 {len(expected_columns)}）")
        print(f"{_mark(counts['metric_info'] == len(expected_metrics))} metric_info   "
              f"{counts['metric_info']} 行（配置声明 {len(expected_metrics)}）")
        print(f"     column_metric {counts['column_metric']} 行（指标→字段关联）")
        all_ok &= counts["table_info"] == len(expected_tables)
        all_ok &= counts["column_info"] == len(expected_columns)
        all_ok &= counts["metric_info"] == len(expected_metrics)

        # ========== 2. 配置与库对账 ==========
        rows = (await session.execute(
            text("SELECT id, table_id, examples FROM column_info"))).fetchall()
        actual_columns = {r[0] for r in rows}
        missing = sorted(expected_columns - actual_columns)   # 配置有、库里没有
        extra = sorted(actual_columns - expected_columns)     # 库里有、配置已删
        orphan = sorted({r[1] for r in rows} - expected_tables)  # 字段挂在已删的表上

        if missing:
            all_ok = False
            print(f"\n[FAIL] 配置声明但库里缺失的字段（{len(missing)}）：{missing}")
        if extra:
            all_ok = False
            print(f"\n[FAIL] 库里有但配置未声明的字段（{len(extra)}）：{extra}")
        if orphan:
            all_ok = False
            print(f"\n[FAIL] 字段所属表已不在配置中（孤儿表 id）：{orphan}")
        if not (missing or extra or orphan):
            print("\n[PASS] 字段清单与配置完全一致，无缺失 / 无多余 / 无孤儿")

        # ========== 3. examples 为空检查 ==========
        empty_examples = sorted(r[0] for r in rows if not r[2])
        if empty_examples:
            print(f"[WARN] 以下字段 examples 为空（未从 DW 取到值）：{empty_examples}")
        else:
            print("[PASS] 所有字段均有 examples")

        # ========== 4. 示例值明细（可选）==========
        if show_examples:
            print("\n=== 字段示例值（column_info.examples）===")
            for cid, _tid, ex in sorted(rows):
                print(f"  {cid}: {ex}")

    # ========== 5. Qdrant ==========
    print("\n=== Qdrant ===")
    qdrant_client = qdrant_client_manager.client
    for name in (ColumnQdrantRepository.collection_name, MetricQdrantRepository.collection_name):
        if not await qdrant_client.collection_exists(name):
            all_ok = False
            print(f"[FAIL] {name}: Collection 不存在")
            continue
        info = await qdrant_client.get_collection(name)
        print(f"[PASS] {name}: {info.points_count} 条向量")

    # ========== 6. ES 字段取值索引 ==========
    print("\n=== ES 字段取值索引 ===")
    es_client = es_client_manager.client
    index_name = ValueESRepository.index_name
    if not await es_client.indices.exists(index=index_name):
        all_ok = False
        print(f"[FAIL] {index_name}: 索引不存在")
    else:
        await es_client.indices.refresh(index=index_name)
        total = (await es_client.count(index=index_name))["count"]
        print(f"[PASS] {index_name}: 共 {total} 条")
        if show_es_detail:
            agg = await es_client.search(index=index_name, body={
                "size": 0,
                "aggs": {"by_column": {"terms": {"field": "column_id", "size": 100}}},
            })
            buckets = agg["aggregations"]["by_column"]["buckets"]
            for b in buckets:
                print(f"  {b['key']}: {b['doc_count']} 条")
            covered = {b["key"] for b in buckets}
            no_value = sorted(expected_columns - covered)
            if no_value:
                print(f"  （以下字段未建取值索引，多为 sync: false 或取值无区分度：{len(no_value)} 个）")

    await meta_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()
    return all_ok


if __name__ == "__main__":
    parser = ArgumentParser(description="检查元知识库当前状态（条目、示例值、向量、取值索引）")
    parser.add_argument("-c", "--conf", default=DEFAULT_CONF, help=f"元知识配置文件（默认 {DEFAULT_CONF}）")
    parser.add_argument("--examples", action="store_true", help="打印每个字段的示例值")
    parser.add_argument("--es-detail", action="store_true", help="打印 ES 按字段的取值分布")
    args = parser.parse_args()

    ok = asyncio.run(check(_resolve_conf(args.conf), args.examples, args.es_detail))
    print("\n结果：" + ("元知识库状态正常" if ok else "存在不一致，请检查上面的 [FAIL] 项"))
    sys.exit(0 if ok else 1)
