"""pytest 全局配置。

作用：把项目根目录加入 sys.path，保证 tests/ 下可以直接 import server.*、eval.*、meta_builder.*
（与 pyproject.toml 中的 pythonpath 配置双保险，兼容直接执行 pytest 的情况）。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
