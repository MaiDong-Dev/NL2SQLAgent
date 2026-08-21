# =============================================================================
# 【向量检索模块】指标向量库 Repository
# 作用：封装 Qdrant 向量数据库的 CRUD 操作，专门管理「业务指标」的向量索引。
#       存储指标名、指标描述、别名三种文本的 Embedding 向量，支持通过向量相似度
#       搜索召回与用户查询语义最相关的业务指标。
# 上下文传递：被 DataAgentContext 携带，在 recall_metric 节点中注入使用。
# =============================================================================

from dataclasses import asdict

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

from app.conf.app_config import app_config
from app.entities.metric_info import MetricInfo


class MetricQdrantRepository:
    """指标向量索引仓库
    
    职责：
    - 管理名为 'data-agent-metric' 的 Qdrant Collection
    - 将指标的 Embedding 向量写入 Qdrant，为后续语义检索建立索引
    - 提供向量相似度搜索接口，召回与查询关键词最相关的 Top-K 指标
    
    向量化策略（多维度覆盖）：
    每个指标会生成多条向量记录，分别对应：
      1. 指标名（如 "转正率"）           → 精确匹配
      2. 指标描述（如 "实习生转正通过率"） → 语义匹配
      3. 指标别名（如 ["转正比例", "转正通过率"]） → 别名覆盖
    这样设计是为了从多个语义角度覆盖同一指标，提高召回率。
    
    召回策略：
    - 距离度量：余弦相似度（Cosine Distance），适合文本语义相似度比较
    - 分数阈值：score_threshold=0.6，过滤低相关度的噪音结果
    - 返回数量：limit=5，每个关键词最多召回 5 个最相关指标
    """

    # Qdrant 中的 Collection 名称，用于隔离不同业务的数据
    collection_name = 'data-agent-metric'

    def __init__(self, client: AsyncQdrantClient):
        self.client = client

    async def ensure_collection(self):
        """确保 Collection 存在，不存在则自动创建
        
        创建参数说明：
        - vectors_config: 指定向量维度（从配置读取 embedding_size），
          维度必须与 Embedding 模型输出维度一致
        - distance: 使用 Cosine 距离，值域 [0, 2]，0 表示完全相同
        """
        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(self.collection_name,
                                                vectors_config=VectorParams(size=app_config.qdrant.embedding_size,
                                                                            distance=Distance.COSINE))

    async def upsert(self, ids: list[str], embeddings: list[list[float]], payloads: list[MetricInfo],
                     batch_size: int = 20):
        """批量写入/更新向量数据（支持分批上传）
        
        参数：
        - ids: 每条记录的唯一标识，用于后续覆盖更新
        - embeddings: 文本对应的 Embedding 向量列表
        - payloads: 每条向量附带的指标元数据（MetricInfo），
          检索命中后可直接还原为业务对象
        - batch_size: 分批大小，避免单次上传数据量过大
        """
        zipped = list(zip(ids, embeddings, payloads))
        for i in range(0, len(zipped), batch_size):
            batch = zipped[i:i + batch_size]
            batch_points = [PointStruct(id=id, vector=embedding, payload=asdict(payload)) for id, embedding, payload in
                            batch]
            await self.client.upsert(collection_name=self.collection_name, points=batch_points)

    async def search(self, embedding: list[float], score_threshold: float = 0.6, limit: int = 5) -> list[MetricInfo]:
        """向量相似度搜索——根据查询向量召回最相关的指标
        
        参数：
        - embedding: 用户查询关键词的 Embedding 向量
        - score_threshold: 相似度阈值（0.6），低于此分数的结果视为不相关，直接丢弃
        - limit: 返回的最大结果数（Top-5）
        
        返回：
        - 将 Qdrant 返回的 payload 反序列化为 MetricInfo 实体列表
        """
        result = await self.client.query_points(collection_name=self.collection_name,
                                                query=embedding,
                                                score_threshold=score_threshold,
                                                limit=limit)
        return [MetricInfo(**point.payload) for point in result.points]