# =============================================================================
# 【入口层】查询路由（query_router）
# 作用：定义 NL2SQL 查询的 HTTP 接口，接收用户自然语言查询，返回 SSE 流式响应。
#
# 组合关系（见 docs/architecture-05-fastapi-di-chain 图5）：
#   POST /api/query → QuerySchema → get_query_service() → QueryService.query()
#
# 接口说明：
#   - 请求方式：POST
#   - 路径：/api/query
#   - 请求体：{"query": "统计去年各地区的销售总额"}
#   - 响应：StreamingResponse（text/event-stream），即 SSE 流，逐条推送
#           处理进度（progress）与最终结果（result）
# =============================================================================

from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from server.api.dependencies import get_query_service
from server.api.schemas.query_schema import QuerySchema
from server.services.query_service import QueryService

# 创建查询路由（前缀/标签可在注册时统一配置）
query_router = APIRouter()


@query_router.post("/api/query")
async def query(
    query: QuerySchema, query_service: QueryService = Depends(get_query_service)
):
    """NL2SQL 查询接口

    参数：
    - query:        请求体（QuerySchema），包含用户自然语言查询
    - query_service: 通过依赖注入自动装配的 QueryService 实例

    返回：
    - StreamingResponse：SSE 流式响应（media_type="text/event-stream"），
      前端可实时接收处理进度与最终 SQL 执行结果
    """
    return StreamingResponse(
        query_service.query(query.query), media_type="text/event-stream"
    )
