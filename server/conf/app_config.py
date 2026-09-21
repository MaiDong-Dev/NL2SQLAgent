# =============================================================================
# 【配置层】应用全局配置（AppConfig）
# 作用：定义整个 NL2SQL RAG Agent 运行时所需的全部配置结构，包括日志、数据库、
#       Qdrant 向量库、Embedding 服务、Elasticsearch 和 LLM 的连接参数。
#
# 配置加载流程：
#   1. 使用 @dataclass 定义配置结构（类型安全，带默认值与字段类型校验）
#   2. 通过 OmegaConf 从 conf/app_config.yaml 读取实际配置值
#   3. OmegaConf.structured(AppConfig) 生成 schema（保证 yaml 中字段完整）
#   4. OmegaConf.merge(schema, context) 将 yaml 值合并到 schema 中
#   5. OmegaConf.to_object() 将配置反序列化为 AppConfig 实例
#
# 上下文传递（组合关系）：
#   - app_config 是模块级单例，被以下模块 import 使用：
#     * clients/*（Embedding/Qdrant/ES/MySQL 客户端管理器，读取连接参数）
#     * agent/llm.py（读取 LLM 模型名称、API 地址与密钥）
#     * core/log.py（读取日志级别、文件路径、轮转策略）
#   - 依赖关系（见 docs/architecture-01）：所有 client → app_config
#
# 注意：本文件在 import 时即执行配置加载（模块级代码），因此必须保证
#       conf/app_config.yaml 存在且字段完整，否则导入即报错。
# =============================================================================

import warnings
from dataclasses import dataclass
from pathlib import Path

from omegaconf import OmegaConf

from server.conf.config_loader import load_config

# 支持从项目根目录的 .env 读取敏感配置（如 DEEPSEEK_API_KEY），系统环境变量优先级更高。
# python-dotenv 由 fastapi[standard] 传递引入；缺失时静默降级为仅使用系统环境变量。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[2] / ".env", override=False)
except ImportError:  # 可选依赖，缺失不影响配置加载
    pass


# -----------------------------------------------------------------------------
# 日志文件配置（LoggingConfig.file）
# -----------------------------------------------------------------------------
@dataclass
class File:
    """日志文件输出配置"""
    enable: bool        # 是否启用文件日志输出
    level: str          # 文件日志级别（如 "INFO"、"DEBUG"）
    path: str           # 日志文件存放目录路径
    rotation: str       # 日志轮转策略（如 "10 MB"、"1 day"）
    retention: str      # 日志保留时长（如 "7 days"）


@dataclass
class Console:
    """日志控制台输出配置"""
    enable: bool        # 是否启用控制台日志输出
    level: str          # 控制台日志级别


@dataclass
class LoggingConfig:
    """日志总配置：聚合文件与控制台两种输出"""
    file: File          # 文件日志配置
    console: Console    # 控制台日志配置


# -----------------------------------------------------------------------------
# 数据库配置（DBConfig）
# 说明：Meta 库与 DW 库共用同一结构，分别存储元数据与业务数据
# -----------------------------------------------------------------------------
@dataclass
class DBConfig:
    """MySQL 数据库连接配置（元数据库 / 数据仓库共用）"""
    host: str           # 数据库主机地址
    port: int           # 数据库端口（默认 3306）
    user: str           # 登录用户名
    password: str       # 登录密码
    database: str       # 数据库名


@dataclass
class QdrantConfig:
    """Qdrant 向量数据库连接配置"""
    host: str           # Qdrant 服务主机地址
    port: int           # Qdrant 服务端口（HTTP 默认 6333）
    embedding_size: int # 向量维度（必须与 Embedding 模型输出维度一致）


@dataclass
class EmbeddingConfig:
    """Embedding 服务连接配置（自部署 HuggingFace TEI 服务）"""
    host: str           # Embedding 服务主机地址
    port: int           # Embedding 服务端口
    model: str          # 模型名称/标识（如 bge-large-zh-v1.5）


@dataclass
class ESConfig:
    """Elasticsearch 连接配置"""
    host: str           # ES 服务主机地址
    port: int           # ES 服务端口（默认 9200）
    index_name: str     # 字段取值索引名称


@dataclass
class RecallConfig:
    """召回阶段配置（向量检索降噪参数）"""
    column_search_limit: int        # 单关键词检索条数：同一字段在库中有多条向量，需过采样后去重
    column_score_ratio: float       # 相对阈值：只保留相似度 >= 本次最高分 × ratio 的字段
    column_key_score_threshold: float  # 主外键的绝对阈值（键列不做相对阈值过滤，见下）


@dataclass
class LLMConfig:
    """大语言模型连接配置（OpenAI 兼容接口）"""
    model_name: str     # 模型名称（如 "deepseek-chat"、"gpt-4"）
    api_key: str        # API 密钥
    base_url: str       # API 基础地址（OpenAI 兼容端点）


@dataclass
class AppConfig:
    """应用总配置：聚合所有子模块配置"""
    logging: LoggingConfig      # 日志配置
    db_meta: DBConfig           # 元数据库配置（存储表/字段/指标定义）
    db_dw: DBConfig             # 数据仓库配置（存储业务数据，执行查询）
    qdrant: QdrantConfig        # Qdrant 向量库配置
    embedding: EmbeddingConfig  # Embedding 服务配置
    es: ESConfig                # Elasticsearch 配置
    recall: RecallConfig        # 召回阶段配置（向量检索降噪参数）
    llm: LLMConfig              # LLM 配置


# 定位 conf/app_config.yaml 配置文件路径
# __file__ = server/conf/app_config.py → parents[2] = 项目根目录
# 最终路径：<项目根>/conf/app_config.yaml
config_file = Path(__file__).parents[2] / 'conf' / 'app_config.yaml'

# 加载配置文件并反序列化为 AppConfig 实例（模块级单例）
# OmegaConf.structured 会依据 AppConfig 的 dataclass 定义生成 schema，
# 用于校验 yaml 中的字段是否完整、类型是否匹配。
if not config_file.exists():
    raise FileNotFoundError(
        f"未找到应用配置文件：{config_file}\n"
        f"请先复制模板：cp conf/app_config.example.yaml conf/app_config.yaml\n"
        f"（该文件含明文密码，已在 .gitignore 中，不会被提交）"
    )

context = OmegaConf.load(config_file)          # 读取 yaml 原始内容
schema = OmegaConf.structured(AppConfig)       # 生成结构化 schema
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))  # 合并并反序列化

# 密钥等敏感值不入库，未注入时提前告警，避免运行到 LLM 节点才报 401
if not app_config.llm.api_key:
    warnings.warn("未读取到 DEEPSEEK_API_KEY，请在环境变量或项目根目录 .env 中配置，否则 LLM 调用会返回 401",
                  RuntimeWarning, stacklevel=2)


if __name__ == '__main__':
    # 快速验证配置加载是否成功（打印 ES 主机地址）
    print(app_config.es.host)
