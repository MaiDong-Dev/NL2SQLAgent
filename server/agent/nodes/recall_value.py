# =============================================================================
# 【数据库交互模块】字段取值召回节点（ES 全文检索）
# 作用：通过 LLM 扩展关键词 + Elasticsearch 全文检索，召回与用户查询
#       相关的字段具体取值（ValueInfo），如状态值、地名、实体名等。
# 上下文传递：
#   - 输入：state["query"]、state["keywords"] → 原始查询 + jieba 关键词
#   - 中间：runtime.context["value_es_repository"] → ES 全文检索
#   - 输出：{"retrieved_values": [...]} → 合并到 state
# 召回策略（两阶段）：
#   阶段1 - LLM 关键词扩展：用 LLM 从 query 中提取"可能出现在字段取值中的关键词"，
#           如"在职"、"实习生"、"转正"等枚举值或实体名
#   阶段2 - ES 全文检索：对每个扩展关键词在 ES 中做 match 查询，
#           利用 IK 分词器实现中文模糊匹配，召回相关字段取值
# 后处理逻辑：
#   - 使用 values_map 按 value_id 去重，保留首次命中的结果
#   - 合并 LLM 扩展关键词和 jieba 关键词，取并集以提高召回率
#
# 为什么字段取值用 ES 全文检索而不是向量检索？
#   取值是离散的枚举值/实体名（如"北京"/"在职"），天然适合倒排索引精确匹配，
#   而向量检索更适合抽象概念（如字段名/指标名）的语义匹配。
# =============================================================================

import asyncio

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.llm import llm
from server.agent.state import DataAgentState
from server.core.log import logger
from server.entities.value_info import ValueInfo
from server.prompt.prompt_loader import load_prompt


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段取值", "status": "running"})

    query = state["query"]
    keywords = state["keywords"]

    value_es_repository = runtime.context["value_es_repository"]

    try:
        # =========================================================================
        # 阶段1：LLM 关键词扩展
        # Prompt 设计意图：
        #   让 LLM 扮演"业务语义解析专家"，从 query 中提取值级关键词（枚举值、
        #   实体名、时间语义词等），用于 ES 全文检索匹配字段取值
        # =========================================================================
        prompt = PromptTemplate(template=load_prompt("extend_keywords_for_value_recall"), input_variables=["query"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        # =========================================================================
        # 阶段2：ES 全文检索 + 去重后处理
        # 检索流程：
        #   1. 合并 jieba 关键词 + LLM 扩展关键词，取并集
        #   2. 对每个关键词在 ES 中做 match 查询（IK 分词后匹配）
        #   3. 用 dict 按 value_id 去重
        # =========================================================================
        values_map: dict[str, ValueInfo] = {}
        keywords = list(set(keywords + result))
        logger.info(f"召回字段取值扩展关键词：{keywords}")
        for keyword in keywords:
            # ES match 查询：ES 会对 keyword 做 IK 分词后再匹配倒排索引
            values: list[ValueInfo] = await value_es_repository.search(keyword)
            for value in values:
                value_id = value.id
                if value_id not in values_map:
                    values_map[value_id] = value

        retrieved_values = list(values_map.values())

        writer({"type": "progress", "step": "召回字段取值", "status": "success"})
        logger.info(f"召回字段取值：{list(values_map.keys())}")

        return {'retrieved_values': retrieved_values}
    except Exception as e:
        writer({"type": "progress", "step": "召回字段取值", "status": "error"})
        logger.error(f"召回字段取值失败: {str(e)}")
        raise