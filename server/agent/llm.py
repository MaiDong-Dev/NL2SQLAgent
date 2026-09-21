# =============================================================================
# 【LLM 调用模块】大语言模型客户端
# 作用：统一初始化和管理 LLM 连接，作为整个 Agent 管线中唯一的 LLM 调用入口。
#       所有需要 LLM 推理的节点（关键词扩展、召回、过滤、SQL 生成、SQL 校正）
#       都通过此模块的 llm 实例进行调用。
# 上下文传递：作为模块级单例，各节点直接 import llm 使用，无需通过 Context 传递。
# =============================================================================

from langchain.chat_models import init_chat_model

from server.conf.app_config import app_config

# 初始化 LLM 客户端（全局单例）
# 使用 OpenAI 兼容接口，支持任意兼容 OpenAI API 的模型服务（如 vLLM、DeepSeek 等）
# temperature=0：确保输出确定性，每次相同输入产生相同输出，适合 SQL 生成场景
llm = init_chat_model(model=app_config.llm.model_name,
                      model_provider="openai",
                      api_key=app_config.llm.api_key,
                      base_url=app_config.llm.base_url,
                      temperature=0)


if __name__ == '__main__':
    for chunk in llm.stream("What is the meaning of life?"):
        print(chunk.text)