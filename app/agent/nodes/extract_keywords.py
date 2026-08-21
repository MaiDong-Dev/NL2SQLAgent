# =============================================================================
# 【提示词构造模块】关键词提取节点
# 作用：使用 jieba 分词 + 词性过滤，从用户自然语言查询中提取核心关键词，
#       作为后续召回节点（向量检索、ES 全文检索）的检索种子。
# 上下文传递：
#   - 输入：state["query"]  → 用户原始查询
#   - 输出：{"keywords": [...]} → 合并到 state，供下游三个召回节点使用
# 设计意图：
#   - 不使用 LLM 做关键词提取（避免延迟和成本），而是用轻量级的 jieba 分词
#   - 通过词性过滤（allowPOS）只保留名词、动词、形容词等信息量大的词
#   - 同时保留原始查询作为兜底关键词，确保不丢失关键信息
# =============================================================================

import jieba.analyse
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def extract_keywords(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "抽取关键字", "status": "running"})

    query = state["query"]

    # 词性过滤：只保留以下词性的词，过滤掉无意义的虚词、标点等
    # 设计意图：TF-IDF 算法本身会过滤停用词，但词性过滤可以进一步
    # 去除"的"、"是"、"在"等高频但无信息量的词
    allow_pos = (
        "n",  # 名词: 数据、服务器、表格
        "nr",  # 人名: 张三、李四
        "ns",  # 地名: 北京、上海
        "nt",  # 机构团体名: 政府、学校、某公司
        "nz",  # 其他专有名词: Unicode、哈希算法、诺贝尔奖
        "v",  # 动词: 运行、开发
        "vn",  # 名动词: 工作、研究
        "a",  # 形容词: 美丽、快速
        "an",  # 名形词: 难度、合法性、复杂度
        "eng",  # 英文
        "i",  # 成语
        "l",  # 常用固定短语
    )

    # 使用 jieba 的 TF-IDF 算法提取关键词
    # extract_tags 内部会计算 TF-IDF，自动过滤停用词和低权重词
    keywords = jieba.analyse.extract_tags(query, allowPOS=allow_pos)

    # 去重 + 保留原始查询作为兜底关键词
    # 目的：即使 jieba 分词结果不理想，原始查询也能作为检索关键词
    keywords = list(set(keywords + [query]))

    writer({"type": "progress", "step": "抽取关键字", "status": "success"})
    logger.info(f"抽取关键字: {keywords}")
    return {"keywords": keywords}