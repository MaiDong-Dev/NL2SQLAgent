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


def format_business_date(date_id) -> str | None:
    """把事实表 yyyyMMdd 形式的整型日期键转成 YYYY-MM-DD

    抽成模块级纯函数（不依赖会话）是为了能离线单测。
    非法值或 None 一律返回 None，由调用方决定如何降级。

    示例：20240101 -> "2024-01-01"，None -> None
    """
    if date_id is None:
        return None

    raw = str(date_id).strip()
    if len(raw) != 8 or not raw.isdigit():
        return None

    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


class DWMySQLRepository:
    """数据仓库查询仓库

    职责：
    - 查询数据表的字段类型和示例值（用于元数据构建）
    - 获取数据库版本信息（用于 SQL 方言适配）
    - 验证 SQL 语法（EXPLAIN）
    - 执行 SQL 查询（返回结果集）
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        """查询指定表的所有字段名和类型

        使用 SHOW COLUMNS 获取表结构元数据
        返回示例：{"id": "int", "name": "varchar(255)", "created_at": "datetime"}
        """
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int) -> list:
        """查询指定字段的去重取值列表（用于元数据构建时的示例值）

        使用 SELECT DISTINCT 获取字段的枚举值/示例值
        limit 参数控制返回数量，避免大字段返回过多数据
        """
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return result.scalars().fetchall()

    async def get_db_info(self) -> dict:
        """获取数据库环境信息（类型 + 版本号）

        返回格式：{"version": "8.0.35", "dialect": "mysql"}
        用途：帮助 LLM 生成符合特定数据库版本的 SQL 语法
        """
        result = await self.session.execute(text("select version()"))
        version = result.scalar()

        dialect = self.session.get_bind().dialect.name

        return {'version': version, 'dialect': dialect}

    async def get_data_date_range(self) -> dict:
        """获取事实数据真实覆盖的日期范围（最早/最晚业务日期）

        返回格式：{"start": "2024-01-01", "end": "2025-12-31"}；表内无数据时为
        {"start": None, "end": None}

        设计意图：
        - 生成 SQL 时必须知道"数据实际覆盖到哪一天"。否则用户问"1月份"而系统
          当前日期是 2026 年时，模型会用当前年份补全过滤条件，查不到任何数据。
        - 直接取事实表 date_id 的最小/最大值：date_id 本身就是 yyyyMMdd 编码，
          取极值即可，无需对列做算术或字符串处理（与 generate_sql 的时间口径约束一致）。
        """
        sql = "select min(date_id) as min_date, max(date_id) as max_date from fact_order"
        row = (await self.session.execute(text(sql))).mappings().fetchone()
        return {
            "start": format_business_date(row["min_date"]),
            "end": format_business_date(row["max_date"]),
        }

    async def validate_sql(self, sql: str) -> None:
        """使用 EXPLAIN 验证 SQL 语法（不实际执行查询）

        设计意图：
        - MySQL 的 EXPLAIN 会解析 SQL 并生成执行计划
        - 如果 SQL 有语法错误，EXPLAIN 会抛出异常
        - 比直接执行更安全，不会产生耗时查询或数据变更
        """
        await self.session.execute(text(f"explain {sql}"))

    async def execute_sql(self, sql: str) -> list[dict]:
        """执行业务查询并返回结果

        返回格式：list[dict]，每行数据为 {列名: 值} 的字典
        使用 mappings() 方法自动将结果行转为 dict
        """
        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]
