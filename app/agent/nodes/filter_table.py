# =============================================================================
# 【提示词构造模块】表格过滤节点
# 作用：使用 LLM 从合并后的候选表中裁剪出回答用户问题真正必需的表和字段，
#       去除不相关的表和字段，减少 Prompt 噪音，提高 SQL 生成质量。
# 上下文传递：
#   - 输入：state["query"]、state["table_infos"] → 用户查询 + 合并后的表信息
#   - 输出：{"table_infos": [...]} → 裁剪后的表信息，覆盖原值
# Prompt 设计意图：
#   - 让 LLM 扮演"查询规划专家"，从候选 schema 中只选择必需的表和字段
#   - 输出 JSON 格式：{表名: [字段1, 字段2, ...]}，便于精确裁剪
#   - 强调"最小必要集合"原则：缺少任何关键字段问题无法回答，但不能冗余
# 后处理逻辑：
#   - 遍历 table_infos，删除 LLM 未选中的表和字段
#   - 保留原始 table_infos 中已存在的字段名称，不做新增
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


async def filter_table(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "过滤表格", "status": "running"})

    query = state["query"]
    table_infos = state["table_infos"]

    try:
        # =========================================================================
        # LLM 过滤表信息
        # Prompt 设计意图：
        #   将 table_infos 以 YAML 格式传入 Prompt（比 JSON 更紧凑、更易读），
        #   让 LLM 输出 {表名: [字段列表]} 的 JSON 格式，然后精确裁剪 table_infos
        # =========================================================================
        prompt = PromptTemplate(template=load_prompt("filter_table_info"), input_variables=["query", "table_infos"])
        output_parser = JsonOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query, "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)})

        # 利用模型输出过滤 table_infos
        # LLM 输出格式示例：
        # {
        #   'fact_order':['order_amount', 'region_id'],
        #   'dim_region':['region_id', 'region_name']
        # }
        for table_info in table_infos[:]:
            if table_info["name"] not in result:
                # 表未被 LLM 选中 → 删除整张表
                table_infos.remove(table_info)
            else:
                # 表被选中 → 只保留 LLM 指定的字段
                selected_columns = result[table_info["name"]]
                for column_info in table_info["columns"][:]:
                    if column_info["name"] not in selected_columns:
                        table_info["columns"].remove(column_info)

        writer({"type": "progress", "step": "过滤表格", "status": "success"})
        logger.info(f"过滤后的表信息: {[table_info['name'] for table_info in table_infos]}")
        return {"table_infos": table_infos}
    except Exception as e:
        writer({"type": "progress", "step": "过滤表格", "status": "error"})
        logger.error(f"过滤表失败:{str(e)}")
        raise