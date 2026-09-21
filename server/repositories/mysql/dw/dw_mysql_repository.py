# =============================================================================
# 【数据库交互模块】数据仓库 MySQL Repository
# 作用：封装对业务数据仓库（DW）的查询操作，包括：
#       - 元数据查询（字段类型、字段取值、数据库版本）
#       - SQL 验证（EXPLAIN）
#       - SQL 执行（实际查询）
# 上下文传递：作为 DataAgentContext 的成员，供在线查询节点（validate_sql、execute_sql、
#             add_extra_context）使用；同时被 meta_builder 的元知识构建（读字段类型/取值）复用。
# =============================================================================

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DWMySQLRepository:
    """数据仓库查询仓库
    
    职责：
    - 查询数据表的字段类型和示例值（用于元数据构建）
    - 获取数据库版本信息（用于 SQL 方言适配）
    - 验证 SQL 语法（EXPLAIN）
    - 执行 SQL 查询（返回结果集）
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        """查询指定表的所有字段名和类型
        
        使用 SHOW COLUMNS 获取表结构元数据
        返回示例：{"id": "int", "name": "varchar(255)", "created_at": "datetime"}
        """
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        """查询指定字段的去重取值列表（用于元数据构建时的示例值）
        
        使用 SELECT DISTINCT 获取字段的枚举值/示例值
        limit 参数控制返回数量，避免大字段返回过多数据
        """
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return result.scalars().fetchall()

    async def get_db_info(self):
        """获取数据库环境信息（类型 + 版本号）
        
        返回格式：{"version": "8.0.35", "dialect": "mysql"}
        用途：帮助 LLM 生成符合特定数据库版本的 SQL 语法
        """
        result = await self.session.execute(text("select version()"))
        version = result.scalar()

        dialect = self.session.get_bind().dialect.name

        return {'version': version, 'dialect': dialect}

    async def validate_sql(self, sql):
        """使用 EXPLAIN 验证 SQL 语法（不实际执行查询）
        
        设计意图：
        - MySQL 的 EXPLAIN 会解析 SQL 并生成执行计划
        - 如果 SQL 有语法错误，EXPLAIN 会抛出异常
        - 比直接执行更安全，不会产生耗时查询或数据变更
        """
        await self.session.execute(text(f"explain {sql}"))

    async def execute_sql(self, sql):
        """执行业务查询并返回结果
        
        返回格式：list[dict]，每行数据为 {列名: 值} 的字典
        使用 mappings() 方法自动将结果行转为 dict
        """
        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]