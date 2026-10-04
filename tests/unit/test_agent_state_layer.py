# =============================================================================
# 【Agent 状态层测试】server/agent/state 与 DW 仓库的纯函数
# 覆盖：DateInfoState 的字段完整性（含新增的 data_range）、时间范围格式转换。
# 为什么值得单测：state 的 TypedDict 没有 total=False、所有字段必填，
# 新增字段必须同步更新构造点，否则运行到 add_extra_context 才炸；
# 而 data_range 是修复"用系统当前年份过滤未指定年份问句"的关键上下文，
# 实测该缺陷会让同一问句连跑 5 次产生 4 个不同 SQL（含 3 次查空）。
# 特点：只 import 类型定义与纯函数，不建数据库连接、不碰 app_config。
# =============================================================================

import pytest

from server.agent.state import DataAgentState, DateInfoState
from server.repositories.mysql.dw.dw_mysql_repository import format_business_date


# -----------------------------------------------------------------------------
# DateInfoState
# -----------------------------------------------------------------------------
def test_date_info_state_carries_data_range():
    """data_range 必须在类型定义里，否则 prompt 拿不到数据真实范围"""
    assert "data_range" in DateInfoState.__annotations__


def test_date_info_state_keeps_original_fields():
    """原有三个字段不能因为加字段而被挤掉"""
    for field in ("date", "weekday", "quarter"):
        assert field in DateInfoState.__annotations__


def test_date_info_state_is_constructible_with_data_range():
    """TypedDict 无 total=False，字段必填 —— 这里按真实构造方式验证一次"""
    info = DateInfoState(date="2026-10-03", weekday="Saturday", quarter="Q4",
                         data_range={"start": "2024-01-01", "end": "2025-12-31"})
    assert info["data_range"]["end"] == "2025-12-31"


def test_main_state_still_declares_date_info():
    """主状态里的 date_info 字段不能被误删（generate_sql / correct_sql 都读它）"""
    assert "date_info" in DataAgentState.__annotations__


# -----------------------------------------------------------------------------
# format_business_date
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "date_id,expected",
    [
        (20240101, "2024-01-01"),
        (20251231, "2025-12-31"),
        ("20250102", "2025-01-02"),   # 驱动可能返回字符串
        (None, None),
        (2024, None),                 # 位数不足，不是合法的 yyyyMMdd
        ("2024010a", None),           # 非纯数字
    ],
)
def test_format_business_date(date_id, expected):
    assert format_business_date(date_id) == expected


def test_format_business_date_is_independent_of_session():
    """必须是模块级纯函数：不传 session 也能调用，这样单测无需中间件"""
    assert format_business_date(20250315) == "2025-03-15"
