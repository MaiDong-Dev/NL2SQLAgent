# =============================================================================
# 【核心层】日志配置（loguru）
# 作用：统一配置全局日志系统，支持控制台与文件两种输出，并注入 request_id
#       实现请求级日志追踪。
#
# 组合关系（见 docs/architecture-01 图1 的 LOG）：
#   - 依赖 app_config.logging（LoggingConfig，读取日志级别/路径/轮转策略）
#   - 依赖 core/context.py 的 request_id_ctx_var（日志注入请求 ID）
#   - logger 为全局单例，被所有业务模块（agent 节点、services、repositories）复用
#
# 日志格式字段说明：
#   - 时间：精确到毫秒（YYYY-MM-DD HH:mm:ss.SSS）
#   - 级别：日志等级（DEBUG/INFO/WARNING/ERROR）
#   - request_id：请求追踪 ID（通过 patch 动态注入）
#   - 位置：模块名:函数名:行号，便于快速定位代码
#   - 消息：日志正文
# =============================================================================

import asyncio
import sys
from pathlib import Path

from loguru import logger

from server.conf.app_config import app_config
from server.core.context import request_id_ctx_var


# 全局日志格式模板（控制台与文件共用）
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>request_id - {extra[request_id]}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def inject_request_id(record):
    """日志补丁函数：在每条日志写入前注入当前请求的 request_id

    参数：record  loguru 的日志记录对象

    说明：
    - 从 ContextVar 读取当前请求的 request_id（并发安全）
    - 写入 record["extra"]，供 log_format 中的 {extra[request_id]} 占位符使用
    """
    request_id = request_id_ctx_var.get()
    record["extra"]["request_id"] = request_id


# 移除 loguru 默认的日志处理器，避免重复输出
logger.remove()

# 给 logger 打补丁：每次日志写入前自动注入 request_id
# 注意：重新赋值 logger 是为了让业务模块 import 的 logger 携带 patch 行为
logger = logger.patch(inject_request_id)

# 根据配置决定是否启用控制台输出
if app_config.logging.console.enable:
    logger.add(sink=sys.stdout, level=app_config.logging.console.level, format=log_format)

# 根据配置决定是否启用文件输出
if app_config.logging.file.enable:
    path = Path(app_config.logging.file.path)
    # 确保日志目录存在
    path.mkdir(parents=True, exist_ok=True)
    logger.add(
        sink=path / "app.log",                                  # 日志文件路径
        level=app_config.logging.file.level,                    # 日志级别
        format=log_format,                                      # 日志格式
        rotation=app_config.logging.file.rotation,              # 轮转策略（如按大小/时间）
        retention=app_config.logging.file.retention,            # 保留时长
        encoding="utf-8"                                        # 文件编码
    )


if __name__ == '__main__':
    # 独立运行时的自测代码：演示 request_id 在并发请求中的隔离效果
    async def graph(request: str):
        # 打印日志（自动携带当前 request_id）
        logger.info(request)

    async def test1():
        # 模拟请求 1：设置 request_id 为 "request-1"
        request_id_ctx_var.set("request-1")
        await asyncio.sleep(1)
        await graph("request-1")

    async def test2():
        # 模拟请求 2：设置 request_id 为 "request-2"
        request_id_ctx_var.set("request-2")
        await asyncio.sleep(1)
        await graph("request-2")

    async def main():
        # 并发执行两个请求，验证日志 request_id 互不干扰
        await asyncio.gather(test1(), test2())

    asyncio.run(main())
