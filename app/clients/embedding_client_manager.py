# =============================================================================
# 【向量检索模块】Embedding 客户端管理器
# 作用：封装 HuggingFace Embedding 服务的连接与初始化，为整个 RAG 管线提供
#       文本→向量 的转换能力。所有向量召回节点（字段召回、指标召回）都依赖此客户端。
# 上下文传递：作为全局单例，在应用启动时初始化，通过 DataAgentContext 注入到各个
#             Agent 节点中，避免在每个节点重复创建连接。
# =============================================================================

from typing import Optional

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    """Embedding 服务客户端管理器
    
    职责：
    - 管理与自部署 HuggingFace Embedding 服务的 HTTP 连接
    - 将文本转化为稠密向量（dense vector），供后续向量相似度检索使用
    
    设计说明：
    - 使用 HuggingFaceEndpointEmbeddings 通过 REST API 调用本地/远程 Embedding 模型
    - 模型 URL 格式：http://{host}:{port}，指向 Text Embeddings Inference (TEI) 服务
    """

    def __init__(self, config: EmbeddingConfig):
        # Embedding 客户端实例，使用 Optional 类型以支持懒初始化
        self.client: Optional[HuggingFaceEndpointEmbeddings] = None
        self.config = config

    def _get_url(self) -> str:
        """构造 Embedding 服务的 HTTP 端点地址，如 http://localhost:8081"""
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        """初始化 Embedding 客户端，建立与向量化服务的连接

        说明：HuggingFaceEndpointEmbeddings 的 model 参数实为服务 URL，
        指向自部署的 TEI（Text Embeddings Inference）服务
        """
        self.client = HuggingFaceEndpointEmbeddings(model=self._get_url())


# 全局单例：应用启动时通过 lifespan 调用 init() 完成初始化
embedding_client_manager = EmbeddingClientManager(app_config.embedding)