# =============================================================================
# 【运维脚本】清空并重建元知识库
# 作用：数据源发生变化（DW 表结构/数据量变更、meta_config.yaml 增删表字段）后，
#       把旧的元知识彻底清掉再全量重建，避免「只增不删」留下脏数据。
#
# 为什么要先清再建？
#   meta_builder 的构建流程对 MySQL 是纯 INSERT（无 ON DUPLICATE KEY UPDATE），
#   Qdrant 每条向量又用随机 uuid4，因此重复构建会：
#     1. MySQL 报 1062 Duplicate entry，整个事务回滚；
#     2. 即便绕过，Qdrant 里向量也会累积翻倍，干扰检索分数分布。
#   所以「重建 = 先清三处存储 + 再跑一次构建」是目前唯一干净的做法。
#
# 清理范围（均可由本脚本重新生成，无需备份）：
#   1. Meta MySQL：table_info / column_info / metric_info / column_metric 四张表清空
#   2. Qdrant：data-agent-column、data-agent-metric 两个 Collection 删除
#   3. ES：字段取值索引（app_config.es.index_name）删除
#
# 使用方式：
#   python -m scripts.rebuild_meta -c conf/meta_config.yaml
# =============================================================================

import asyncio
from argparse import ArgumentParser
from pathlib import Path

from sqlalchemy import text

from meta_builder.services.meta_knowledge_service import MetaKnowledgeService
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

# 清空顺序：先删关联表，再删主表（避免外键/业务约束）
META_TABLES = ["column_metric", "metric_info", "column_info", "table_info"]

# 需要删除的 Qdrant Collection
QDRANT_COLLECTIONS = [
    ColumnQdrantRepository.collection_name,   # data-agent-column
    MetricQdrantRepository.collection_name,   # data-agent-metric
]


async def clean_and_build(config_path: Path):
    """清空三处存储后重新构建元知识库"""
    # ========== 初始化客户端 ==========
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()

    # ========== 步骤1：清空 Meta MySQL 四张表 ==========
    async with meta_mysql_client_manager.session_factory() as meta_session:
        for table in META_TABLES:
            result = await meta_session.execute(text(f"DELETE FROM {table}"))
            print(f"[clean] meta.{table}: 删除 {result.rowcount} 行")
        await meta_session.commit()

    # ========== 步骤2：删除 Qdrant 两个 Collection ==========
    qdrant_client = qdrant_client_manager.client
    for collection in QDRANT_COLLECTIONS:
        if await qdrant_client.collection_exists(collection):
            await qdrant_client.delete_collection(collection)
            print(f"[clean] qdrant.{collection}: 已删除")
        else:
            print(f"[clean] qdrant.{collection}: 不存在，跳过")

    # ========== 步骤3：删除 ES 字段取值索引 ==========
    es_client = es_client_manager.client
    index_name = ValueESRepository.index_name
    if await es_client.indices.exists(index=index_name):
        await es_client.indices.delete(index=index_name)
        print(f"[clean] es.{index_name}: 已删除")
    else:
        print(f"[clean] es.{index_name}: 不存在，跳过")

    # ========== 步骤4：重新构建（与 build_meta_knowledge 完全一致）==========
    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        service = MetaKnowledgeService(
            meta_mysql_repository=MetaMySQLRepository(meta_session),
            dw_mysql_repository=DWMySQLRepository(dw_session),
            column_qdrant_repository=ColumnQdrantRepository(qdrant_client),
            embedding_client=embedding_client_manager.client,
            value_es_repository=ValueESRepository(es_client),
            metric_qdrant_repository=MetricQdrantRepository(qdrant_client),
        )
        await service.build(config_path)
        print(f"[build] 元知识库重建完成：{config_path}")

    # ========== 释放连接 ==========
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()


if __name__ == "__main__":
    parser = ArgumentParser(description="清空并重建 NL2SQL 元知识库")
    parser.add_argument("-c", "--conf", required=True, help="元知识配置文件路径（meta_config.yaml）")
    args = parser.parse_args()

    asyncio.run(clean_and_build(Path(args.conf)))
