# =============================================================================
# 【提示词构造模块】指标关联字段补全节点
# 作用：把「通过筛选的指标」所依赖的字段补进候选表信息，确保生成 SQL 时
#       指标计算所需的字段已就位。
# 上下文传递：
#   - 输入：state["metric_infos"]（已被 filter_metric 裁剪）、state["table_infos"]
#           （已被 filter_table 裁剪）
#   - 中间：runtime.context["meta_mysql_repository"] → 查询缺失字段的元数据
#   - 输出：{"table_infos": [...]} → 补全后的表信息
#
# 为什么单独加这个节点，而不是在 merge_retrieved_info 里并入？
#   merge 阶段指标还没筛选，若在那里并入所有召回指标的 relevant_columns，
#   被 filter_metric 裁掉的指标（问「销售额」时召回的 AOV）依然会把它依赖的
#   字段留在候选集里 —— 这些字段对本次问句是纯噪音，实测约占误召回的三分之一。
#   因此把补全动作后移到 filter_metric 与 filter_table 都完成之后：
#   「先筛指标 → 再补字段」，候选集里只留下真正要用的指标所需字段。
# =============================================================================

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import ColumnInfoState, DataAgentState, TableInfoState
from server.core.log import logger


async def enrich_metric_columns(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "补全指标字段", "status": "running"})

    table_infos = state["table_infos"]
    metric_infos = state["metric_infos"]

    meta_mysql_repository = runtime.context["meta_mysql_repository"]

    try:
        # =========================================================================
        # 步骤1：收集「通过筛选的指标」所需字段，按表聚合
        # relevant_columns 形如 "fact_order.order_amount" → 拆成 (表名, 字段名)
        # =========================================================================
        needed_columns: dict[str, list[str]] = {}
        for metric_info in metric_infos:
            for relevant_column in metric_info["relevant_columns"]:
                if "." not in relevant_column:
                    continue
                table_name, column_name = relevant_column.split(".", 1)
                needed_columns.setdefault(table_name, [])
                if column_name not in needed_columns[table_name]:
                    needed_columns[table_name].append(column_name)

        # =========================================================================
        # 步骤2：把缺失的表/字段补进 table_infos（已有的不重复添加）
        # 注意：filter_table 可能整表裁掉，或裁掉了指标需要的字段，这里都要补回，
        # 否则 LLM 会因为缺少字段而无法按指标口径计算。
        # =========================================================================
        enriched: list[str] = []
        for table_name, column_names in needed_columns.items():
            table_info = next((item for item in table_infos if item["name"] == table_name), None)
            if table_info is None:
                table = await meta_mysql_repository.get_table_info_by_id(table_name)
                if table is None:
                    continue
                table_info = TableInfoState(name=table.name, role=table.role,
                                            description=table.description, columns=[])
                table_infos.append(table_info)

            kept_column_names = {column["name"] for column in table_info["columns"]}
            for column_name in column_names:
                if column_name in kept_column_names:
                    continue
                column = await meta_mysql_repository.get_column_info_by_id(f"{table_name}.{column_name}")
                if column is None:
                    continue
                table_info["columns"].append(
                    ColumnInfoState(name=column.name, type=column.type, role=column.role,
                                    examples=column.examples, description=column.description,
                                    alias=column.alias)
                )
                kept_column_names.add(column_name)
                enriched.append(column.id)

        writer({"type": "progress", "step": "补全指标字段", "status": "success"})
        if enriched:
            logger.info(f"指标关联字段补全: {enriched}")
        return {"table_infos": table_infos}
    except Exception as e:
        writer({"type": "progress", "step": "补全指标字段", "status": "error"})
        logger.error(f"补全指标关联字段失败: {str(e)}")
        raise
