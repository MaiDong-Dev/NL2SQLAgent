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

import asyncio

import jieba.analyse
from langgraph.runtime import Runtime

from server.agent.context import DataAgentContext
from server.agent.state import DataAgentState
from server.core.log import logger


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


if __name__ == "__main__":

    # =============================================================================
    # 【本地自测入口】直接调用节点函数，验证关键词提取效果（无需启动图/外部服务）
    #
    # 运行方式（在项目根目录执行）：
    #   python -m server.agent.nodes.extract_keywords
    #
    # 说明：
    #   - 节点函数依赖 runtime.stream_writer 推送进度事件，这里用打印函数替代
    #     真实的 LangGraph StreamWriter，便于观察事件流
    #   - DataAgentState 是 TypedDict，运行时等价于 dict，测试只需提供 query 字段
    #   - Runtime 是 dataclass，本节点只用 stream_writer，其余字段保持默认/空值
    # =============================================================================

    async def _extract(query: str) -> list[str]:
        """执行一次关键词提取，返回提取结果"""
        state: DataAgentState = {"query": query}  # 构造最小可用 state

        def stream_writer(chunk: dict) -> None:
            """模拟 LangGraph 的 stream_writer，把进度事件打印出来"""
            print(f"  [stream] {chunk}")

        runtime: Runtime[DataAgentContext] = Runtime(context=None, stream_writer=stream_writer)

        result = await extract_keywords(state, runtime)
        return result["keywords"]


    async def _main():
        # 覆盖常见查询形态：长句/短句、含时间/地名/人名、纯英文、纯虚词
        test_queries = [
            "查询上个月北京地区销售额最高的前10个商品",
            "统计2024年每个季度的活跃用户数",
            "张三的订单记录",
            "订单",
            "GMV",
            "我想看一下",
        ]

        for query in test_queries:
            keywords = await _extract(query)
            print(f"查询: {query}\n  关键词: {keywords}")

            # 校验 1：原始查询必须作为兜底关键词保留
            assert query in keywords, f"原始查询未保留: {query}"
            # 校验 2：关键词不应重复（list(set(...)) 去重）
            assert len(keywords) == len(set(keywords)), f"关键词存在重复: {keywords}"

        print("\n全部用例通过")


    asyncio.run(_main())

