# =============================================================================
# 【数据库交互模块】元数据 MySQL Repository
# 作用：封装对元数据库（Meta DB）的 CRUD 操作，管理表定义、字段定义、
#       指标定义及其关联关系。这是 RAG 系统的"知识底座"，存储了所有可用的
#       数据 Schema 信息。
# 上下文传递：被 DataAgentContext 携带，在 merge_retrieved_info 节点中
#            注入使用，用于补全召回结果中缺失的元数据。
# =============================================================================

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from server.entities.column_info import ColumnInfo
from server.entities.column_metric import ColumnMetric
from server.entities.metric_info import MetricInfo
from server.entities.table_info import TableInfo
from server.models.column_info_mysql import ColumnInfoMySQL
from server.models.table_info_mysql import TableInfoMySQL
from server.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from server.repositories.mysql.meta.mappers.column_metric_mapper import ColumnMetricMapper
from server.repositories.mysql.meta.mappers.metric_info_mapper import MetricInfoMapper
from server.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper


class MetaMySQLRepository:
    """元数据仓库
    
    职责：
    - 存储和查询表信息（TableInfo）
    - 存储和查询字段信息（ColumnInfo）
    - 存储和查询指标信息（MetricInfo）
    - 存储和查询指标-字段关联关系（ColumnMetric）
    - 查询主外键字段（用于 SQL JOIN 补全）
    
    数据流向：
    - 写入：meta_knowledge_service.build() 在初始化时批量写入
    - 读取：merge_retrieved_info 节点在运行时查询补全元数据
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_table_infos(self, table_infos: list[TableInfo]):
        """批量保存表定义（Entity → Model → DB）"""
        models = [TableInfoMapper.to_model(table_info) for table_info in table_infos]
        self.session.add_all(models)

    async def save_column_infos(self, columns_info: list[ColumnInfo]):
        """批量保存字段定义"""
        models = [ColumnInfoMapper.to_model(column_info) for column_info in columns_info]
        self.session.add_all(models)

    async def save_metric_infos(self, metric_infos: list[MetricInfo]):
        """批量保存指标定义"""
        self.session.add_all([MetricInfoMapper.to_model(metric_info) for metric_info in metric_infos])

    async def save_column_metrics(self, column_metrics: list[ColumnMetric]):
        """批量保存指标-字段关联关系"""
        self.session.add_all([ColumnMetricMapper.to_model(column_metric) for column_metric in column_metrics])

    async def get_column_info_by_id(self, column_id: str) -> ColumnInfo | None:
        """根据字段 ID 查询字段完整信息（DB → Entity）
        
        用途：当召回结果中缺少某个字段的完整信息时，从元数据库补全
        """
        result: ColumnInfoMySQL | None = await self.session.get(ColumnInfoMySQL, column_id)
        if result:
            return ColumnInfoMapper.to_entity(result)
        return None

    async def get_table_info_by_id(self, table_id: str) -> TableInfo | None:
        """根据表 ID 查询表完整信息"""
        result: TableInfoMySQL | None = await self.session.get(TableInfoMySQL, table_id)
        if result:
            return TableInfoMapper.to_entity(result)
        return None

    async def get_key_columns_by_table_id(self, table_id: str) -> list[ColumnInfo]:
        """查询指定表的主键和外键字段
        
        设计意图：向量召回可能遗漏主外键字段（无业务语义），
        但 SQL JOIN 必须用到它们，所以需要显式查询补全
        
        使用原生 SQL 查询 role 为 'primary_key' 或 'foreign_key' 的字段
        """
        sql = """
            select * 
            from column_info 
            where table_id = :table_id 
            and role in ('primary_key', 'foreign_key')
        """
        result = await self.session.execute(text(sql), {"table_id": table_id})
        return [ColumnInfo(**row) for row in result.mappings().fetchall()]

    async def get_time_dimension_columns(self) -> list[ColumnInfo]:
        """查询「时间维度表」的全部字段

        设计意图：与 get_key_columns_by_table_id 同属一类补偿机制 ——
        向量召回几乎召不回时间维表字段（year/quarter/month 缺少业务语义），
        但做时间口径分析时必须 JOIN 时间维表，否则 LLM 会退化成对事实表日期键
        做算术或字符串格式化（如 `date_id DIV 100`、`DATE_FORMAT(STR_TO_DATE(date_id,...))`）。

        识别方式：维度表（table_info.role='dim'）中同时具备 year/quarter/month
        里的至少 2 个时间粒度字段，即判定为时间维度表，返回其全部字段（含主键，供 JOIN）。
        库中没有时间维表时返回空列表，调用方无需特殊处理。
        """
        sql = """
            select c.*
            from column_info c
            where c.table_id in (
                select c2.table_id
                from column_info c2
                join table_info t2 on t2.id = c2.table_id
                where t2.role = 'dim'
                  and c2.name in ('year', 'quarter', 'month')
                group by c2.table_id
                having count(distinct c2.name) >= 2
            )
        """
        result = await self.session.execute(text(sql))
        return [ColumnInfo(**row) for row in result.mappings().fetchall()]