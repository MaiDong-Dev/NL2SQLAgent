"""Held-out 冒烟：跑一批不在 eval/dataset.jsonl 里的问句，验证泛化性

用法（项目根目录）：
  python -m scripts.smoke_heldout

用途：每次改 prompt / 召回逻辑后，除了跑 eval 全量，也跑一批"没见过"的问句，
确认提升不是对评测集的过拟合。脚本只打印生成的 SQL 与前几行结果，人工审阅：
  1. 时间问句是否 JOIN 了时间维表（而不是对 date_id 做算术/字符串函数）；
  2. 排名类问句是否用 ORDER BY + LIMIT（而不是 RANK() 窗口函数）；
  3. 输出列是否精简（不多出分组用的 ID 列、不多出排名列）。
问句清单在 QUERIES 中维护，改动系统能力后应同步补充新问句。
"""

import asyncio

from server.agent.context import DataAgentContext
from server.agent.graph import graph
from server.clients.embedding_client_manager import embedding_client_manager
from server.clients.es_client_manager import es_client_manager
from server.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from server.clients.qdrant_client_manager import qdrant_client_manager
from server.repositories.es.value_es_repository import ValueESRepository
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from server.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from server.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from server.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

# 注意：dw 数据仓库只有 2025 年 Q1（1~3 月）共 115 笔订单，
# 问句涉及 2024 年 / Q2~Q4 会返回空结果，冒烟时会被判为「结果为空」告警。
# 新增问句时请确认过滤条件落在这个数据范围内。
QUERIES = [
    "2025年第一季度的销售额是多少",
    "2025年华东大区每个月的订单量",
    "销售额排名前三的大区有哪些",
    "2025年3月销量最高的商品是哪个",
    "2025年1到3月各商品品类的销售额",
    "铂金会员在第一季度下了多少单",
    "广东省2025年每个月的销售额是多少",
    "各品牌在2025年的平均订单金额是多少",
]


async def main():
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        context = DataAgentContext(
            embedding_client=embedding_client_manager.client,
            column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
            value_es_repository=ValueESRepository(es_client_manager.client),
            metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
            meta_mysql_repository=MetaMySQLRepository(meta_session),
            dw_mysql_repository=DWMySQLRepository(dw_session),
        )

        for index, query in enumerate(QUERIES, start=1):
            sql = None
            rows = None
            error = None
            async for mode, chunk in graph.astream(
                input={"query": query}, context=context, stream_mode=["custom", "updates"]
            ):
                if mode == "custom":
                    if chunk.get("type") == "result":
                        rows = chunk.get("data")
                    elif chunk.get("type") == "error":
                        error = chunk.get("message")
                    continue
                for update in chunk.values():
                    if isinstance(update, dict) and "sql" in update:
                        sql = update["sql"]

            print("=" * 70)
            print(f"[{index}] {query}")
            print(f"SQL: {sql}")
            if error:
                print(f"ERROR: {error}")
            elif rows:
                print(f"行数: {len(rows)}")
                for row in rows[:3]:
                    print("   ", row)

            # 自动检查1：结果为空通常意味着问句超出数据范围（dw 仅 2025 Q1 有数据）
            if not error and rows is not None and len(rows) == 0:
                print("WARNING 结果为空：过滤条件可能超出数据范围")
            # 自动检查2：对日期键做算术/字符串处理，说明没有正确 JOIN 时间维表
            if sql and "date_id" in sql and any(
                    keyword in sql.upper() for keyword in (" DIV ", "DATE_FORMAT", "SUBSTR", "LEFT(", "CONCAT")):
                print("WARNING 对 date_id 做了算术/字符串处理，应改为 JOIN dim_date")

    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
