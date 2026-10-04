# =============================================================================
# 【客户端层】包级导出
# 作用：统一导出 5 个中间件客户端单例（MySQL×2 / Qdrant / ES / Embedding），
#       调用方写 `from server.clients import dw_mysql_client_manager` 即可。
#
# 说明：这些是**懒连接**单例——import 时只构造管理器对象，不建立实际连接，
#       真正连接发生在 init()。所以在这里导入不会触发任何网络行为。
# =============================================================================

from server.clients.embedding_client_manager import embedding_client_manager
from server.clients.es_client_manager import es_client_manager
from server.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from server.clients.qdrant_client_manager import qdrant_client_manager

__all__ = [
    "embedding_client_manager",
    "es_client_manager",
    "dw_mysql_client_manager",
    "meta_mysql_client_manager",
    "qdrant_client_manager",
]
