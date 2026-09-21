# =============================================================================
# 【入口层】FastAPI 依赖注入（dependencies）
# 作用：定义 FastAPI 的依赖注入函数，将「客户端管理器单例」装配为「Repository
#       实例」和「QueryService 实例」，实现基础设施依赖的自动组装。
#
# 组合关系（见 docs/architecture-05-fastapi-di-chain 图5）：
#   HTTP 请求 → query_router → get_query_service() → 逐级注入各 Repository
#      get_query_service ──┬─ get_embedding_client      → embedding_client_manager
#                          ├─ get_column_qdrant_repository → qdrant_client_manager
#                          ├─ get_value_es_repository      → es_client_manager
#                          ├─ get_metric_qdrant_repository → qdrant_client_manager
#                          ├─ get_meta_mysql_repository ── get_meta_session → meta_mysql_client_manager
#                          └─ get_dw_mysql_repository ─── get_dw_session  → dw_mysql_client_manager
#
# 设计意图：
#   - 依赖注入（DI）将「对象创建」与「对象使用」解耦，路由层无需关心依赖细节
#   - 会话（session）通过 get_meta_session/get_dw_session 以 yield 方式提供，
#     请求结束后自动关闭，保证连接正确归还连接池（请求级隔离）
#   - Repository 依赖 session（生命周期短），而 qdrant/es/embedding 客户端
#     依赖单例（生命周期长），二者通过不同的注入函数区分管理
# =============================================================================

from fastapi import Depends
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from sqlalchemy.ext.asyncio import AsyncSession

from server.clients.embedding_client_manager import embedding_client_manager
from server.clients.es_client_manager import es_client_manager
from server.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from server.clients.qdrant_client_manager import qdrant_client_manager
from server.repositories.es.value_es_repository import ValueESRepository
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from server.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from server.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from server.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from server.services.query_service import QueryService


async def get_meta_session():
    """依赖注入：提供元数据库（Meta DB）的异步会话

    使用 async with 确保请求结束后会话自动关闭，连接归还连接池
    """
    async with meta_mysql_client_manager.session_factory() as session:
        yield session


async def get_dw_session():
    """依赖注入：提供数据仓库（DW）的异步会话

    使用 async with 确保请求结束后会话自动关闭，连接归还连接池
    """
    async with dw_mysql_client_manager.session_factory() as session:
        yield session


async def get_embedding_client() -> HuggingFaceEndpointEmbeddings:
    """依赖注入：提供 Embedding 客户端（单例）"""
    return embedding_client_manager.client


async def get_column_qdrant_repository() -> ColumnQdrantRepository:
    """依赖注入：创建字段向量库 Repository（每次请求新建，复用单例客户端）"""
    return ColumnQdrantRepository(qdrant_client_manager.client)


async def get_value_es_repository() -> ValueESRepository:
    """依赖注入：创建字段取值全文检索 Repository"""
    return ValueESRepository(es_client_manager.client)


async def get_metric_qdrant_repository() -> MetricQdrantRepository:
    """依赖注入：创建指标向量库 Repository"""
    return MetricQdrantRepository(qdrant_client_manager.client)


async def get_meta_mysql_repository(session: AsyncSession = Depends(get_meta_session)) -> MetaMySQLRepository:
    """依赖注入：创建元数据库 Repository（绑定当前请求的会话）"""
    return MetaMySQLRepository(session)


async def get_dw_mysql_repository(session: AsyncSession = Depends(get_dw_session)) -> DWMySQLRepository:
    """依赖注入：创建数据仓库 Repository（绑定当前请求的会话）"""
    return DWMySQLRepository(session)


async def get_query_service(
        embedding_client: HuggingFaceEndpointEmbeddings = Depends(get_embedding_client),
        column_qdrant_repository: ColumnQdrantRepository = Depends(get_column_qdrant_repository),
        value_es_repository: ValueESRepository = Depends(get_value_es_repository),
        metric_qdrant_repository: MetricQdrantRepository = Depends(get_metric_qdrant_repository),
        meta_mysql_repository: MetaMySQLRepository = Depends(get_meta_mysql_repository),
        dw_mysql_repository: DWMySQLRepository = Depends(get_dw_mysql_repository)
) -> QueryService:
    """依赖注入：装配 QueryService（聚合全部基础设施依赖）

    QueryService 是查询的统一入口，需要 6 个依赖：
    - embedding_client：         文本向量化
    - column_qdrant_repository： 字段向量召回
    - value_es_repository：      字段取值全文召回
    - metric_qdrant_repository： 指标向量召回
    - meta_mysql_repository：    元数据查询补全
    - dw_mysql_repository：      SQL 验证与执行
    """
    return QueryService(
        embedding_client=embedding_client,
        column_qdrant_repository=column_qdrant_repository,
        value_es_repository=value_es_repository,
        metric_qdrant_repository=metric_qdrant_repository,
        meta_mysql_repository=meta_mysql_repository,
        dw_mysql_repository=dw_mysql_repository
    )
