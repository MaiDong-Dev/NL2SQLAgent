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
# 合并逻辑（3 个步骤）：
#   步骤1 - 字段取值合并到字段示例：
#     将召回的字段取值（如"北京"）追加到对应字段的 examples 列表中，
#     帮助 LLM 理解字段的实际取值范围
#   步骤2 - 按表分组 + 主外键/时间维度补全：
#     将字段按 table_id 分组，并显式查询每张表的主键和外键字段加入，
#     确保多表 JOIN 时有关联条件可用；问句含时间语义时并入时间维表字段
#   步骤3 - 转换为 LLM 可读的 State 格式：
#     将 TableInfo/ColumnInfo 实体转换为精简的 TableInfoState/ColumnInfoState，
#     减少 Prompt 长度，避免超出 LLM 上下文窗口
#
# 注意：指标关联字段（relevant_columns）不在此处并入——本节点早于 filter_metric，
#   此时并入会把「随后被裁掉的指标」的字段也留在候选集里形成噪音，
#   改由 enrich_metric_columns 在指标筛选之后按需补入。
# =============================================================================

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import DataAgentState, TableInfoState, MetricInfoState, ColumnInfoState
from server.agent.time_utils import has_time_semantic
from server.core.log import logger
from server.entities.column_info import ColumnInfo
from server.entities.table_info import TableInfo


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
        # 说明：指标关联字段（relevant_columns）**不在本节点并入**
        # 原因：本节点位于 filter_metric 之前，此时指标尚未筛选。若在这里把召回到的
        #   所有指标的关联字段都并入，被 filter_metric 裁掉的指标（如问「销售额」时
        #   召回的 AOV）仍会把它依赖的字段（order_id / customer_id）留在候选集里，
        #   实测这部分约占字段误召回的三分之一。
        # 改为「先筛指标、再补字段」：由 enrich_metric_columns 节点在
        #   filter_metric / filter_table 之后，只并入通过筛选的指标的关联字段。
        # =========================================================================

        # =========================================================================
        # 步骤1：将字段取值合并到字段信息列表
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
        # 步骤2：按照字段所属的表 id 进行分组，得到 table_id→columns 映射
        # =========================================================================
        table_to_columns_map: dict[str, list[ColumnInfo]] = {}
        for column in retrieved_columns_map.values():
            table_id = column.table_id
            if table_id not in table_to_columns_map:
                table_to_columns_map[table_id] = []
            table_to_columns_map[table_id].append(column)

        # =========================================================================
        # 步骤2.1：显式的添加每个表的主外键
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
        # 步骤2.2：时间维度补全
        # 设计意图：与步骤3.1的「主外键补全」同属确定性补偿 —— 向量召回几乎召不回
        # 时间维表字段（year/quarter/month 缺少业务语义），缺了它，SQL 生成只能退化成
        # 对事实表日期键做算术或字符串格式化（实测出现 date_id DIV 100）导致口径错误。
        # 因此当问句含时间语义时，显式把时间维表整表（含主键，供 JOIN）并入候选。
        # =========================================================================
        if has_time_semantic(state["query"]):
            time_columns: list[ColumnInfo] = await meta_mysql_repository.get_time_dimension_columns()
            for time_column in time_columns:
                columns_of_table = table_to_columns_map.setdefault(time_column.table_id, [])
                if time_column.id not in {column.id for column in columns_of_table}:
                    columns_of_table.append(time_column)
            if time_columns:
                logger.info(f"时间维度补全: {[column.id for column in time_columns]}")

        # =========================================================================
        # 步骤3：将 table_id→columns 映射转换为 list[TableInfoState]
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