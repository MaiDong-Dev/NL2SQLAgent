# =============================================================================
# 【提示词构造模块】召回信息合并节点
# 作用：将三路并行召回（字段/取值/指标）的结果合并为统一的表结构视图，
#       为后续的 LLM 过滤和 SQL 生成提供结构化的上下文信息。
# 上下文传递：
#   - 输入：state["retrieved_columns"]、state["retrieved_values"]、
#           state["retrieved_metrics"] → 三路召回结果
#   - 中间：runtime.context["meta_mysql_repository"] → 查询元数据补全信息
#   - 输出：{"table_infos": [...], "metric_infos": [...]} → 合并后传给过滤节点
#
# 合并逻辑（4 个步骤）：
#   步骤1 - 指标关联字段补全：
#     将召回的指标所关联的字段（relevant_columns）也加入字段列表，
#     确保后续生成 SQL 时，指标计算所需的字段都已就位
#   步骤2 - 字段取值合并到字段示例：
#     将召回的字段取值（如"北京"）追加到对应字段的 examples 列表中，
#     帮助 LLM 理解字段的实际取值范围
#   步骤3 - 按表分组 + 主外键补全：
#     将字段按 table_id 分组，并显式查询每张表的主键和外键字段加入，
#     确保多表 JOIN 时有关联条件可用
#   步骤4 - 转换为 LLM 可读的 State 格式：
#     将 TableInfo/ColumnInfo 实体转换为精简的 TableInfoState/ColumnInfoState，
#     减少 Prompt 长度，避免超出 LLM 上下文窗口
# =============================================================================

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState, TableInfoState, MetricInfoState, ColumnInfoState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo


async def merge_retrieved_info(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "合并召回信息", "status": "running"})

    # 已召回信息
    retrieved_columns = state["retrieved_columns"]
    retrieved_values = state["retrieved_values"]
    retrieved_metrics = state["retrieved_metrics"]

    # 获取所需依赖
    meta_mysql_repository = runtime.context["meta_mysql_repository"]

    # 用 dict 存储字段信息，便于后续按 column_id 快速查找和补全
    retrieved_columns_map: dict[str, ColumnInfo] = {retrieved_column.id: retrieved_column for retrieved_column
                                                    in retrieved_columns}

    # 合并表格信息
    table_infos: list[TableInfoState] = []

    try:
        # =========================================================================
        # 步骤1：将指标信息的相关字段加入字段信息列表
        # 设计意图：指标如"转正率"可能关联"转正状态"和"入职日期"字段，
        # 即使这些字段在向量召回中未被命中，也需要加入以确保 SQL 生成正确
        # =========================================================================
        for retrieved_metric in retrieved_metrics:
            relevant_columns = retrieved_metric.relevant_columns
            for relevant_column in relevant_columns:
                if relevant_column not in retrieved_columns_map:
                    # 从元数据库中查询补全该字段的完整信息
                    column_info = await meta_mysql_repository.get_column_info_by_id(relevant_column)
                    retrieved_columns_map[relevant_column] = column_info

        # =========================================================================
        # 步骤2：将字段取值合并到字段信息列表
        # 设计意图：召回的字段取值（如"北京"、"在职"）需要与所属字段关联，
        # 作为字段的 examples 展示给 LLM，帮助 LLM 理解数据分布
        # =========================================================================
        for retrieved_value in retrieved_values:
            column_id = retrieved_value.column_id
            column_value = retrieved_value.value
            #
            if column_id not in retrieved_columns_map:
                column_info = await meta_mysql_repository.get_column_info_by_id(column_id)
                retrieved_columns_map[column_id] = column_info
            if column_value not in retrieved_columns_map[column_id].examples:
                retrieved_columns_map[column_id].examples.append(column_value)

        # =========================================================================
        # 步骤3：按照字段所属的表 id 进行分组，得到 table_id→columns 映射
        # =========================================================================
        table_to_columns_map: dict[str, list[ColumnInfo]] = {}
        for column in retrieved_columns_map.values():
            table_id = column.table_id
            if table_id not in table_to_columns_map:
                table_to_columns_map[table_id] = []
            table_to_columns_map[table_id].append(column)

        # =========================================================================
        # 步骤3.1：显式的添加每个表的主外键
        # 设计意图：向量召回可能遗漏主外键字段（这些字段通常不包含业务语义），
        # 但 SQL 生成时 JOIN 必须用到它们，所以需要显式从元数据库补全
        # =========================================================================
        for table_id in table_to_columns_map.keys():
            # 查询主外键字段
            key_columns: list[ColumnInfo] = await meta_mysql_repository.get_key_columns_by_table_id(table_id)

            # 当前表已有的所有列的 ID
            column_ids = [column.id for column in table_to_columns_map[table_id]]

            for key_column in key_columns:
                if key_column.id not in column_ids:
                    table_to_columns_map[table_id].append(key_column)

        # =========================================================================
        # 步骤4：将 table_id→columns 映射转换为 list[TableInfoState]
        # 设计意图：将内部的 ColumnInfo 实体转换为精简的 ColumnInfoState，
        # 减少 Prompt 长度，避免超出 LLM 上下文窗口
        # =========================================================================
        for table_id, columns in table_to_columns_map.items():
            table: TableInfo = await  meta_mysql_repository.get_table_info_by_id(table_id)
            columns = [
                ColumnInfoState(name=column.name, type=column.type, role=column.role, examples=column.examples,
                                description=column.description, alias=column.alias)
                for column in columns]
            table_info_state = TableInfoState(name=table.name,
                                              role=table.role,
                                              description=table.description,
                                              columns=columns)
            table_infos.append(table_info_state)

        # 处理指标信息：转换为精简的 MetricInfoState
        metric_infos: list[MetricInfoState] = [
            MetricInfoState(name=metric_info.name, description=metric_info.description,
                            relevant_columns=metric_info.relevant_columns, alias=metric_info.alias)
            for metric_info in retrieved_metrics]

        writer({"type": "progress", "step": "合并召回信息", "status": "success"})
        logger.info(
            f"合并召回信息: 表信息-{[table_info['name'] for table_info in table_infos]},指标信息-{[metric_info['name'] for metric_info in metric_infos]}")

        return {"table_infos": table_infos, "metric_infos": metric_infos}
    except Exception as e:
        writer({"type": "progress", "step": "合并召回信息", "status": "error"})
        logger.error(f"合并召回信息失败: {str(e)}")
        raise