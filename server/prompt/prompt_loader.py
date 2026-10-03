# =============================================================================
# 【提示词构造模块】Prompt 模板加载器
# 作用：从项目 prompts/ 目录加载 .prompt 模板文件，将 Prompt 模板与业务代码
#       解耦，便于非开发人员独立维护和调优 Prompt。
# 上下文传递：各 Agent 节点通过 prompt 名称调用 load_prompt() 获取模板文本，
#            再使用 LangChain 的 PromptTemplate 注入变量后发送给 LLM。
# 使用示例：
#       template = load_prompt("generate_sql")
#       print(template)  返回 prompts/generate_sql.prompt 的完整内容
# =============================================================================

from pathlib import Path


def load_prompt(name: str) -> str:
    """加载指定名称的 Prompt 模板文件"""
    prompt_path = Path(__file__).parents[2] / 'prompts' / f'{name}.prompt'
    return prompt_path.read_text(encoding='utf-8')
if __name__  == "__main__":

    print(load_prompt("generate_sql"))