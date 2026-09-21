# =============================================================================
# 【接口层集成测试】POST /api/query
# 需要真实中间件：MySQL（meta/dw）+ Qdrant + ES + Embedding 服务 + DeepSeek Key。
#
# 默认跳过，手动开启：
#   Windows:  set RUN_INTEGRATION=1 && .venv\Scripts\python.exe -m pytest tests/integration -m integration
#   Linux:    RUN_INTEGRATION=1 pytest tests/integration -m integration
#
# 前置：先启动 deploy/docker-compose.yaml 里的中间件。
# =============================================================================

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="集成测试需真实中间件，设置 RUN_INTEGRATION=1 后执行",
    ),
]


def test_query_endpoint_returns_answer_for_simple_question():
    """冒烟：一条最简问句应能通过完整链路拿到回答（不校验答案正确性）"""
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        response = client.post("/api/query", json={"query": "一共有多少个客户"})

    assert response.status_code == 200
    assert response.text.strip(), "响应体为空，链路未产出任何内容"
