# =============================================================================
# 【脚本入口】元知识构建脚本（build_meta_knowledge）
# 作用：提供命令行方式独立构建元知识库，无需启动 FastAPI 服务即可将配置文件
#       （meta_config.yaml）中的表/字段/指标定义同步到三大存储引擎。
#
# 组合关系（见 docs/architecture-01-package-dependency 图1）：
#   scripts --> services/meta_knowledge_service --> 三大存储 Repository
#
# 使用方式：
#   python -m app.scripts.build_meta_knowledge -c /path/to/meta_config.yaml
#
# 与 core/lifespan.py 的区别：
#   - lifespan：在 Web 服务启动时初始化「客户端连接」（不含元知识构建）
#   - 本脚本：独立进程初始化连接 + 执行完整的元知识构建流程
# =============================================================================

import asyncio
from argparse import ArgumentParser
from pathlib import Path

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    meta_mysql_client_manager,
    dw_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.meta_knowledge_service import MetaKnowledgeService


async def build(config_path: Path):
    """执行元知识库构建

    参数：config_path  元知识配置文件（meta_config.yaml）路径

    流程：
    1. 初始化五大客户端（MySQL Meta/DW、Qdrant、Embedding、ES）
    2. 创建各存储引擎的 Repository 实例
    3. 装配 MetaKnowledgeService 并调用 build() 执行构建
    4. 关闭所有客户端连接，释放资源
    """
    meta_mysql_client_manager.init()        # 初始化元数据 MySQL 客户端
    dw_mysql_client_manager.init()          # 初始化数据仓库 MySQL 客户端
    qdrant_client_manager.init()            # 初始化 Qdrant 向量库客户端
    embedding_client_manager.init()         # 初始化 Embedding 客户端
    es_client_manager.init()                # 初始化 Elasticsearch 客户端

    # 同时打开两个 MySQL 会话（元数据库 + 数据仓库）
    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        meta_mysql_repository = MetaMySQLRepository(meta_session)          # 元数据库 Repository
        dw_mysql_repository = DWMySQLRepository(dw_session)                # 数据仓库 Repository
        column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)   # 字段向量库 Repository
        embedding_client = embedding_client_manager.client                 # Embedding 客户端
        value_es_repository = ValueESRepository(es_client_manager.client)  # 取值全文检索 Repository
        metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)  # 指标向量库 Repository

        # 装配元知识构建服务（聚合全部依赖）
        mete_knowledge_service = MetaKnowledgeService(
            meta_mysql_repository=meta_mysql_repository,
            dw_mysql_repository=dw_mysql_repository,
            column_qdrant_repository=column_qdrant_repository,
            embedding_client=embedding_client,
            value_es_repository=value_es_repository,
            metric_qdrant_repository=metric_qdrant_repository,
        )
        # 执行元知识构建（同步到 Meta MySQL / Qdrant / ES）
        await mete_knowledge_service.build(config_path)

    # 释放所有客户端连接
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()


if __name__ == "__main__":
    # 解析命令行参数：-c/--conf 指定元知识配置文件路径
    parser = ArgumentParser(description="构建 NL2SQL 元知识库")
    parser.add_argument("-c", "--conf", required=True, help="元知识配置文件路径（meta_config.yaml）")  # 配置路径参数
    args = parser.parse_args()

    # 获取配置文件路径并执行构建
    config_path = Path(args.conf)
    asyncio.run(build(config_path))
