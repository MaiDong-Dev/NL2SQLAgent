# =============================================================================
# 【提示词构造模块】补充额外上下文节点
# 作用：在生成 SQL 之前，补充 LLM 需要的环境信息：
#       1. 当前日期/星期/季度——帮助 LLM 理解"本月"、"最近三个月"等相对时间
#       2. 数据真实覆盖的日期范围——避免 LLM 用系统当前年份去过滤历史数据
#          （数据只到 2025 年底而系统当前是 2026 年时，"1月份"会被补成 year=2026）
#       3. 数据库类型和版本——帮助 LLM 生成符合特定数据库方言的 SQL
# 上下文传递：
#   - 输入：无（独立计算，不依赖上游 state）
#   - 中间：runtime.context["dw_mysql_repository"] → 查询数据库版本与数据日期范围
#   - 输出：{"date_info": {...}, "db_info": {...}} → 传给 generate_sql
# 设计意图：
#   - 日期信息是动态的（随运行时间变化），不能硬编码在 Prompt 中
#   - 数据库方言信息来自实际连接，确保 LLM 生成正确的 SQL 语法
# =============================================================================

from datetime import datetime

from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import DataAgentState, DateInfoState
from server.core.log import logger


async def add_extra_context(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "添加额外上下文信息", "status": "running"})

    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    try:
        # 当前的时间信息
        today = datetime.today()
        # 日期：格式 YYYY-MM-DD，如 "2025-01-15"
        date = today.strftime("%Y-%m-%d")
        # 星期：英文全称，如 "Wednesday"
        weekday = today.strftime("%A")
        # 季度：格式 Q1/Q2/Q3/Q4
        quarter = f"Q{(today.month - 1) // 3 + 1}"

        # 数据真实覆盖的日期范围。
        # 单独 try/except 降级：这一步只是"锦上添花"的上下文，
        # 查不到不应该把整条问句打挂，给个空范围让下游按"无信息"处理即可。
        try:
            data_range = await dw_mysql_repository.get_data_date_range()
        except Exception as e:
            logger.warning(f"获取数据时间范围失败，降级为空范围: {e}")
            data_range = {"start": None, "end": None}

        date_info = DateInfoState(date=date, weekday=weekday, quarter=quarter,
                                  data_range=data_range)

        # 数据仓库环境信息（数据库类型 + 版本号）
        db_info = await dw_mysql_repository.get_db_info()

        writer({"type": "progress", "step": "添加额外上下文信息", "status": "success"})
        logger.info(f"额外上下文信息：数据库信息-{db_info} 日期信息-{date_info}")
        return {
            "date_info": date_info,
            "db_info": db_info,
        }
    except Exception as e:
        writer({"type": "progress", "step": "添加额外上下文信息", "status": "error"})
        logger.error(f"添加上下文失败:{str(e)}")
        raise