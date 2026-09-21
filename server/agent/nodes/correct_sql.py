# =============================================================================
# 【提示词构造模块 + LLM 调用】SQL 校正节点
# 作用：当 SQL 验证失败时，将错误信息连同原始上下文一起传给 LLM，
#       让 LLM 根据数据库返回的错误信息进行最小必要修复。
# 上下文传递：
#   - 输入：state["sql"]、state["error"]、state["query"]、state["table_infos"]、
#           state["metric_infos"]、state["date_info"]、state["db_info"] → 全部上下文+错误
#   - 输出：{"sql": "..."} → 修正后的 SQL，传给 execute_sql
# Prompt 设计意图：
#   - 让 LLM 扮演"SQL 调试专家"，根据数据库报错信息精准定位问题
#   - 强调"最小必要修改"原则：只修复导致错误的部分，不重写 SQL
#   - 严格保持原始业务语义不变，不擅自修改统计口径或过滤条件
#   - 输出格式与 generate_sql 一致：纯 SQL 文本，无 Markdown 标记
# 设计意图（为什么用 LLM 修正而不是规则修正）：
#   - SQL 错误类型多样（语法错误、字段不存在、类型不匹配等），
#     规则覆盖困难，LLM 能理解错误信息并做出针对性修复
# =============================================================================

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.llm import llm
from server.agent.state import DataAgentState
from server.core.log import logger
from server.prompt.prompt_loader import load_prompt


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校正SQL", "status": "running"})

    sql = state["sql"]
    error = state["error"]

    query = state["query"]
    table_infos = state["table_infos"]
    metric_infos = state["metric_infos"]
    date_info = state["date_info"]
    db_info = state["db_info"]

    try:
        # 组装校正 Prompt：包含原始查询 + 表结构 + 错误 SQL + 错误信息
        # 让 LLM 在充分理解上下文的基础上做精准修复
        prompt = PromptTemplate(template=load_prompt("correct_sql"), input_variables=["query", "metric_infos"])
        output_parser = StrOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query,
             "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
             "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False),
             "date_info": yaml.dump(date_info, allow_unicode=True, sort_keys=False),
             "db_info": yaml.dump(db_info, allow_unicode=True, sort_keys=False),
             "sql": sql,
             "error": error
             })
        writer({"type": "progress", "step": "校正SQL", "status": "success"})
        logger.info(f"校正后的SQL: {result}")
        return {"sql": result}
    except Exception as e:
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        logger.error(f"校正SQL失败:{str(e)}")
        raise