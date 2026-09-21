# =============================================================================
# 【入口层】查询请求模型（QuerySchema）
# 作用：定义 NL2SQL 查询接口的请求体结构，用于 FastAPI 的请求参数校验与解析。
#
# 组合关系（见 docs/architecture-05-fastapi-di-chain 图5）：
#   ROUTER（query_router）--> SCHEMA（QuerySchema）
#
# 说明：
#   - 基于 Pydantic BaseModel，FastAPI 自动完成请求体解析与类型校验
#   - 请求体示例：{"query": "统计去年各地区的销售总额"}
# =============================================================================

from pydantic import BaseModel


class QuerySchema(BaseModel):
    """查询请求体模型

    字段说明：
    - query: 用户自然语言查询字符串（必填）
    """
    query: str
