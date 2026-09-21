# =============================================================================
# 【运维脚本】外部依赖服务健康检查
# 作用：逐个探测 NL2SQLAgent 依赖的外部服务是否可用、数据是否就绪，用于
#       启动服务前 / 部署后快速定位环境问题。
#
# 检查项：
#   1. mysql-meta   元数据库（表/字段/指标定义）
#   2. mysql-dw     数据仓库（业务数据，SQL 实际执行的地方）
#   3. qdrant       向量库（data-agent-column / data-agent-metric 两个 collection）
#   4. es           Elasticsearch（字段取值倒排索引）
#   5. embedding    TEI 向量化服务（校验输出维度是否与 qdrant.embedding_size 一致）
#   6. llm          大模型接口（DeepSeek 等 OpenAI 兼容端点）
#
# 运行方式（在项目根目录）：
#   python -m scripts.check_services
#   python -m scripts.check_services --timeout 20      # 单项超时调大
#   python -m scripts.check_services --skip llm        # 跳过某项（可多次指定）
#
# 退出码：全部通过返回 0，存在失败项返回 1（可直接用于 CI / shell 判断）。
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 保证 `python scripts/check_services.py` 与 `python -m scripts.check_services` 都能 import server 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from server.clients.embedding_client_manager import embedding_client_manager  # noqa: E402
from server.clients.es_client_manager import es_client_manager  # noqa: E402
from server.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager  # noqa: E402
from server.clients.qdrant_client_manager import qdrant_client_manager  # noqa: E402
from server.conf.app_config import app_config  # noqa: E402

# 与 Repository 中写死的名称保持一致（server/repositories/qdrant/*）
QDRANT_COLUMN_COLLECTION = "data-agent-column"
QDRANT_METRIC_COLLECTION = "data-agent-metric"


@dataclass
class CheckResult:
    """单项检查结果"""

    name: str
    ok: bool
    detail: str = ""
    elapsed: float = 0.0


async def check_mysql(mysql_client_manager, label: str) -> CheckResult:
    """检查 MySQL 连通性与表数量

    参数：mysql_client_manager  MysqlClientManager  meta / dw 客户端管理器
          label                 str                展示名称（含库名）
    """
    mysql_client_manager.init()
    async with mysql_client_manager.session_factory() as session:
        version = (await session.execute(text("SELECT VERSION()"))).scalar_one()
        tables = [row[0] for row in (await session.execute(text("SHOW TABLES"))).all()]
    preview = "、".join(tables[:5]) + ("…" if len(tables) > 5 else "")
    return CheckResult(
        name=f"mysql-{label}",
        ok=True,
        detail=f"MySQL {version} · 库 {mysql_client_manager.db_config.database} · {len(tables)} 张表：{preview or '空库'}",
    )


async def check_qdrant() -> CheckResult:
    """检查 Qdrant 连通性，并确认字段/指标两个 collection 是否已构建"""
    qdrant_client_manager.init()
    client = qdrant_client_manager.client
    existing = {c.name for c in (await client.get_collections()).collections}

    parts, ok = [], True
    for alias, name in (("column", QDRANT_COLUMN_COLLECTION), ("metric", QDRANT_METRIC_COLLECTION)):
        if name not in existing:
            ok = False
            parts.append(f"{alias}({name}) 缺失")
            continue
        count = (await client.count(collection_name=name, exact=False)).count
        parts.append(f"{alias}({name}) {count} 条")

    return CheckResult(name="qdrant", ok=ok, detail=f"{app_config.qdrant.host}:{app_config.qdrant.port} · " + "；".join(parts))


async def check_es() -> CheckResult:
    """检查 Elasticsearch 连通性、集群状态与字段取值索引的数据量"""
    es_client_manager.init()
    client = es_client_manager.client
    info = await client.info()
    version = info.get("version", {}).get("number", "unknown")  # ObjectApiResponse 支持 Mapping 访问
    health = (await client.cluster.health()).get("status", "unknown")

    index = app_config.es.index_name
    exists = await client.indices.exists(index=index)
    count = (await client.count(index=index)).get("count", 0) if exists else 0

    return CheckResult(
        name="elasticsearch",
        ok=exists,
        detail=f"ES {version} · 集群 {health} · {index} " + (f"{count} 条" if exists else "索引不存在（需先构建元知识）"),
    )


async def check_embedding() -> CheckResult:
    """检查 Embedding 服务：向量化一条文本，并校验维度与 Qdrant 配置一致"""
    embedding_client_manager.init()
    vector = await embedding_client_manager.client.aembed_query("连通性测试")
    dim = len(vector)
    expected = app_config.qdrant.embedding_size
    return CheckResult(
        name="embedding",
        ok=dim == expected,
        detail=f"{app_config.embedding.host}:{app_config.embedding.port} · 输出维度 {dim}（Qdrant 配置 {expected}）",
    )


async def check_llm() -> CheckResult:
    """检查 LLM 接口：发送一条极短提示，确认能正常回包"""
    from server.agent.llm import llm  # 延迟导入：LLM 初始化失败不影响其他检查项

    response = await llm.ainvoke("只回复两个字：正常")
    content = getattr(response, "content", str(response))
    return CheckResult(
        name="llm",
        ok=bool(str(content).strip()),
        detail=f"{app_config.llm.model_name} @{app_config.llm.base_url} · 回复：{str(content)[:50]}",
    )


# 全部检查项：名称 -> 协程工厂
CHECKS: dict[str, callable] = {
    "mysql-meta": lambda: check_mysql(meta_mysql_client_manager, "meta"),
    "mysql-dw": lambda: check_mysql(dw_mysql_client_manager, "dw"),
    "qdrant": check_qdrant,
    "es": check_es,
    "embedding": check_embedding,
    "llm": check_llm,
}


async def run_checks(names: list[str], timeout: float) -> list[CheckResult]:
    """按顺序执行检查，单项超时或异常统一转成失败结果

    参数：names     list[str]  要执行的检查项名称
          timeout   float      单项超时秒数
    """
    results: list[CheckResult] = []
    for name in names:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(CHECKS[name](), timeout=timeout)
        except asyncio.TimeoutError:
            result = CheckResult(name=name, ok=False, detail=f"超时（>{timeout}s），检查 host/端口是否可达")
        except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉所有异常并汇总
            result = CheckResult(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")
        result.elapsed = time.perf_counter() - started
        results.append(result)
    return results


async def close_all() -> None:
    """释放已建立的连接（部分客户端可能未 init，逐个忽略异常）"""
    for close in (
        qdrant_client_manager.close,
        es_client_manager.close,
        meta_mysql_client_manager.close,
        dw_mysql_client_manager.close,
    ):
        try:
            await close()
        except Exception:  # noqa: BLE001 - 关闭阶段异常无需中断
            pass


async def main() -> int:
    parser = argparse.ArgumentParser(description="NL2SQLAgent 外部依赖服务健康检查")
    parser.add_argument("--timeout", type=float, default=10.0, help="单项检查超时秒数，默认 10")
    parser.add_argument("--skip", action="append", default=[], choices=list(CHECKS), help="跳过的检查项，可多次指定")
    args = parser.parse_args()

    names = [name for name in CHECKS if name not in args.skip]
    print(f"开始检查 {len(names)} 项依赖服务（超时 {args.timeout}s/项）\n")

    results = await run_checks(names, args.timeout)
    await close_all()

    width = max(len(r.name) for r in results)
    for r in results:
        flag = "PASS" if r.ok else "FAIL"
        print(f"[{flag}] {r.name.ljust(width)}  {r.elapsed:5.2f}s  {r.detail}")

    failed = [r.name for r in results if not r.ok]
    print(f"\n结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        print("失败项：" + "、".join(failed))
        return 1
    print("所有依赖服务正常")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
