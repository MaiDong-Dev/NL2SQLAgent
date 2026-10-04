# =============================================================================
# 【配置层】包级导出
# 作用：`from server.conf import app_config` 代替 `from server.conf.app_config import app_config`。
#
# 注意：app_config 是**模块级单例**，import 时即读取 conf/app_config.yaml（含明文密码）。
# 本包只依赖同包的 config_loader，不反向依赖任何其它内部模块，因此安全。
# =============================================================================

from server.conf.app_config import app_config

__all__ = ["app_config"]
