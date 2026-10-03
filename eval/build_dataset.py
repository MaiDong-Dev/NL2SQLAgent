# =============================================================================
# 【评测集构建】build_dataset
# 作用：把下面的题目清单编译成 eval/dataset.jsonl，并在编译期把每条题**真跑一遍**：
#       参考 SQL 必须能执行、结果非空、行数与声明一致，否则直接报错不产出文件。
#
# 为什么要用生成器而不是手写 jsonl：
#   1. reference_columns 由参考 SQL **自动推导**（约定 SQL 里每列都带表别名），
#      避免手工标注漏字段或写错表名——09 报告里"标注了系统召不回的字段"就是这么来的。
#   2. expected_rows 在编译期与实际行数比对，能直接抓出"分组粒度写错"
#      （例如问"各大区"却按省份分组，会得到 31 行而不是 7 行）。
#
# 出题铁律（09 报告复盘结论，逐条对应下面的检查）：
#   - 答案唯一：格式化（ROUND）必须在问句写明"保留两位小数"
#   - 输出列唯一："哪个"只输出维度列，"排名/前N/有哪些"才输出维度+度量
#   - 形态唯一：问"是多少"且无分组维度 → 必须返回单个汇总值
#   - 方向唯一：差值题必须写明方向或用绝对值，禁止裸"相差多少"
#   - 时间显式：凡涉年份必写年份；刻意不写年份的题单独标记，用来考"不许用当前年份"
#
# 运行方式（项目根目录）：
#   python -m eval.build_dataset              # 校验并写入 eval/dataset.jsonl
#   python -m eval.build_dataset --check-only # 只校验不写文件
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from server.clients.mysql_client_manager import (  # noqa: E402
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from server.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository  # noqa: E402

OUTPUT = ROOT / "eval" / "dataset.jsonl"

# -----------------------------------------------------------------------------
# 题目清单：(类别, 问句, 参考 SQL, 期望行数)
#
# 参考 SQL 约定：**每一列都写成 别名.列名**，便于自动推导 reference_columns。
# 期望行数用于抓分组粒度错误，务必按问句的真实语义填写。
# -----------------------------------------------------------------------------
CASES: list[tuple[str, str, str, int]] = [
    # === A 单指标聚合（问"是多少"，必须返回单个汇总值） ===
    ("A-单指标聚合", "一共有多少笔订单",
     "SELECT COUNT(f.order_id) AS order_count FROM fact_order f", 1),
    ("A-单指标聚合", "总销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount FROM fact_order f", 1),
    ("A-单指标聚合", "总销量是多少件",
     "SELECT SUM(f.order_quantity) AS total_quantity FROM fact_order f", 1),
    ("A-单指标聚合", "下过单的客户一共有多少人",
     "SELECT COUNT(DISTINCT f.customer_id) AS customer_count FROM fact_order f", 1),
    ("A-单指标聚合", "平均每笔订单的金额是多少（保留两位小数）",
     "SELECT ROUND(AVG(f.order_amount), 2) AS avg_amount FROM fact_order f", 1),
    ("A-单指标聚合", "单笔订单的最高金额是多少",
     "SELECT MAX(f.order_amount) AS max_amount FROM fact_order f", 1),
    ("A-单指标聚合", "一共有多少个商品",
     "SELECT COUNT(p.product_id) AS product_count FROM dim_product p", 1),
    ("A-单指标聚合", "一共有多少个品牌（去重后）",
     "SELECT COUNT(DISTINCT p.brand) AS brand_count FROM dim_product p", 1),

    # === B 单级分组 ===
    ("B-单级分组", "各大区的销售额分别是多少",
     "SELECT r.region_name, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.region_name", 7),
    ("B-单级分组", "各大区的订单量分别是多少",
     "SELECT r.region_name, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.region_name", 7),
    ("B-单级分组", "各省的订单量分别是多少",
     "SELECT r.province, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.province", 31),
    ("B-单级分组", "各商品品类的销售额分别是多少",
     "SELECT p.category, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.category", 10),
    ("B-单级分组", "各商品品类的销量分别是多少",
     "SELECT p.category, SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.category", 10),
    ("B-单级分组", "各品牌的销售额分别是多少",
     "SELECT p.brand, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.brand", 61),
    ("B-单级分组", "各会员等级的订单量分别是多少",
     "SELECT c.member_level, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "GROUP BY c.member_level", 4),
    ("B-单级分组", "各会员等级的平均订单金额是多少（保留两位小数）",
     "SELECT c.member_level, ROUND(AVG(f.order_amount), 2) AS avg_amount "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "GROUP BY c.member_level", 4),
    ("B-单级分组", "男女客户分别下了多少单",
     "SELECT c.gender, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "GROUP BY c.gender", 2),
    ("B-单级分组", "各省下过单的客户数分别是多少",
     "SELECT r.province, COUNT(DISTINCT f.customer_id) AS customer_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.province", 31),
    ("B-单级分组", "各大区的总销量分别是多少",
     "SELECT r.region_name, SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.region_name", 7),

    # === C 排序与 TopN ===
    ("C-排序与TopN", "销售额最高的商品品类是哪个",
     "SELECT p.category FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.category ORDER BY SUM(f.order_amount) DESC LIMIT 1", 1),
    ("C-排序与TopN", "销量最高的商品是哪个",
     "SELECT p.product_name FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.product_id, p.product_name ORDER BY SUM(f.order_quantity) DESC LIMIT 1", 1),
    ("C-排序与TopN", "销量前三名的商品分别是哪些",
     "SELECT p.product_name, SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.product_id, p.product_name ORDER BY total_quantity DESC LIMIT 3", 3),
    ("C-排序与TopN", "销售额前5的商品分别是哪些",
     "SELECT p.product_name, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.product_id, p.product_name ORDER BY total_amount DESC LIMIT 5", 5),
    ("C-排序与TopN", "销售额最高的省份是哪个",
     "SELECT r.province FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.province ORDER BY SUM(f.order_amount) DESC LIMIT 1", 1),
    ("C-排序与TopN", "订单量最多的10个省份分别是哪些",
     "SELECT r.province, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.province ORDER BY order_count DESC LIMIT 10", 10),
    ("C-排序与TopN", "下单金额最高的前5名客户是谁",
     "SELECT c.customer_name, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "GROUP BY c.customer_id, c.customer_name ORDER BY total_amount DESC LIMIT 5", 5),
    ("C-排序与TopN", "各品牌的销售额排名是怎样的（从高到低）",
     "SELECT p.brand, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.brand ORDER BY total_amount DESC", 61),
    ("C-排序与TopN", "各大区的销售额排名是怎样的（从高到低）",
     "SELECT r.region_name, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "GROUP BY r.region_name ORDER BY total_amount DESC", 7),

    # === D 时间粒度与趋势 ===
    ("D-时间粒度与趋势", "2025年每个月的订单量分别是多少",
     "SELECT d.month, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 GROUP BY d.month ORDER BY d.month", 12),
    ("D-时间粒度与趋势", "2024年每个月的订单量分别是多少",
     "SELECT d.month, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2024 GROUP BY d.month ORDER BY d.month", 12),
    ("D-时间粒度与趋势", "2025年每个月的销售额分别是多少",
     "SELECT d.month, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 GROUP BY d.month ORDER BY d.month", 12),
    ("D-时间粒度与趋势", "2025年各季度的订单量分别是多少",
     "SELECT d.quarter, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 GROUP BY d.quarter ORDER BY d.quarter", 4),
    ("D-时间粒度与趋势", "2024年各季度的订单量分别是多少",
     "SELECT d.quarter, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2024 GROUP BY d.quarter ORDER BY d.quarter", 4),
    ("D-时间粒度与趋势", "2025年3月每天的订单量分别是多少",
     "SELECT d.day, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 AND d.month = 3 GROUP BY d.day ORDER BY d.day", 31),
    ("D-时间粒度与趋势", "2024年和2025年的订单量分别是多少",
     "SELECT d.year, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "GROUP BY d.year ORDER BY d.year", 2),
    ("D-时间粒度与趋势", "2025年的总销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025", 1),
    ("D-时间粒度与趋势", "2025年11月的订单量是多少",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 AND d.month = 11", 1),
    ("D-时间粒度与趋势", "2025年第四季度的销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 AND d.quarter = 'Q4'", 1),
    ("D-时间粒度与趋势", "2025年各大区的销售额分别是多少",
     "SELECT r.region_name, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 GROUP BY r.region_name", 7),
    ("D-时间粒度与趋势", "2024年每个月的总销量分别是多少",
     "SELECT d.month, SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2024 GROUP BY d.month ORDER BY d.month", 12),

    # === E 时间 × 维度交叉 ===
    ("E-时间维度交叉", "2025年华东大区的销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 AND r.region_name = '华东'", 1),
    ("E-时间维度交叉", "2025年3月各商品品类的销售额分别是多少",
     "SELECT p.category, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE d.year = 2025 AND d.month = 3 GROUP BY p.category", 10),
    ("E-时间维度交叉", "2025年各会员等级的销售额分别是多少",
     "SELECT c.member_level, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_customer c ON f.customer_id = c.customer_id "
     "WHERE d.year = 2025 GROUP BY c.member_level", 4),
    ("E-时间维度交叉", "2025年各月华东大区的订单量分别是多少",
     "SELECT d.month, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 AND r.region_name = '华东' GROUP BY d.month ORDER BY d.month", 12),
    ("E-时间维度交叉", "2024年广东省的销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2024 AND r.province = '广东省'", 1),
    ("E-时间维度交叉", "2025年3月各品牌的销售额排名是怎样的（从高到低）",
     "SELECT p.brand, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE d.year = 2025 AND d.month = 3 GROUP BY p.brand ORDER BY total_amount DESC", 61),
    ("E-时间维度交叉", "2024年1月各大区的销量分别是多少",
     "SELECT r.region_name, SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2024 AND d.month = 1 GROUP BY r.region_name", 7),
    ("E-时间维度交叉", "2024年手机数码品类的销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE d.year = 2024 AND p.category = '手机数码'", 1),
    ("E-时间维度交叉", "2025年第四季度各品类的销售额分别是多少",
     "SELECT p.category, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE d.year = 2025 AND d.quarter = 'Q4' GROUP BY p.category", 10),
    ("E-时间维度交叉", "2024年第二季度各会员等级的订单量分别是多少",
     "SELECT c.member_level, COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_customer c ON f.customer_id = c.customer_id "
     "WHERE d.year = 2024 AND d.quarter = 'Q2' GROUP BY c.member_level", 4),

    # === F 条件过滤与 HAVING ===
    ("F-条件过滤", "订单金额超过5000元的订单有多少笔",
     "SELECT COUNT(f.order_id) AS order_count FROM fact_order f "
     "WHERE f.order_amount > 5000", 1),
    ("F-条件过滤", "铂金会员一共下了多少单",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "WHERE c.member_level = '铂金'", 1),
    ("F-条件过滤", "买过华为品牌商品的客户有多少人",
     "SELECT COUNT(DISTINCT f.customer_id) AS customer_count "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.brand = '华为'", 1),
    ("F-条件过滤", "广东省男性客户的订单量是多少",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE r.province = '广东省' AND c.gender = '男'", 1),
    ("F-条件过滤", "鞋靴品类中耐克品牌的销售额是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category = '鞋靴' AND p.brand = '耐克'", 1),
    ("F-条件过滤", "2025年销售额超过300万的省份分别是哪些",
     "SELECT r.province, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 GROUP BY r.province HAVING SUM(f.order_amount) > 3000000", 3),
    ("F-条件过滤", "买过休闲零食的女性客户有多少人",
     "SELECT COUNT(DISTINCT f.customer_id) AS customer_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category = '休闲零食' AND c.gender = '女'", 1),
    ("F-条件过滤", "2025年订单量超过2000的月份分别是哪几个",
     "SELECT d.month FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 GROUP BY d.month HAVING COUNT(f.order_id) > 2000", 5),

    # === G 占比与排除条件 ===
    ("G-占比与排除", "各品类的销售额占总销售额的百分比分别是多少（保留两位小数）",
     "SELECT p.category, ROUND(SUM(f.order_amount) / "
     "(SELECT SUM(f2.order_amount) FROM fact_order f2) * 100, 2) AS amount_ratio "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "GROUP BY p.category", 10),
    ("G-占比与排除", "手机数码品类的销售额占总销售额的百分比是多少（保留两位小数）",
     "SELECT ROUND(SUM(f.order_amount) / "
     "(SELECT SUM(f2.order_amount) FROM fact_order f2) * 100, 2) AS amount_ratio "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category = '手机数码'", 1),
    ("G-占比与排除", "华东大区的销售额占总销售额的百分比是多少（保留两位小数）",
     "SELECT ROUND(SUM(f.order_amount) / "
     "(SELECT SUM(f2.order_amount) FROM fact_order f2) * 100, 2) AS amount_ratio "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE r.region_name = '华东'", 1),
    ("G-占比与排除", "除手机数码外其他品类的销售额合计是多少",
     "SELECT SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category <> '手机数码'", 1),
    ("G-占比与排除", "除华东外其他大区的订单量合计是多少",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE r.region_name <> '华东'", 1),
    ("G-占比与排除", "2025年3月的销售额比2025年2月多多少",
     "SELECT SUM(CASE WHEN d.month = 3 THEN f.order_amount ELSE 0 END) - "
     "SUM(CASE WHEN d.month = 2 THEN f.order_amount ELSE 0 END) AS amount_diff "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025", 1),
    ("G-占比与排除", "2025年第四季度的订单量比第三季度多多少笔",
     "SELECT SUM(CASE WHEN d.quarter = 'Q4' THEN 1 ELSE 0 END) - "
     "SUM(CASE WHEN d.quarter = 'Q3' THEN 1 ELSE 0 END) AS order_diff "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025", 1),

    # === H 三表及以上关联 ===
    ("H-多表关联", "2025年3月华东大区各品类的销售额分别是多少",
     "SELECT p.category, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 AND d.month = 3 AND r.region_name = '华东' "
     "GROUP BY p.category", 10),
    ("H-多表关联", "各会员等级购买手机数码品类的销售额分别是多少",
     "SELECT c.member_level, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category = '手机数码' GROUP BY c.member_level", 4),
    ("H-多表关联", "2025年2月各会员等级的销售额分别是多少",
     "SELECT c.member_level, SUM(f.order_amount) AS total_amount "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 AND d.month = 2 GROUP BY c.member_level", 4),
    ("H-多表关联", "2025年广东省鞋靴品类的销量是多少",
     "SELECT SUM(f.order_quantity) AS total_quantity "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "JOIN dim_region r ON f.region_id = r.region_id "
     "WHERE d.year = 2025 AND r.province = '广东省' AND p.category = '鞋靴'", 1),
    ("H-多表关联", "各大区中购买过手机数码的客户数分别是多少",
     "SELECT r.region_name, COUNT(DISTINCT f.customer_id) AS customer_count "
     "FROM fact_order f JOIN dim_region r ON f.region_id = r.region_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE p.category = '手机数码' GROUP BY r.region_name", 7),

    # === I 易错边界（含"不许用当前年份"的专项题） ===
    # 这两条刻意不写年份：数据只到 2025-12-31，而系统当前是 2026 年。
    # 正确行为是只按 month 过滤、不补 year，否则会查空。
    ("I-易错边界", "1月份的订单量是多少",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.month = 1", 1),
    ("I-易错边界", "3月份销量最高的商品品类是哪个",
     "SELECT p.category FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "JOIN dim_product p ON f.product_id = p.product_id "
     "WHERE d.month = 3 GROUP BY p.category "
     "ORDER BY SUM(f.order_quantity) DESC LIMIT 1", 1),
    ("I-易错边界", "2025年各季度下过单的客户数分别是多少",
     "SELECT d.quarter, COUNT(DISTINCT f.customer_id) AS customer_count "
     "FROM fact_order f JOIN dim_date d ON f.date_id = d.date_id "
     "WHERE d.year = 2025 GROUP BY d.quarter ORDER BY d.quarter", 4),
    ("I-易错边界", "下单次数最多的客户一共下了多少单",
     "SELECT COUNT(f.order_id) AS order_count "
     "FROM fact_order f JOIN dim_customer c ON f.customer_id = c.customer_id "
     "GROUP BY c.customer_id ORDER BY order_count DESC LIMIT 1", 1),
    ("I-易错边界", "各会员等级的客户数分别是多少",
     "SELECT c.member_level, COUNT(c.customer_id) AS customer_count "
     "FROM dim_customer c GROUP BY c.member_level", 4),
    ("I-易错边界", "各商品品类下的商品数分别是多少",
     "SELECT p.category, COUNT(p.product_id) AS product_count "
     "FROM dim_product p GROUP BY p.category", 10),
]

# 从参考 SQL 里解析「表别名 → 表名」，再把 别名.列名 还原成 表名.列名
_ALIAS_PATTERN = re.compile(r"\b(?:from|join)\s+(\w+)(?:\s+(?:as\s+)?(\w+))?", re.IGNORECASE)
_QUALIFIED_COLUMN = re.compile(r"\b(\w+)\.(\w+)\b")
# SQL 关键字，避免把 `AS total` 之类误当作别名
_SQL_KEYWORDS = {
    "where", "group", "order", "on", "join", "inner", "left", "right", "outer",
    "having", "limit", "by", "as", "select", "and", "or", "desc", "asc", "case",
    "when", "then", "else", "end", "distinct", "union", "using",
}


def build_alias_map(sql: str) -> dict[str, str]:
    """解析 SQL 中的表别名：{"f": "fact_order", "r": "dim_region"}

    没有别名的表（from fact_order）会以表名本身作为键，方便统一处理。
    """
    alias_map: dict[str, str] = {}
    for table, alias in _ALIAS_PATTERN.findall(sql):
        # 形如 `from fact_order where ...` 时，第二组会匹配到 where，需要排除
        if alias and alias.lower() not in _SQL_KEYWORDS:
            alias_map[alias] = table
        alias_map.setdefault(table, table)
    return alias_map


def derive_reference_columns(sql: str, alias_map: dict[str, str]) -> list[str]:
    """从参考 SQL 推导 reference_columns（表.列），按出现顺序去重

    约定参考 SQL 里每个列都写成 别名.列名，因此这里只需把别名换成表名。
    这样标注永远不会与 SQL 脱节——手写标注才是 09 报告里错误的来源。
    """
    columns: list[str] = []
    for alias, column in _QUALIFIED_COLUMN.findall(sql):
        table = alias_map.get(alias)
        if table is None:
            raise ValueError(f"参考 SQL 里的别名 {alias!r} 未在 FROM/JOIN 中定义")
        qualified = f"{table}.{column}"
        if qualified not in columns:
            columns.append(qualified)
    return columns


async def main():
    parser = argparse.ArgumentParser(description="编译并校验评测集")
    parser.add_argument("--check-only", action="store_true", help="只校验，不写 dataset.jsonl")
    args = parser.parse_args()

    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    errors: list[str] = []
    output_lines: list[dict] = []

    try:
        async with meta_mysql_client_manager.session_factory() as meta_session:
            rows = (await meta_session.execute(text("select id from column_info"))).fetchall()
            meta_columns = {row[0] for row in rows}

        async with dw_mysql_client_manager.session_factory() as dw_session:
            repository = DWMySQLRepository(dw_session)

            for index, (category, query, sql, expected_rows) in enumerate(CASES, start=1):
                label = f"第 {index} 条「{query}」"

                try:
                    alias_map = build_alias_map(sql)
                    reference_columns = derive_reference_columns(sql, alias_map)
                except ValueError as e:
                    errors.append(f"{label}：{e}")
                    continue

                unknown = [c for c in reference_columns if c not in meta_columns]
                if unknown:
                    errors.append(f"{label}：SQL 引用了 meta 中不存在的字段 {unknown}")

                try:
                    result = await repository.execute_sql(sql)
                except Exception as e:
                    errors.append(f"{label}：参考 SQL 执行失败 {type(e).__name__}: {e}")
                    continue

                if not result:
                    errors.append(f"{label}：参考 SQL 返回空结果（废题）")
                    continue

                if len(result) != expected_rows:
                    errors.append(
                        f"{label}：声明期望 {expected_rows} 行，实际返回 {len(result)} 行"
                        f"（多半是分组粒度写错了）")

                output_lines.append({
                    "query": query,
                    "reference_sql": sql,
                    "reference_columns": reference_columns,
                    "category": category,
                    "expected_rows": expected_rows,
                })
    finally:
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()

    print(f"题目总数: {len(CASES)}，通过校验: {len(output_lines)}")
    if errors:
        print(f"\n发现 {len(errors)} 个问题（未产出文件）:")
        for message in errors:
            print(f"  ✗ {message}")
        sys.exit(1)

    if args.check_only:
        print("--check-only：未写入文件")
        return

    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        for line in output_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"已写入: {OUTPUT}")

    from collections import Counter
    print("\n题型分布:")
    for category, count in sorted(Counter(c[0] for c in CASES).items()):
        print(f"  {category:<20} {count:>3} 条")


if __name__ == "__main__":
    asyncio.run(main())
