# =============================================================================
# 【Agent 上下文定义】DataAgentContext
# 作用：定义 LangGraph 工作流中各节点共享的「基础设施依赖」（数据库连接、
#       Embedding 客户端、向量库 Repository 等），与 State 不同：
#       - State：存储业务数据，随工作流流转而变化
#       - Context：存储基础设施，全程不变，随图编译时注入
# 上下文传递逻辑：
#   - Context 在 graph.astream(context=context) 时传入
#   - 每个节点通过 runtime.context 获取，无需显式传参
#   - 这样设计避免了每个节点都需要 __init__ 注入依赖的繁琐
# =============================================================================

from typing import TypedDict

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class DataAgentContext(TypedDict):
    """Agent 基础设施上下文——包含所有外部服务依赖
    
    各字段用途：
    - embedding_client:         将文本转为向量，供向量召回节点使用
    - column_qdrant_repository: 字段向量库，通过语义相似度召回相关字段
    - value_es_repository:      字段取值 ES 索引，通过全文检索召回字段值
    - metric_qdrant_repository: 指标向量库，通过语义相似度召回相关指标
    - meta_mysql_repository:    元数据库（表/字段/指标定义），供 merge 节点查询
    - dw_mysql_repository:      数据仓库，供 SQL 验证、执行和元数据查询
    """
    embedding_client: HuggingFaceEndpointEmbeddings
    column_qdrant_repository: ColumnQdrantRepository
    value_es_repository: ValueESRepository
    metric_qdrant_repository: MetricQdrantRepository
    meta_mysql_repository: MetaMySQLRepository
    dw_mysql_repository: DWMySQLRepository