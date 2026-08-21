# =============================================================================
# 【向量检索模块】字段召回节点
# 作用：通过 L 大模型扩展关键词 + Qdrant 向量相似度搜索，召回与用户查询
#       语义最相关的数据表字段（ColumnInfo）。
# 上下文传递：
#   - 输入：state["query"]、state["keywords"] → 原始查询 + jieba 关键词
#   - 中间：runtime.context["embedding_client"] → 将关键词转为向量
#   - 中间：runtime.context["column_qdrant_repository"] → 向量检索
#   - 输出：{"retrieved_columns": [...]} → 合并到 state
# 召回策略（两阶段）：
#   阶段1 - LLM 关键词扩展：用 LLM 根据 query 推断回答所需的数据字段名，
#           弥补 jieba 分词无法理解业务语义的不足
#   阶段2 - 向量检索：将扩展后的关键词逐个 Embedding，在 Qdrant 中搜索
#           Top-5 最相似字段，并用 dict 去重（同一字段可能被多个关键词命中）
# 后处理逻辑：
#   - 使用 retrieved_columns_map 按 column_id 去重，保留首次命中的结果
#   - 合并 LLM 扩展关键词和 jieba 关键词，取并集以提高召回率
# =============================================================================

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.prompt.prompt_loader import load_prompt


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段", "status": "running"})

    query = state["query"]
    keywords = state["keywords"]

    embedding_client = runtime.context["embedding_client"]
    column_qdrant_repository = runtime.context["column_qdrant_repository"]

    try:
        # =========================================================================
        # 阶段1：LLM 关键词扩展
        # Prompt 设计意图：
        #   让 LLM 扮演"字段推断专家"，从业务语义角度推断回答该问题所需的字段名，
        #   输出 JSON 数组格式的字段名列表。这些字段名是抽象的业务概念（如"转正状态"、
        #   "订单金额"），而非具体的数据库字段名，用于向量语义匹配。
        # =========================================================================
        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_column_recall"),
            input_variables=["query"],
        )
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # =========================================================================
        # 阶段2：向量检索 + 去重后处理
        # 检索流程：
        #   1. 合并 jieba 关键词 + LLM 扩展关键词，取并集
        #   2. 对每个关键词做 Embedding，在 Qdrant 中搜索 Top-5 相似字段
        #   3. 用 dict 按 column_id 去重，同一字段只保留一条
        # 为什么用 dict 去重而不是 set？
        #   ColumnInfo 是 dataclass，直接放 set 可能因为 hash 不稳定导致重复，
        #   用 column_id 作为 key 可以精确去重
        # =========================================================================
        retrieved_columns_map: dict[str, ColumnInfo] = {}

        keywords = list(set(keywords + result))
        logger.info(f"召回字段信息扩展关键词：{keywords}")
        for keyword in keywords:
            # 将关键词转为向量（Embedding）
            embedding = await embedding_client.aembed_query(keyword)
            # 在 Qdrant 中搜索最相似的 Top-5 字段
            payloads: list[ColumnInfo] = await column_qdrant_repository.search(
                embedding
            )
            for payload in payloads:
                column_id = payload.id
                if column_id not in retrieved_columns_map:
                    retrieved_columns_map[column_id] = payload

        retrieved_columns = list(retrieved_columns_map.values())

        writer({"type": "progress", "step": "召回字段", "status": "success"})
        logger.info(f"召回字段信息：{list(retrieved_columns_map.keys())}")
        return {"retrieved_columns": retrieved_columns}
    except Exception as e:
        writer({"type": "progress", "step": "召回字段", "status": "error"})
        logger.error(f"召回字段信息失败: {str(e)}")
        raise