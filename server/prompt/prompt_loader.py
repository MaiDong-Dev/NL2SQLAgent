# =============================================================================
# 【提示词构造模块】Prompt 模板加载器
# 作用：从项目 prompts/ 目录加载 .prompt 模板文件，将 Prompt 模板与业务代码
#       解耦，便于非开发人员（如数据分析师）独立维护和调优 Prompt。
# 上下文传递：各 Agent 节点通过 prompt 名称调用 load_prompt() 获取模板文本，
#            再使用 LangChain 的 PromptTemplate 注入变量后发送给 LLM。
# =============================================================================

from pathlib import Path


def load_prompt(name: str) -> str:
    """从 prompts 目录加载指定名称的 Prompt 模板文件
    
    设计意图：
    - Prompt 模板独立于代码，存放在 prompts/ 目录下
    - 模板文件使用 .prompt 后缀，便于 IDE 识别和语法高亮
    - 支持变量占位符 {variable_name}，由 LangChain PromptTemplate 填充
    
    路径解析：
    - __file__ 是当前文件路径 (server/prompt/prompt_loader.py)
    - parents[2] 向上两级到项目根目录
    - 拼接 prompts/{name}.prompt 得到完整路径
    
    使用示例：
        template = load_prompt("generate_sql")
        # 返回 prompts/generate_sql.prompt 的完整内容
    """
    prompt_path = Path(__file__).parents[2] / 'prompts' / f'{name}.prompt'
    return prompt_path.read_text(encoding='utf-8')
if __name__  == "__main__":

    print(load_prompt("generate_sql"))