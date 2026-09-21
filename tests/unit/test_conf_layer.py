# =============================================================================
# 【配置层测试】server/conf
# 覆盖：本地真实配置是否就位、示例模板是否可被 schema 解析、meta_config 声明式
#      配置的字段约束是否合法、缺文件时是否给出明确错误。
# 特点：纯离线校验，不依赖 MySQL / ES / Qdrant / Embedding。
# =============================================================================

from pathlib import Path

import pytest

from server.conf.app_config import AppConfig, app_config
from server.conf.config_loader import load_config
from server.conf.meta_config import MetaConfig

ROOT = Path(__file__).resolve().parents[2]
CONF_DIR = ROOT / "conf"

VALID_COLUMN_ROLES = {"primary_key", "foreign_key", "measure", "dimension"}
VALID_TABLE_ROLES = {"fact", "dim"}


# -----------------------------------------------------------------------------
# 应用配置（app_config）
# -----------------------------------------------------------------------------
def test_local_config_exists():
    """本地真实配置必须存在：它不入库，但运行前必须就位"""
    assert (CONF_DIR / "app_config.yaml").is_file(), (
        "缺少 conf/app_config.yaml，请执行：cp conf/app_config.example.yaml conf/app_config.yaml"
    )


def test_app_config_module_singleton_loaded():
    """模块级单例应已加载完成，并带出各中间件连接参数"""
    assert app_config.db_meta.port == 3306
    assert app_config.db_dw.database == "dw"
    assert app_config.qdrant.embedding_size > 0
    assert app_config.embedding.model
    assert app_config.es.index_name


def test_recall_config_defaults_are_sane():
    """召回降噪参数必须落在有效区间（阈值写错会静默召回全量/召回为零）"""
    recall = app_config.recall
    assert recall.column_search_limit > 0
    assert recall.column_key_score_threshold > 0
    assert 0 < recall.column_score_ratio <= 1


def test_example_template_matches_schema():
    """示例模板必须与 AppConfig 结构一致，保证新环境复制后可直接运行"""
    cfg = load_config(CONF_DIR / "app_config.example.yaml", AppConfig)
    assert cfg.llm.base_url
    assert isinstance(cfg.logging.file.retention, str)


def test_example_template_contains_no_real_secret():
    """示例模板是入库文件，不允许出现真实密码"""
    text = (CONF_DIR / "app_config.example.yaml").read_text(encoding="utf-8")
    assert "Wl.123" not in text
    assert "Wuyun.123" not in text


def test_missing_config_file_raises():
    """配置文件缺失时应直接抛出 FileNotFoundError（而不是静默用默认值跑起来）"""
    with pytest.raises(FileNotFoundError):
        load_config(CONF_DIR / "not_exists.yaml", AppConfig)


# -----------------------------------------------------------------------------
# 元知识配置（meta_config）
# -----------------------------------------------------------------------------
def test_meta_config_parses():
    cfg = load_config(CONF_DIR / "meta_config.yaml", MetaConfig)
    assert cfg.tables, "meta_config.yaml 至少应声明一张表"


def test_meta_config_table_and_column_roles_are_valid():
    """表角色 / 字段角色是下游分支判断依据（如 is_time_dimension_table），取值必须合法"""
    cfg = load_config(CONF_DIR / "meta_config.yaml", MetaConfig)
    for table in cfg.tables:
        assert table.role in VALID_TABLE_ROLES, f"{table.name} 的表角色非法：{table.role}"
        assert table.columns, f"{table.name} 未声明任何字段"
        for column in table.columns:
            assert column.role in VALID_COLUMN_ROLES, (
                f"{table.name}.{column.name} 的字段角色非法：{column.role}"
            )


def test_meta_config_column_fields_are_typed():
    """alias 必须是列表、sync 必须是布尔值（OmegaConf 会按 dataclass 校验类型）"""
    cfg = load_config(CONF_DIR / "meta_config.yaml", MetaConfig)
    for table in cfg.tables:
        for column in table.columns:
            assert isinstance(column.alias, list), f"{table.name}.{column.name}.alias 应为列表"
            assert isinstance(column.sync, bool), f"{table.name}.{column.name}.sync 应为布尔值"
            assert column.description, f"{table.name}.{column.name} 缺少业务描述（影响语义召回）"


def test_meta_config_metrics_reference_existing_columns():
    """指标挂载的 relevant_columns 必须能在表定义中找到，否则召回时会补空"""
    cfg = load_config(CONF_DIR / "meta_config.yaml", MetaConfig)
    if not cfg.metrics:
        pytest.skip("meta_config.yaml 未声明指标")

    declared_ids = {f"{table.name}.{column.name}" for table in cfg.tables for column in table.columns}
    for metric in cfg.metrics:
        for column_id in metric.relevant_columns:
            assert column_id in declared_ids, f"指标「{metric.name}」引用了不存在的字段：{column_id}"
