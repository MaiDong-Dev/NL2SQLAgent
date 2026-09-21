# =============================================================================
# 【提示词层测试】server/prompt
# 覆盖：prompts/*.prompt 模板是否可加载、是否含占位符、缺失模板的报错行为。
# 特点：纯文件读取，不调用 LLM。
# =============================================================================

from pathlib import Path

import pytest

from server.prompt.prompt_loader import load_prompt

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"

PROMPT_FILES = sorted(PROMPTS_DIR.glob("*.prompt"))


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
