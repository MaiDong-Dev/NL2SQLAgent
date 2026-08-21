# =============================================================================
# 【配置层】通用配置加载器
# 作用：提供通用的 OmegaConf 配置加载工具函数，将任意 YAML 配置文件加载并
#       反序列化为指定的 dataclass 类型实例。
#
# 组合关系：
#   - 被 app/conf/app_config.py、app/conf/meta_config.py 复用（当前 app_config
#     实际上直接内联实现了同样的逻辑，本函数作为通用抽象保留）
#   - 依赖 OmegaConf 库实现 schema 合并与类型校验
#
# 设计意图：
#   - 泛型函数 load_config[T]，通过类型参数 T 指定目标 dataclass 类型
#   - OmegaConf.structured(schema_cls) 依据 dataclass 生成 schema，用于：
#       1. 校验 yaml 字段是否完整、类型是否匹配
#       2. 为缺失字段填充默认值（dataclass 定义的默认值）
# =============================================================================

from pathlib import Path
from typing import Type, TypeVar

from omegaconf import OmegaConf

# 泛型类型变量 T：表示目标 dataclass 配置类型
T = TypeVar("T")


def load_config[T](config_file: Path, schema_cls: Type[T]) -> T:
    """加载 YAML 配置文件并反序列化为指定类型的配置对象

    参数：
    - config_file: YAML 配置文件路径
    - schema_cls:  目标配置 dataclass 类型（如 AppConfig、MetaConfig）

    返回：
    - 反序列化后的配置对象实例（类型为 T）

    加载流程：
    1. OmegaConf.load          读取 yaml 原始内容
    2. OmegaConf.structured    依据 schema_cls 生成结构化 schema（类型校验 + 默认值）
    3. OmegaConf.merge         将 yaml 值合并到 schema（schema 优先级低于 yaml 实际值）
    4. OmegaConf.to_object     反序列化为 Python dataclass 实例
    """
    context = OmegaConf.load(config_file)                       # 读取 yaml 原始内容
    schema = OmegaConf.structured(schema_cls)                   # 生成结构化 schema
    config: T = OmegaConf.to_object(OmegaConf.merge(schema, context))  # 合并并反序列化
    return config
