# =============================================================================
# 【向量检索模块】指标召回节点
# 作用：通过 LLM 扩展关键词 + Qdrant 向量相似度搜索，召回与用户查询
#       语义最相关的业务指标（MetricInfo），如"转正率"、"GMV"、"留存率"等。
# 上下文传递：
#   - 输入：state["query"]、state["keywords"] → 原始查询 + jieba 关键词
#   - 中间：runtime.context["embedding_client"] → 将关键词转为向量
#   - 中间：runtime.context["metric_qdrant_repository"] → 向量检索
#   - 输出：{"retrieved_metrics": [...]} → 合并到 state
# 召回策略（两阶段）：
#   阶段1 - LLM 关键词扩展：用 LLM 从 query 中推断"指标意图"（如"转正情况"
#           → "转正率"/"转正人数"），并补充同义词（如"GMV"→"成交额"）
#   阶段2 - 向量检索：将扩展后的指标概念关键词逐个 Embedding，在 Qdrant 中
#           搜索 Top-5 最相似指标，并用 dict 去重
# 后处理逻辑：
#   - 使用 retrieved_metrics_map 按 metric_id 去重
#   - 合并 LLM 扩展关键词和 jieba 关键词，取并集以提高召回率
# =============================================================================

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo
from app.prompt.prompt_loader import load_prompt


async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回指标", "status": "running"})

    query = state["query"]
    keywords = state["keywords"]

    embedding_client = runtime.context['embedding_client']
    metric_qdrant_repository = runtime.context['metric_qdrant_repository']

    try:
        # =========================================================================
        # 阶段1：LLM 关键词扩展
        # Prompt 设计意图：
        #   让 LLM 扮演"指标语义扩展专家"，从 query 中识别度量目标并生成
        #   指标检索关键词（如"转正情况"→"转正率/转正人数/转正比例"），
        #   同时补充同义词和英文缩写（如"GMV"/"成交额"）
        # =========================================================================
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_metric_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # =========================================================================
        # 阶段2：向量检索 + 去重后处理
        # 检索流程：
        #   1. 合并 jieba 关键词 + LLM 扩展关键词，取并集
        #   2. 对每个关键词做 Embedding，在 Qdrant 中搜索 Top-5 相似指标
        #   3. 用 dict 按 metric_id 去重
        # =========================================================================
        retrieved_metrics_map: dict[str, MetricInfo] = {}

        keywords = list(set(keywords + result))
        logger.info(f"召回指标信息扩展关键词：{keywords}")
        for keyword in keywords:
            # 将关键词转为向量（Embedding）
            embedding = await embedding_client.aembed_query(keyword)
            # 在 Qdrant 中搜索最相似的 Top-5 指标
            payloads: list[MetricInfo] = await metric_qdrant_repository.search(embedding)
            for payload in payloads:
                metric_id = payload.id
                if metric_id not in retrieved_metrics_map:
                    retrieved_metrics_map[metric_id] = payload

        retrieved_metrics = list(retrieved_metrics_map.values())

        writer({"type": "progress", "step": "召回指标", "status": "success"})
        logger.info(f"召回指标信息：{list(retrieved_metrics_map.keys())}")
        return {"retrieved_metrics": retrieved_metrics}
    except Exception as e:
        writer({"type": "progress", "step": "召回指标", "status": "error"})
        logger.error(f"召回指标信息失败: {str(e)}")
        raise