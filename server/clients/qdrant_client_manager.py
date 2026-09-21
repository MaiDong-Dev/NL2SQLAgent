# =============================================================================
# 【客户端层】Qdrant 客户端管理器（QdrantClientManager）
# 作用：封装 Qdrant 异步客户端（AsyncQdrantClient）的连接与生命周期管理，
#       为「字段/指标向量检索」提供底层连接能力。
#
# 组合关系（见 docs/architecture-01/02）：
#   - 依赖配置：app_config.qdrant（QdrantConfig，读取 host/port/embedding_size）
#   - 被 ColumnQdrantRepository / MetricQdrantRepository 使用
#   - 被 server/core/lifespan.py 在应用启动/关闭时调用 init()/close()
#   - 被 meta_builder/scripts/build_meta_knowledge.py 在元知识构建时调用
#
# 说明：qdrant_client_manager 为模块级单例，全局共享一个连接。
# =============================================================================

import asyncio
import random
from typing import Optional

from qdrant_client import AsyncQdrantClient, models

from server.conf.app_config import QdrantConfig, app_config


class QdrantClientManager:
    """Qdrant 客户端管理器

    职责：
    - 管理与 Qdrant 向量数据库的连接
    - 提供连接初始化（init）与资源释放（close）方法
    - 供字段/指标 Repository 进行向量写入与相似度检索
    """

    def __init__(self, qdrant_config: QdrantConfig):
        """初始化管理器

        参数：qdrant_config  QdrantConfig  Qdrant 连接配置（host/port）
        """
        self.qdrant_config = qdrant_config
        self.client: Optional[AsyncQdrantClient] = None   # 懒加载，init() 后才赋值

    def _get_url(self) -> str:
        """构造 Qdrant 服务的 HTTP 端点地址，如 http://localhost:6333"""
        return f"http://{self.qdrant_config.host}:{self.qdrant_config.port}"

    def init(self):
        """初始化 Qdrant 异步客户端，建立连接（在应用启动时调用）"""
        self.client = AsyncQdrantClient(url=self._get_url())

    async def close(self):
        """关闭 Qdrant 连接，释放底层资源（在应用关闭时调用）"""
        await self.client.close()


# 全局单例：应用启动时通过 lifespan 调用 init() 完成初始化
qdrant_client_manager = QdrantClientManager(app_config.qdrant)


if __name__ == '__main__':
    # 独立运行时的自测代码：演示 Qdrant 的 collection 创建、向量写入与查询
    qdrant_client_manager.init()

    async def test():
        client = qdrant_client_manager.client
        # 创建 collection（若不存在），指定向量维度与余弦距离
        if not await client.collection_exists("my_collection"):
            await client.create_collection(
                collection_name="my_collection",
                vectors_config=models.VectorParams(size=10, distance=models.Distance.COSINE),
            )

        # 批量写入 100 条随机向量
        await client.upsert(
            collection_name="my_collection",
            points=[
                models.PointStruct(
                    id=i,
                    vector=[random.random() for _ in range(10)],
                )
                for i in range(100)
            ],
        )

        # 查询：随机向量检索 Top-10，相似度阈值 0.8
        res = await client.query_points(
            collection_name="my_collection",
            query=[random.random() for _ in range(10)],  # type: ignore
            limit=10,
            score_threshold=0.8
        )

        print(res)

    asyncio.run(test())
