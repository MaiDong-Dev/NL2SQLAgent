# =============================================================================
# 【提示词构造模块】指标过滤节点
# 作用：使用 LLM 从召回的候选指标中筛选出回答用户问题真正必需的指标，
#       去除不相关的指标，减少 Prompt 噪音，避免 LLM 生成不必要的指标计算。
# 上下文传递：
#   - 输入：state["query"]、state["metric_infos"] → 用户查询 + 合并后的指标
#   - 输出：{"metric_infos": [...]} → 裁剪后的指标，覆盖原值
# Prompt 设计意图：
#   - 让 LLM 扮演"指标筛选与查询规划专家"
#   - 核心原则：问题涉及度量/统计才选指标，纯列表查询不选指标
#   - 最小集合原则：能用一个指标回答的不用多个，冗余元素要剔除
# 后处理逻辑：
#   - 遍历 metric_infos，删除 LLM 未选中的指标
#   - 只保留指标名称，不修改指标定义
# =============================================================================

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


async def filter_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "过滤指标", "status": "running"})

    query = state["query"]
    metric_infos = state["metric_infos"]
    try:
        # =========================================================================
        # LLM 过滤指标信息
        # Prompt 设计意图：
        #   将 metric_infos 以 YAML 格式传入，让 LLM 输出指标名称的 JSON 数组，
        #   然后精确裁剪 metric_infos。允许输出空数组 [] 表示不需要任何指标。
        # =========================================================================
        prompt = PromptTemplate(template=load_prompt("filter_metric_info"), input_variables=["query", "metric_infos"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query, "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False)})

        # 利用模型输出过滤 metric_infos：只保留 LLM 选中的指标
        for metric_info in metric_infos[:]:
            if metric_info["name"] not in result:
                metric_infos.remove(metric_info)

        writer({"type": "progress", "step": "过滤指标", "status": "success"})
        logger.info(f"过滤后的指标: {[metric_info['name'] for metric_info in metric_infos]}")
        return {"metric_infos": metric_infos}
    except Exception as e:
        writer({"type": "progress", "step": "过滤指标", "status": "error"})
        logger.error(f"过滤指标失败:{str(e)}")
        raise