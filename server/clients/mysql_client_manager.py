# =============================================================================
# 【客户端层】MySQL 客户端管理器（MysqlClientManager）
# 作用：封装 SQLAlchemy 异步引擎（AsyncEngine）与会话工厂（async_sessionmaker），
#       为元数据库（Meta）与数据仓库（DW）提供数据库连接与异步会话管理。
#
# 组合关系（见 docs/architecture-01/02/05）：
#   - 依赖配置：app_config.db_meta / app_config.db_dw（DBConfig）
#   - 创建两个全局单例：
#     * meta_mysql_client_manager —— 连接元数据库（存储表/字段/指标定义）
#     * dw_mysql_client_manager   —— 连接数据仓库（存储业务数据，执行查询）
#   - 被 MetaMySQLRepository / DWMySQLRepository 通过 session_factory 获取会话
#   - 被 server/core/lifespan.py 在应用启动/关闭时调用 init()/close()
#
# 设计意图：
#   - 元数据库与数据仓库分离：元数据（Schema 知识）与业务数据（实际记录）物理隔离
#   - 会话工厂模式：每次请求通过 session_factory() 创建独立会话，保证请求隔离
# =============================================================================

import asyncio
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker

from server.conf.app_config import DBConfig, app_config


class MysqlClientManager:
    """MySQL 客户端管理器

    职责：
    - 创建并管理 SQLAlchemy 异步引擎（AsyncEngine）
    - 提供异步会话工厂（async_sessionmaker），供 Repository 获取会话
    - 提供连接初始化（init）与资源释放（close）方法
    """

    def __init__(self, db_config: DBConfig):
        """初始化管理器

        参数：db_config  DBConfig  数据库连接配置（host/port/user/password/database）
        """
        self.db_config = db_config
        self.engine: Optional[AsyncEngine] = None       # 懒加载，init() 后才赋值
        self.session_factory = None                      # 懒加载，init() 后才赋值

    def _get_url(self) -> str:
        """构造 SQLAlchemy 异步连接串

        使用 asyncmy 驱动 + MySQL 协议，强制 utf8mb4 字符集（支持 emoji 等 4 字节字符）
        格式：mysql+asyncmy://user:password@host:port/database?charset=utf8mb4
        """
        return f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}?charset=utf8mb4"

    def init(self):
        """初始化异步引擎与会话工厂（在应用启动时调用）

        引擎参数说明：
        - pool_size=10：      连接池大小（最多同时 10 个连接）
        - pool_pre_ping=True：每次取连接前先 ping 探测，避免使用失效连接
        会话工厂参数说明：
        - autoflush=True：         自动 flush（查询前自动同步未提交的变更）
        - expire_on_commit=False： 提交后不使对象过期（便于提交后继续访问属性）
        - autobegin=True：         自动开启事务
        """
        self.engine = create_async_engine(url=self._get_url(),
                                          pool_size=10,
                                          pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine,
                                                  autoflush=True,
                                                  expire_on_commit=False,
                                                  autobegin=True)

    async def close(self):
        """关闭引擎，释放所有数据库连接（在应用关闭时调用）"""
        await self.engine.dispose()


# 数据仓库客户端单例（连接业务数据仓库）
dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
# 元数据库客户端单例（连接元数据数据库）
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)


if __name__ == '__main__':
    # 独立运行时的自测代码
    dw_mysql_client_manager.init()

    async def test():
        async with dw_mysql_client_manager.session_factory() as session:
            result = await session.execute(text("select * from dim_customer limit 10"))
            rows = result.fetchall()
            print(rows)

    asyncio.run(test())
