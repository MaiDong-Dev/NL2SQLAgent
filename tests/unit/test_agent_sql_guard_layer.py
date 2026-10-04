# =============================================================================
# 【Agent 层测试】server/agent/sql_guard（SQL 只读门禁）
# 覆盖：白名单前缀、多语句拦截、黑名单关键词、注释夹带、边界用例。
# 为什么值得单测：这是**唯一一道拦住写操作落到业务库的代码门禁**。
#   LLM 生成的 SQL 不可信，而 `EXPLAIN DELETE` 在 MySQL 里合法、能通过 validate_sql，
#   一旦这道正则写错（比如漏掉注释夹带或多语句），后果是真删数据。
#   纯函数、零依赖，必须离线可测。
# =============================================================================

import pytest

from server.agent.sql_guard import assert_read_only, check_read_only, strip_sql_comments

# 合法只读语句：必须放行
READ_ONLY_SQLS = [
    "select * from fact_order limit 10",
    "select * from fact_order;",                       # 末尾分号要容忍
    "SELECT d.year, sum(f.order_amount) FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id GROUP BY d.year",
    "with t as (select region_name from dim_region) select * from t",   # CTE
    "  \n\t select 1 ",                                 # 前后空白
    "-- 统计各大区销售额\nselect region_name from dim_region",           # 前导注释
    "select * from fact_order -- ; delete from fact_order",  # 分号在注释里，实际只有一条语句
    "select replace(product_name, 'a', 'b') from dim_product",  # REPLACE() 是字符串函数不是写操作
    "select count(*) from fact_order where order_amount > 100",
]

# 危险语句：必须拦截
DANGEROUS_SQLS = [
    "delete from fact_order",
    "DELETE FROM fact_order WHERE year < 2024",
    "update fact_order set order_amount = 0",
    "insert into fact_order values (1)",
    "drop table fact_order",
    "alter table fact_order add column x int",
    "truncate table fact_order",
    "select 1; delete from fact_order",                 # 多语句注入
    "select * from fact_order; drop table dim_date",
    "select * from fact_order into outfile '/tmp/a'",   # 文件导出
    "select sleep(10)",                                 # DoS
    "select benchmark(10000000, md5('x'))",
    "select * from information_schema.tables",          # 元数据探测
    "select * from mysql.user",
    "/* x */ delete from fact_order",                   # 注释夹带绕过
    "grant all on *.* to 'a'@'%'",
    "set global max_connections = 1",
    "",                                                 # 空语句
    "   ",
    "explain select * from fact_order",                 # 非查询开头
]


@pytest.mark.parametrize("sql", READ_ONLY_SQLS)
def test_read_only_sql_passes(sql):
    assert check_read_only(sql) is None, f"只读语句被误杀：{sql!r} -> {check_read_only(sql)}"


@pytest.mark.parametrize("sql", DANGEROUS_SQLS)
def test_dangerous_sql_blocked(sql):
    reason = check_read_only(sql)
    assert reason is not None, f"危险语句未被拦截：{sql!r}"
    assert isinstance(reason, str) and reason, "拒绝原因应是非空字符串，便于写进日志"


def test_non_string_input_blocked():
    """LLM 若返回非字符串（如 None），不能当成合法 SQL 放行"""
    for bad in (None, 123, [], {}):
        assert check_read_only(bad) is not None


def test_strip_sql_comments():
    assert strip_sql_comments("select 1 -- 注释").strip() == "select 1"
    # 块注释整体被替换为一个空格，故 "select " + " " + " 1"
    assert strip_sql_comments("select /* 块注释 */ 1").strip() == "select   1"


def test_assert_read_only_raises():
    assert_read_only("select 1")  # 合法不抛
    with pytest.raises(ValueError):
        assert_read_only("delete from fact_order")


def test_blacklist_does_not_kill_normal_business_sql():
    """黑名单不能误杀正常业务词：offset 里含 set、字段名含 create_time 之类"""
    for sql in (
        "select * from fact_order limit 10 offset 20",        # offset 含 "set"
        "select created_at, updated_at from dim_customer",     # created/updated 含 "create"/"update"
    ):
        assert check_read_only(sql) is None, f"正常业务 SQL 被误杀：{sql}"
