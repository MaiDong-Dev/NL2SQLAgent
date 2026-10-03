# =============================================================================
# 【工具模块】时间维度语义识别
# 作用：判断用户问句是否需要时间维度支撑，以及识别元数据中的「时间维度表」。
#       供 merge_retrieved_info（补全时间维表字段）与 filter_table（强制保留时间维表）共用。
# 设计意图（为什么要这套确定性规则）：
#   向量召回依赖字段名的业务语义，而时间维表字段（year / quarter / month）语义极弱，
#   几乎召不回来。缺了时间维表，SQL 生成阶段就只能退化成对事实表日期键做算术或字符串
#   格式化（实测出现过 `date_id DIV 100`、`DATE_FORMAT(STR_TO_DATE(date_id,...))`），
#   结果口径错误。因此这里沿用「主外键补全」的思路，用规则做补偿。
# =============================================================================

import re

# 问句中出现以下任一模式，即认为需要时间维度支撑
# （覆盖：2025年 / 年 / 月 / 季度 / 周 / 日期 / 最近 / 近3天 / 今年 / 本月 / Q1 / year...）
_TIME_QUERY_PATTERN = re.compile(
    r"\d{4}\s*年"
    r"|年(?!龄)"          # 排除"年龄/年龄段"这类误命中（注意用前瞻：龄在年之后）
    r"|季度|月份|月|周|日期|时间"
    r"|最近|近\s*\d|今年|去年|本月|上月|本周|上周|今日|昨日|当天|截至"
    r"|Q[1-4]"
    r"|year|month|quarter|week|date",
    re.IGNORECASE,
)

# 时间维度表的判定依据：一张维表同时具备以下时间粒度字段中的至少 2 个
_TIME_GRAIN_COLUMN_NAMES = {"year", "quarter", "month"}

# 显式年份：四位数后面必须跟"年"（如 2025年 / 2024 年）。
# 不能只匹配四位数——「订单量超过2000的月份」里的 2000 是阈值不是年份，
# 要求"年"后缀才能把两者分开。代价是"2025"这种省略"年"的写法识别不到，
# 但那只会让歧义检查多报一条 WARN（提示性的），比误判成越界 FAIL 安全。
_YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}\s*年")


def has_time_semantic(query: str) -> bool:
    """判断用户问句是否包含时间维度语义"""
    return bool(_TIME_QUERY_PATTERN.search(query or ""))


def extract_years(query: str) -> list[int]:
    """提取问句中显式写出的年份（形如"2025年"），按出现顺序去重"""
    years = []
    for match in _YEAR_PATTERN.finditer(query or ""):
        year = int(re.sub(r"\D", "", match.group()))
        if year not in years:
            years.append(year)
    return years


def has_explicit_year(query: str) -> bool:
    """判断问句是否显式写出了年份（如"2025年"）

    用途：出题校验。含时间语义但没写年份的问句（"1月份的订单量是多少"），
    答案取决于模型如何推断年份，属歧义题，需要出题人确认是否有意为之——
    实测这类题曾因模型用系统当前年份补全而查空，是评测噪声的主要来源之一。
    """
    return bool(_YEAR_PATTERN.search(query or ""))


def is_time_dimension_table(column_names) -> bool:
    """根据字段名集合判断是否为时间维度表（年/季/月至少命中 2 个）"""
    return len(set(column_names) & _TIME_GRAIN_COLUMN_NAMES) >= 2
