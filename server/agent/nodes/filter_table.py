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

import copy

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.llm import llm
from server.agent.state import DataAgentState
from server.agent.time_utils import has_time_semantic, is_time_dimension_table
from server.core.log import logger
from server.prompt.prompt_loader import load_prompt


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

        # =========================================================================
        # 过滤前先备份时间维表
        # 设计意图：LLM 过滤非常激进，常把整张时间维表裁掉（字段名没有业务语义），
        # 一旦裁掉，生成阶段只能对事实表日期键做算术/格式化，时间口径必错。
        # 故问句含时间语义时，先把时间维表整体留档，过滤后再兜底恢复。
        # =========================================================================
        time_table_backups = []
        if has_time_semantic(query):
            time_table_backups = [
                copy.deepcopy(table_info) for table_info in table_infos
                if is_time_dimension_table([column["name"] for column in table_info["columns"]])
            ]

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

        # =========================================================================
        # 过滤后兜底恢复时间维表
        #   - 整表被裁掉 → 原样放回
        #   - 表还在但时间粒度字段被裁 → 把被裁掉的字段补回
        # =========================================================================
        if time_table_backups:
            kept_table_names = {table_info["name"] for table_info in table_infos}
            for backup in time_table_backups:
                if backup["name"] not in kept_table_names:
                    table_infos.append(backup)
                    logger.info(f"时间维表被LLM过滤，已兜底恢复: {backup['name']}")
                    continue
                target = next(table_info for table_info in table_infos
                              if table_info["name"] == backup["name"])
                kept_column_names = {column["name"] for column in target["columns"]}
                for column in backup["columns"]:
                    if column["name"] not in kept_column_names:
                        target["columns"].append(column)

        writer({"type": "progress", "step": "过滤表格", "status": "success"})
        logger.info(f"过滤后的表信息: {[table_info['name'] for table_info in table_infos]}")
        return {"table_infos": table_infos}
    except Exception as e:
        writer({"type": "progress", "step": "过滤表格", "status": "error"})
        logger.error(f"过滤表失败:{str(e)}")
        raise