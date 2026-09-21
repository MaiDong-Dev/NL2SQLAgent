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
#   阶段2 - 向量检索：将扩展后的关键词逐个 Embedding，在 Qdrant 中检索
#           Top-N 最相似字段，按字段去重后，再用「相对本次最高分」的阈值降噪
#           （同一字段在库中有 name/description/alias 多条向量，需过采样后去重）
# 后处理逻辑：
#   - 使用 retrieved_columns_map 按 column_id 去重，保留首次命中的结果
#   - 合并 LLM 扩展关键词和 jieba 关键词，取并集以提高召回率
# =============================================================================

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.llm import llm
from server.agent.state import DataAgentState
from server.conf.app_config import app_config
from server.core.log import logger
from server.entities.column_info import ColumnInfo
from server.prompt.prompt_loader import load_prompt

# 主外键角色：这类字段不做相对阈值过滤，见阶段2 注释
KEY_ROLES = {"primary_key", "foreign_key"}


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
        # 阶段2：向量检索 + 去重 + 相对阈值降噪
        # 检索流程：
        #   1. 合并 jieba 关键词 + LLM 扩展关键词，取并集
        #   2. 对每个关键词做 Embedding，在 Qdrant 中检索 Top-N 相似字段
        #      （N = 配置 recall.column_search_limit，需过采样：同一字段在库中有
        #        name/description/alias 多条向量，会重复占用名额）
        #   3. 按 column_id 去重，同一字段只保留「最高相似度」
        #   4. 相对阈值过滤：只保留 score >= 本次最高分 × ratio 的字段
        #
        # 为什么用「相对阈值」而不是绝对阈值？
        #   实测正确字段与噪音字段的绝对分数高度交错：问「销售额」时 order_amount
        #   最高 1.000，而噪音项 order_quantity 也能到 0.815；问「客单价」时
        #   order_amount 仅 0.704、order_quantity 0.627。任何固定的绝对阈值都会
        #   要么错杀正确项、要么放过噪音。改为相对本次最高分后，阈值随问句自适应。
        #
        # 被阈值裁掉的字段会丢吗？
        #   不会：主外键（如 region_id / order_id）由 merge 节点确定性补全，
        #   时间维表字段由「时间维度补全」兜底，二者都不依赖向量召回。
        # =========================================================================
        candidates: dict[str, tuple[ColumnInfo, float]] = {}

        keywords = list(set(keywords + result))
        logger.info(f"召回字段信息扩展关键词：{keywords}")
        for keyword in keywords:
            # 将关键词转为向量（Embedding）
            embedding = await embedding_client.aembed_query(keyword)
            # 在 Qdrant 中检索最相似的 Top-N 字段（含相似度分数）
            scored_columns: list[tuple[ColumnInfo, float]] = await column_qdrant_repository.search(embedding)

            # 阈值按「每个关键词」独立计算，而不是全句统一：
            # 关键词覆盖问句的不同部分（维度词"华为品牌" vs 度量词"销售数量"），
            # 它们的绝对分数不可比。若用全局最高分做阈值，维度词得分 1.000 会把
            # 度量词对应的 order_quantity（约 0.85）整体压制掉 —— 实测过：
            # "华为品牌商品的销售数量" 因此召不回 order_quantity，
            # LLM 只能退化成 COUNT(order_id)，生成错误 SQL。
            keyword_best_score = max((score for _, score in scored_columns), default=0.0)
            score_threshold = keyword_best_score * app_config.recall.column_score_ratio
            for payload, score in scored_columns:
                # 主外键不做相对阈值过滤：语义弱、分数普遍偏低，但 JOIN 必需，
                # 用相对阈值会把它们误裁（问「各大区销售额」时 region_id 仅 0.693，
                # 而 region_name 是 1.000），故键列沿用较低的绝对阈值。
                if score < (app_config.recall.column_key_score_threshold
                            if payload.role in KEY_ROLES else score_threshold):
                    continue
                existing = candidates.get(payload.id)
                if existing is None or score > existing[1]:
                    candidates[payload.id] = (payload, score)

        retrieved_columns = [column for column, _ in candidates.values()]

        writer({"type": "progress", "step": "召回字段", "status": "success"})
        logger.info(f"召回字段信息：{[column.id for column in retrieved_columns]}（候选 {len(candidates)} 个字段）")
        return {"retrieved_columns": retrieved_columns}
    except Exception as e:
        writer({"type": "progress", "step": "召回字段", "status": "error"})
        logger.error(f"召回字段信息失败: {str(e)}")
        raise