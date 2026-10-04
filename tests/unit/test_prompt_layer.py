# =============================================================================
# 【提示词层测试】server/prompt
# 覆盖：prompts/*.prompt 模板是否可加载、是否含占位符、缺失模板的报错行为，
#       以及「模板占位符」与「节点声明的 input_variables」是否一致。
# 特点：纯文件读取 + 源码 AST 解析，不 import 节点模块（那会拉起 app_config 与 LLM 客户端，
#       让单元测试依赖运行环境），因此零依赖、可离线跑。
# =============================================================================

import ast
import re
from pathlib import Path

import pytest

from server.prompt.prompt_loader import load_prompt

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"

PROMPT_FILES = sorted(PROMPTS_DIR.glob("*.prompt"))

# 节点源码 → 它加载的 prompt 模板名
NODE_PROMPTS = {
    ROOT / "server" / "agent" / "nodes" / "generate_sql.py": "generate_sql",
    ROOT / "server" / "agent" / "nodes" / "correct_sql.py": "correct_sql",
}


def _placeholders(template: str) -> set[str]:
    """抽出模板里的 {变量名}"""
    return set(re.findall(r"\{(\w+)\}", template))


def _declared_input_variables(module_path: Path) -> list[str]:
    """从节点源码里读出 PromptTemplate(input_variables=[...]) 的字面量

    用 AST 而不是 import：import 节点会连带加载 app_config 与 LLM 客户端，
    单元测试不该依赖运行环境。
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if func_name != "PromptTemplate":
            continue
        for keyword in node.keywords:
            if keyword.arg == "input_variables" and isinstance(keyword.value, ast.List):
                return [e.value for e in keyword.value.elts if isinstance(e, ast.Constant)]
    return []


def test_prompts_directory_is_not_empty():
    """提示词是与业务代码解耦的资产，目录为空说明打包/部署漏拷"""
    assert PROMPT_FILES, f"{PROMPTS_DIR} 下没有任何 .prompt 模板"


@pytest.mark.parametrize("prompt_path", PROMPT_FILES, ids=lambda p: p.stem)
def test_every_prompt_is_loadable(prompt_path: Path):
    """节点按名称加载模板，任何一个读不到都会在运行时炸在 LLM 调用前"""
    text = load_prompt(prompt_path.stem)
    assert text.strip(), f"{prompt_path.name} 内容为空"
    assert len(text) > 50, f"{prompt_path.name} 内容过短，疑似被截断"


def test_sql_generation_prompt_has_placeholders():
    """生成 SQL 的模板必须带变量占位符，否则无法注入召回字段与问句"""
    text = load_prompt("generate_sql")
    assert "{" in text and "}" in text


def test_unknown_prompt_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_prompt("this_prompt_does_not_exist")


@pytest.mark.parametrize("module_path,prompt_name", NODE_PROMPTS.items(),
                         ids=lambda v: v.name if isinstance(v, Path) else v)
def test_declared_input_variables_match_template(module_path: Path, prompt_name: str):
    """节点声明的 input_variables 必须与模板占位符完全一致

    回归护栏：correct_sql.py 曾把 7 个占位符的模板只声明了 2 个
    （input_variables=["query", "metric_infos"]），却传了 7 个变量。
    该节点只在 SQL 校验失败时才走到，所以一直没暴露——正是这类"低频路径的声明漂移"
    需要靠测试而不是靠运行来发现。
    """
    declared = set(_declared_input_variables(module_path))
    placeholders = _placeholders(load_prompt(prompt_name))

    assert declared, f"{module_path.name} 里没有解析到 PromptTemplate(input_variables=...)"
    assert declared == placeholders, (
        f"{prompt_name} 模板占位符与 {module_path.name} 声明的 input_variables 不一致：\n"
        f"  模板有但未声明: {sorted(placeholders - declared)}\n"
        f"  声明了但模板没有: {sorted(declared - placeholders)}"
    )


def test_generate_sql_prompt_carries_data_range_rule():
    """数据真实时间范围必须出现在 prompt 里

    这是"用系统当前年份过滤未指定年份的问句"这一缺陷的修复点：
    实测该缺陷会让同一问句连跑 5 次产生 4 个不同 SQL（含 3 次错误的 year=<当前年>）。
    """
    text = load_prompt("generate_sql")
    assert "data_range" in text, "generate_sql 模板没有引用数据范围字段"
    assert "未指定" in text or "未显式" in text, "缺少「未指定年份」的约束说明"


def test_correct_sql_prompt_carries_same_year_rule():
    """校正节点同样会改写 SQL，必须有相同的年份约束，否则会把错误年份固化下来"""
    text = load_prompt("correct_sql")
    assert "data_range" in text
    assert "年份" in text
