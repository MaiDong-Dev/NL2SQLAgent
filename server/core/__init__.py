# =============================================================================
# 【核心层】包级导出
# 作用：`from server.core import logger` 代替 `from server.core.log import logger`。
#       logger 是全仓最常用的内部符号，这一条收益最大。
#
# ⚠️ 注意副作用：`server/core/log.py` 在 **import 时**就会读取 app_config.logging、
#   创建 logs/ 目录并挂上 loguru 的 sink。因此本文件（以及 `import server.core.*`
#   的任何一行）都会顺手完成日志初始化——这是有意为之（日志必须尽早可用），
#   但如果将来需要"只在明确要求时初始化日志"，就要把这段逻辑挪进显式函数。
# =============================================================================

from server.core.context import request_id_ctx_var
from server.core.log import logger

__all__ = ["logger", "request_id_ctx_var"]
