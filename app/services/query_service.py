# =============================================================================
# 【查询服务】QueryService
# 作用：作为 NL2SQL 查询的统一入口，负责：
#       1. 组装 DataAgentContext（注入所有基础设施依赖）
#       2. 创建 DataAgentState（初始化用户查询）
#       3. 调用 LangGraph 工作流，以 SSE 流式方式返回结果
# 上下文传递：
#   - 输入：用户查询字符串（query）
#   - 内部：组装 Context 和 State，注入到 graph.astream()
#   - 输出：SSE（Server-Sent Events）格式的流式响应
# 设计意图：
#   - 每次查询都创建新的 Context 和 State，确保请求隔离
#   - 使用 SSE 流式返回，前端可以实时展示处理进度
# =============================================================================

import json

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    """NL2SQL 查询服务
    
    职责：
    - 接收用户自然语言查询
    - 组装 Agent 所需的上下文和状态
    - 驱动 LangGraph 工作流执行
    - 以 SSE 流式方式返回处理进度和最终结果
    """
    def __init__(self,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueESRepository,
                 metric_qdrant_repository: MetricQdrantRepository,
                 meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    async def query(self, query: str):
        """执行 NL2SQL 查询
        
        参数：
        - query: 用户自然语言查询，如 "统计去年各地区的销售总额"
        
        返回：
        - SSE 流式生成器，每个 chunk 格式为 "data: {json}\n\n"
        
        处理流程：
        1. 组装 DataAgentContext：注入所有基础设施依赖
        2. 创建 DataAgentState：初始化用户查询
        3. 调用 LangGraph 工作流：graph.astream() 异步执行整个 Pipeline
        4. 流式输出：将每个节点的输出包装为 SSE 格式返回
        """
        # 为每次查询创建独立的 Context（确保请求隔离）
        context = DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository
        )
        # 创建初始 State（只包含用户查询，其他字段由后续节点填充）
        state = DataAgentState(query=query)
        try:
            # 执行 LangGraph 工作流，stream_mode="custom" 使用自定义流式输出
            # 每个节点通过 runtime.stream_writer 写入的数据会作为 chunk 返回
            async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n" # SSE格式发送数据
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False, default=str)}\n\n"