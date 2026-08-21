# =============================================================================
# 【核心层】FastAPI 生命周期管理（lifespan）
# 作用：管理 FastAPI 应用启动/关闭时的资源初始化与释放，是「基础设施依赖」
#       的统一装配点。
#
# 组合关系（见 docs/architecture-01-package-dependency 图1）：
#   lifespan --> embedding/qdrant/es/mysql 四大客户端管理器
#
# 生命周期流程：
#   启动前（yield 之前）：
#     1. embedding_client_manager.init()   初始化 Embedding 客户端
#     2. qdrant_client_manager.init()      初始化 Qdrant 向量库客户端
#     3. es_client_manager.init()          初始化 Elasticsearch 客户端
#     4. meta_mysql_client_manager.init()  初始化元数据库连接
#     5. dw_mysql_client_manager.init()    初始化数据仓库连接
#   关闭前（yield 之后）：
#     依次 close() 释放 qdrant/es/meta/dw 连接资源
#
# 说明：
#   - lifespan 使用 asynccontextmanager 装饰，作为 FastAPI 的 lifespan 参数传入
#   - 注意：此处只初始化连接，不执行元知识构建（build 由独立脚本或启动逻辑触发）
#   - embedding 客户端无 close 方法（HTTP 无状态，无需显式释放）
# =============================================================================

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用生命周期上下文管理器

    参数：app  FastAPI  应用实例

    说明：yield 之前的代码在应用启动时执行（资源初始化），
         yield 之后的代码在应用关闭时执行（资源释放）。
    """
    # ========== 应用启动前：初始化所有客户端连接 ==========
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    yield
    # ========== 应用关闭前：释放所有客户端连接 ==========
    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
