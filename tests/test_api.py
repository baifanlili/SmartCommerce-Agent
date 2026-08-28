from fastapi.testclient import TestClient
import pytest

from smart_commerce.main import app
from smart_commerce.agents.shopping_agents import ShoppingSupervisor
from smart_commerce.services.llm_provider import MockLLMProvider


@pytest.fixture(scope="module")
def client():
    app.state.settings.admin_token = "test-admin-token"
    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, MockLLMProvider())
    with TestClient(app) as test_client:
        yield test_client
    app.state.settings.admin_token = None


def test_liveness_does_not_require_redis(client) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_readiness_reports_service_state(client) -> None:
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)
    payload = response.json()
    assert payload["service"] == "api"
    if response.status_code == 503:
        assert payload["status"] == "degraded"
        assert payload["redis"] == "unavailable"


def test_response_headers_include_request_chain_ids(client) -> None:
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "req-123", "X-Trace-ID": "trace-456"},
    )
    assert response.headers["x-request-id"] == "req-123"
    assert response.headers["x-trace-id"] == "trace-456"


def test_request_chain_ids_are_generated_when_absent(client) -> None:
    response = client.get("/health/live")
    request_id = response.headers["x-request-id"]
    assert request_id
    assert response.headers["x-trace-id"] == request_id


def test_validation_error_is_structured(client) -> None:
    response = client.post("/api/v1/chat", json={"session_id": "", "message": ""})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["details"]


def test_not_found_error_is_structured(client) -> None:
    response = client.get("/api/v1/not-found")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == response.headers["x-request-id"]


def test_products_can_be_filtered_by_budget(client) -> None:
    response = client.get("/api/v1/products", params={"max_price": 5000, "category": "Laptop"})
    assert response.status_code == 200
    products = response.json()
    assert products
    assert all(item["price"] <= 5000 for item in products)


def test_chat_returns_agent_steps_and_recommendations(client) -> None:
    response = client.post("/api/v1/chat", json={"session_id": "test-session", "message": "推荐一台5000元以内适合程序员的笔记本"})
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-trace-id"]
    payload = response.json()
    assert payload["mode"] == "mock"
    assert payload["intent"] == {
        "name": "product_recommendation",
        "raw_message": "推荐一台5000元以内适合程序员的笔记本",
        "filters": {"max_price": 5000.0, "category": "Laptop", "keywords": ["程序员"]},
    }
    assert len(payload["steps"]) == 3
    assert payload["recommendations"][0]["name"] == "ThinkPad T14 Gen 5"


def test_admin_config_requires_token(client) -> None:
    response = client.get("/api/v1/admin/llm-config")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_admin_config_is_masked_and_can_be_enabled(client) -> None:
    headers = {"X-Admin-Token": "test-admin-token"}
    save_response = client.post(
        "/api/v1/admin/llm-config",
        headers=headers,
        json={
            "provider": "deepseek",
            "api_key": "test-secret-key",
            "model": "deepseekflash",
            "base_url": "https://example.test/v1",
            "api_mode": "responses",
            "timeout_seconds": 15,
            "max_retries": 1,
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["api_key_configured"] is True
    assert saved["api_key_masked"] == "tes...key"
    assert "test-secret-key" not in save_response.text

    enable_response = client.post("/api/v1/admin/llm-config/enable", headers=headers)

    assert enable_response.status_code == 200
    assert enable_response.json()["is_active"] is True
    assert app.state.supervisor.llm_provider.name == "deepseek"

    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, MockLLMProvider())


def test_admin_config_test_failure_does_not_enable_draft(client, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = {"X-Admin-Token": "test-admin-token"}

    class FailingProvider:
        name = "deepseek"

        async def generate_reply(self, message, products):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        app.state.llm_config_store,
        "build_provider",
        lambda *_args, **_kwargs: FailingProvider(),
    )
    response = client.post(
        "/api/v1/admin/llm-config/test",
        headers=headers,
        json={"provider": "deepseek", "api_key": "candidate-key"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": False, "message": "连接测试失败，当前配置未启用", "mode": "mock"}
