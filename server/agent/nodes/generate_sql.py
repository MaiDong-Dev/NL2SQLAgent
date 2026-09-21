# =============================================================================
# 【提示词构造模块 + LLM 调用】SQL 生成节点
# 作用：将所有上下文信息（表结构、指标定义、日期信息、数据库环境）组装为
#       完整的 Prompt，调用 LLM 生成一条可执行的 SQL 查询语句。
# 上下文传递：
#   - 输入：state["query"]、state["table_infos"]、state["metric_infos"]、
#           state["date_info"]、state["db_info"] → 全部上下文
#   - 输出：{"sql": "..."} → 传给 validate_sql 验证
# Prompt 设计意图：
#   - 多维度信息注入：表结构 + 指标定义 + 时间信息 + 数据库方言
#   - 严格约束：只输出纯 SQL 文本，禁止 Markdown 代码块标记
#   - 只读约束：生成的 SQL 只能用于查询，不能涉及写操作
#   - 指标优先：若指标信息中存在相关定义，必须严格遵循其口径
# 输出解析：
#   - 使用 StrOutputParser（纯文本），不做 JSON 解析
#   - 因为 SQL 是自由文本，不是结构化 JSON
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


async def generate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "生成SQL", "status": "running"})

    query = state["query"]
    table_infos = state["table_infos"]
    metric_infos = state["metric_infos"]
    date_info = state["date_info"]
    db_info = state["db_info"]

    try:
        # 组装 Prompt 并调用 LLM
        # 所有上下文信息以 YAML 格式序列化（比 JSON 更紧凑，节省 Token）
        prompt = PromptTemplate(template=load_prompt("generate_sql"),
                                input_variables=["query", "table_infos", "metric_infos", "date_info", "db_info"])
        output_parser = StrOutputParser()

        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query,
             "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
             "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False),
             "date_info": yaml.dump(date_info, allow_unicode=True, sort_keys=False),
             "db_info": yaml.dump(db_info, allow_unicode=True, sort_keys=False)
             })

        writer({"type": "progress", "step": "生成SQL", "status": "success"})
        logger.info(f"生成的SQL: {result}")
        return {"sql": result}
    except Exception as e:
        writer({"type": "progress", "step": "生成SQL", "status": "error"})
        logger.error(f"生成SQL失败: {str(e)}")
        raise