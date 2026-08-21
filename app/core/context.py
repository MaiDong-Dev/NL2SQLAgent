# =============================================================================
# 【核心层】请求上下文（request_id）
# 作用：定义全局的 request_id 上下文变量（ContextVar），用于在并发请求中
#       追踪和区分日志，实现「请求级」的日志隔离。
#
# 组合关系（见 docs/architecture-01 图1 的 REQ_CTX）：
#   - 被 core/log.py 的 inject_request_id() 读取，注入到每条日志记录
#   - 各请求处理器（中间件/依赖）通过 request_id_ctx_var.set() 设置当前请求 ID
#
# 设计意图：
#   为什么用 ContextVar 而不是全局变量？
#   - FastAPI 是异步框架，多个请求在同一事件循环中并发交错执行
#   - 普通全局变量会被并发请求相互覆盖，导致日志串号
#   - ContextVar 是「上下文局部变量」，每个协程/任务拥有独立的值副本，
#     天然支持并发场景下的请求隔离（类似线程局部变量 thread-local）
# =============================================================================

from contextvars import ContextVar

# 请求 ID 上下文变量：默认值为 "1"（无请求上下文时的兜底值）
# 用法示例：
#   request_id_ctx_var.set("request-123")   # 请求开始时设置
#   request_id = request_id_ctx_var.get()   # 日志注入时读取
request_id_ctx_var = ContextVar("request_id", default="1")
