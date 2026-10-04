# =============================================================================
# 【安全模块】SQL 只读门禁
# 作用：在 SQL 真正打到数据仓库之前做一道**代码级**的只读校验，拦截任何可能
#       改写数据或拖垮库的语句。
#
# 为什么必须有这一层：
#   - `generate_sql` 的"只能查询、不能写操作"只是 **Prompt 约束**（见
#     `prompts/generate_sql.prompt`），LLM 不保证遵守，且受输入诱导可能写出 DML/DDL。
#   - `validate_sql` 用 `EXPLAIN` 验证，而 MySQL 的 `EXPLAIN DELETE/UPDATE` 是
#     **合法语句**、能解析通过 —— 也就是说 EXPLAIN 这道门禁拦不住写操作。
#   - 结果就是：模型只要生成一条 DELETE，流程会一路绿灯走到 `execute_sql` 真删数据。
#
# 因此本模块提供**白名单 + 黑名单**双重校验，作为执行前最后一道硬门禁：
#   1. 白名单：语句必须以 SELECT / WITH 开头（CTE 也允许）
#   2. 多语句拦截：去掉末尾分号后不允许再出现 `;`
#   3. 黑名单：任何位置出现写操作、DDL、权限、文件导出、系统库访问等关键词一律拒绝
#
# 设计约束：本模块是**纯函数**（不依赖会话、配置、网络），便于离线单测。
# =============================================================================

import re

# 允许的语句开头（小写判断）。WITH 用于支持 CTE：`with t as (select ...) select ...`
ALLOWED_PREFIXES = ("select", "with")

# 命中即拒绝的关键词（正则，匹配时不区分大小写，均为词级匹配）
# 说明：这里用"任何位置出现即拒绝"的严格策略，宁可误杀也不放过——
# 因为本系统只做只读问数，合法业务 SQL 根本不会包含这些词。
FORBIDDEN_PATTERNS = (
    # 写操作 / DDL / 权限
    # 说明：`replace` 只拦 `REPLACE INTO`（写操作），不拦 REPLACE() 字符串函数；
    # 其余词用词边界匹配，因此不会误杀 created_at / updated_at 这类字段名。
    r"\b(insert|update|delete|truncate|drop|alter|create|rename)\b",
    r"\breplace\s+into\b",
    r"\b(grant|revoke|set|lock|unlock|call|handler|shutdown)\b",
    # 文件读写与外带（MySQL 的 SELECT ... INTO OUTFILE 也能写文件）
    r"\b(load_file|outfile|dumpfile|load_data)\b",
    # 系统库/元数据探测
    r"\b(mysql|information_schema|performance_schema|sys)\s*\.",
    # 耗时/DoS 型函数（防止一条 SQL 拖死整库）
    r"\b(sleep|benchmark)\s*\(",
)

_COMMENT_PATTERN = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)
_FORBIDDEN_RE = re.compile("|".join(FORBIDDEN_PATTERNS), re.IGNORECASE)


def strip_sql_comments(sql: str) -> str:
    """去掉 SQL 中的单行注释（--）与块注释（/* */），保留原语义的换行位置

    必须在校验前调用：否则 `/* x */ delete` 这类带注释夹带的写法会绕过前缀判断。
    """
    return _COMMENT_PATTERN.sub(" ", sql)


def check_read_only(sql: str) -> str | None:
    """校验 SQL 是否为安全的只读查询语句

    参数：
    - sql: 待校验的 SQL 文本（通常来自 LLM 生成）

    返回：
    - None：通过校验，可以执行
    - str：拒绝原因（可直接写进日志或回传给 LLM 修正）
    """
    if not isinstance(sql, str) or not sql.strip():
        return "SQL 为空"

    # 先去注释，再去掉首尾空白与末尾分号（LLM 常在结尾带一个 `;`）
    cleaned = strip_sql_comments(sql).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if not cleaned:
        return "SQL 为空"

    # 多语句拦截：`select 1; delete from t` 是最典型的注入形态
    if ";" in cleaned:
        return "检测到多条语句（含分号），只允许单条查询"

    lowered = cleaned.lower()

    # 白名单：允许以 ( 开头的括号包裹写法，去掉括号后再判前缀
    prefix = lowered.lstrip("(")
    if not prefix.startswith(ALLOWED_PREFIXES):
        return f"只允许 SELECT / WITH 开头的查询语句，实际以 {cleaned[:20]!r} 开头"

    # 黑名单：任何位置命中即拒绝
    matched = _FORBIDDEN_RE.search(cleaned)
    if matched:
        return f"包含禁止的语句或关键词：{matched.group(0)!r}"

    return None


def assert_read_only(sql: str) -> None:
    """校验失败时直接抛异常（供 execute_sql 之类"必须拦住"的场景使用）"""
    reason = check_read_only(sql)
    if reason is not None:
        raise ValueError(f"SQL 只读校验未通过：{reason}")
