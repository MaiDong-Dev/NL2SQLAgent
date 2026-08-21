# =============================================================================
# 【客户端层】Elasticsearch 客户端管理器（ESClientManager）
# 作用：封装 Elasticsearch 异步客户端（AsyncElasticsearch）的连接与生命周期管理，
#       为「字段取值全文检索」提供底层连接能力。
#
# 组合关系（见 docs/architecture-01/02）：
#   - 依赖配置：app_config.es（ESConfig，读取 host/port）
#   - 被 ValueESRepository 使用（通过 es_client_manager.client 获取连接）
#   - 被 core/lifespan.py 在应用启动/关闭时调用 init()/close()
#   - 被 scripts/build_meta_knowledge.py 在元知识构建时调用
#
# 说明：es_client_manager 为模块级单例，全局共享一个连接（ES 连接本身线程安全）。
# =============================================================================

import asyncio
from typing import Optional

from elasticsearch import AsyncElasticsearch

from app.conf.app_config import ESConfig, app_config


class ESClientManager:
    """Elasticsearch 客户端管理器

    职责：
    - 管理与 Elasticsearch 服务的 HTTP 连接
    - 提供连接初始化（init）与资源释放（close）方法
    - 供 ValueESRepository 建立/查询字段取值的倒排索引
    """

    def __init__(self, es_config: ESConfig):
        """初始化管理器

        参数：es_config  ESConfig  ES 连接配置（host/port）
        """
        self.es_config = es_config
        self.client: Optional[AsyncElasticsearch] = None   # 懒加载，init() 后才赋值

    def _get_url(self) -> str:
        """构造 ES 服务的 HTTP 端点地址，如 http://localhost:9200"""
        return f"http://{self.es_config.host}:{self.es_config.port}"

    def init(self):
        """初始化 ES 异步客户端，建立与 ES 服务的连接（在应用启动时调用）"""
        self.client = AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        """关闭 ES 连接，释放底层资源（在应用关闭时调用）"""
        await self.client.close()


# 全局单例：应用启动时通过 lifespan 调用 init() 完成初始化
es_client_manager = ESClientManager(app_config.es)


if __name__ == '__main__':
    # 独立运行时的自测代码：演示 ES 的索引创建、批量写入与查询流程
    es_client_manager.init()

    async def test():
        client = es_client_manager.client

        # 创建索引
        await client.indices.create(
            index="my-books",
            mappings={
                "dynamic": False,
                "properties": {
                    "name": {
                        "type": "text"
                    },
                    "author": {
                        "type": "text"
                    },
                    "release_date": {
                        "type": "date",
                        "format": "yyyy-MM-dd"
                    },
                    "page_count": {
                        "type": "integer"
                    }
                }
            },
        )

        # 插入数据
        await client.bulk(
            operations=[
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Revelation Space",
                    "author": "Alastair Reynolds",
                    "release_date": "2000-03-15",
                    "page_count": 585
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "1984",
                    "author": "George Orwell",
                    "release_date": "1985-06-01",
                    "page_count": 328
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Fahrenheit 451",
                    "author": "Ray Bradbury",
                    "release_date": "1953-10-15",
                    "page_count": 227
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "Brave New World",
                    "author": "Aldous Huxley",
                    "release_date": "1932-06-01",
                    "page_count": 268
                },
                {
                    "index": {
                        "_index": "my-books"
                    }
                },
                {
                    "name": "The Handmaids Tale",
                    "author": "Margaret Atwood",
                    "release_date": "1985-06-01",
                    "page_count": 311
                }
            ],
        )

        # 搜索
        resp = await client.search(
            index="my-books",
            query={
                "match": {
                    "name": "brave"
                }
            },
        )
        print(resp)
        await es_client_manager.close()

    asyncio.run(test())
