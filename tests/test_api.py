import json

from fastapi.testclient import TestClient
import pytest

from smart_commerce.main import app
from smart_commerce.agents.shopping_agents import ShoppingSupervisor
from smart_commerce.core.config import Settings
from smart_commerce.core.identity import IdentityContext
from smart_commerce.services.llm_provider import LLMProviderError, MockLLMProvider
from smart_commerce.services.runtime_config import RuntimeLLMConfigStore
from smart_commerce.services.session_memory import SessionMemory


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if event_type and data_lines:
            events.append({"type": event_type, "data": json.loads("\n".join(data_lines))})
    return events

@pytest.fixture()
def client(tmp_path):
    app.state.settings.admin_token = "test-admin-token"
    app.state.settings.environment = "development"
    app.state.settings.identity_mode = "development"
    app.state.settings.identity_gateway_token = None
    store = RuntimeLLMConfigStore(
        Settings(
            _env_file=None,
            environment="development",
            llm_provider="mock",
            runtime_config_db_path=str(tmp_path / "runtime-config.sqlite3"),
        )
    )
    app.state.llm_config_store = store
    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, store.build_provider())
    with TestClient(app) as test_client:
        yield test_client
    app.state.settings.admin_token = None
    app.state.settings.environment = "development"
    app.state.settings.identity_mode = "development"
    app.state.settings.identity_gateway_token = None
    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, MockLLMProvider())


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

def test_chat_stream_emits_sse_events_with_chain_ids(client) -> None:
    response = client.post(
        "/api/v1/chat/stream",
        headers={"X-Request-ID": "stream-req-1", "X-Trace-ID": "stream-trace-1"},
        json={"session_id": "stream-session", "message": "推荐一台5000元以内适合程序员的笔记本"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-request-id"] == "stream-req-1"
    assert response.headers["x-trace-id"] == "stream-trace-1"
    events = _parse_sse(response.text)
    types = [event["type"] for event in events]
    assert types[0] == "step"
    assert types.count("step") == 6
    assert "delta" in types
    assert types[-1] == "done"
    assert all(event["data"]["request_id"] == "stream-req-1" for event in events)
    assert all(event["data"]["trace_id"] == "stream-trace-1" for event in events)
    delta_text = "".join(event["data"]["text"] for event in events if event["type"] == "delta")
    done = events[-1]["data"]
    assert done["session_id"] == "stream-session"
    assert delta_text == done["reply"]
    assert done["mode"] == "mock"
    assert done["intent"]["name"] == "product_recommendation"
    assert done["intent"]["filters"]["max_price"] == 5000.0
    assert len(done["steps"]) == 3
    assert done["recommendations"][0]["name"] == "ThinkPad T14 Gen 5"


def test_chat_stream_emits_error_event_when_supervisor_fails(client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_stream(message):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(app.state.supervisor, "stream_run", failing_stream)
    response = client.post(
        "/api/v1/chat/stream",
        json={"session_id": "stream-error", "message": "推荐笔记本"},
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[-1]["type"] == "error"
    error = events[-1]["data"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["trace_id"] == response.headers["x-trace-id"]


def test_development_chat_uses_anonymous_identity_without_headers(client) -> None:
    response = client.post("/api/v1/chat", json={"session_id": "anonymous-session", "message": "推荐笔记本"})

    assert response.status_code == 200


def test_chat_rejects_identity_fields_in_request_body(client) -> None:
    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": "test-session",
            "message": "推荐笔记本",
            "user_id": "forged-user",
            "tenant_id": "forged-tenant",
            "role": "admin",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_gateway_identity_requires_server_configuration(client) -> None:
    app.state.settings.environment = "production"
    app.state.settings.identity_gateway_token = None

    response = client.post("/api/v1/chat", json={"session_id": "production-session", "message": "推荐笔记本"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "IDENTITY_AUTH_NOT_CONFIGURED"


def test_gateway_identity_rejects_invalid_token(client) -> None:
    app.state.settings.environment = "production"
    app.state.settings.identity_gateway_token = "trusted-gateway-token"

    response = client.post(
        "/api/v1/chat",
        headers={"X-Agent-Identity-Token": "wrong-token"},
        json={"session_id": "production-session", "message": "推荐笔记本"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "IDENTITY_TOKEN_INVALID"


def test_gateway_identity_requires_verified_context_headers(client) -> None:
    app.state.settings.environment = "production"
    app.state.settings.identity_gateway_token = "trusted-gateway-token"

    response = client.post(
        "/api/v1/chat",
        headers={"X-Agent-Identity-Token": "trusted-gateway-token"},
        json={"session_id": "production-session", "message": "推荐笔记本"},
    )

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "IDENTITY_CONTEXT_INVALID"
    assert error["details"] == [{"field": "user_id", "message": "必须是 1-128 位的字母、数字、点、下划线或连字符"}]


def test_gateway_identity_accepts_trusted_headers_and_preserves_trace_id(client) -> None:
    app.state.settings.environment = "production"
    app.state.settings.identity_gateway_token = "trusted-gateway-token"

    response = client.post(
        "/api/v1/chat",
        headers={
            "X-Agent-Identity-Token": "trusted-gateway-token",
            "X-Agent-User-ID": "user-10001",
            "X-Agent-Tenant-ID": "tenant-demo",
            "X-Agent-Role": "user",
            "X-Agent-Scopes": "agent:chat,memory:read:self",
            "X-Trace-ID": "trace-from-gateway",
        },
        json={"session_id": "production-session", "message": "推荐笔记本"},
    )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-from-gateway"


def test_session_storage_key_isolated_by_tenant_and_user() -> None:
    session_id = "same-session"
    first = IdentityContext(user_id="user-a", tenant_id="tenant-a", role="user", trace_id="trace-a")
    second = IdentityContext(user_id="user-b", tenant_id="tenant-a", role="user", trace_id="trace-b")
    third = IdentityContext(user_id="user-a", tenant_id="tenant-b", role="user", trace_id="trace-c")

    assert SessionMemory.storage_key(first, session_id) == "smart-commerce:session:tenant-a:user-a:same-session"
    assert SessionMemory.storage_key(first, session_id) != SessionMemory.storage_key(second, session_id)
    assert SessionMemory.storage_key(first, session_id) != SessionMemory.storage_key(third, session_id)


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
            "expected_version": 1,
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["api_key_configured"] is True
    assert saved["api_key_masked"] == "tes...key"
    assert "test-secret-key" not in save_response.text
    assert saved["draft_version"] == 2
    assert saved["active_version"] == 1

    enable_response = client.post(
        "/api/v1/admin/llm-config/enable",
        headers=headers,
        json={"expected_version": saved["active_version"]},
    )

    assert enable_response.status_code == 200
    enabled = enable_response.json()
    assert enabled["is_active"] is True
    assert enabled["draft_version"] == 2
    assert enabled["active_version"] == 2
    assert app.state.supervisor.llm_provider.name == "deepseek"

    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, MockLLMProvider())


def test_admin_config_save_conflict_returns_409(client) -> None:
    headers = {"X-Admin-Token": "test-admin-token"}
    payload = {
        "provider": "deepseek",
        "api_key": "candidate-key",
        "model": "deepseekflash",
        "base_url": "https://example.test/v1",
        "api_mode": "chat",
        "timeout_seconds": 15,
        "max_retries": 1,
        "expected_version": 1,
    }
    first = client.post("/api/v1/admin/llm-config", headers=headers, json=payload)
    assert first.status_code == 200

    stale = client.post("/api/v1/admin/llm-config", headers=headers, json=payload)

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "CONFIG_VERSION_CONFLICT"
    assert error["details"][0]["message"] == "当前版本为 2"
    assert "candidate-key" not in stale.text


def test_admin_config_enable_conflict_returns_409(client) -> None:
    headers = {"X-Admin-Token": "test-admin-token"}
    save = client.post(
        "/api/v1/admin/llm-config",
        headers=headers,
        json={
            "provider": "deepseek",
            "api_key": "candidate-key",
            "expected_version": 1,
        },
    )
    assert save.status_code == 200
    enable = client.post(
        "/api/v1/admin/llm-config/enable",
        headers=headers,
        json={"expected_version": 1},
    )
    assert enable.status_code == 200

    stale = client.post(
        "/api/v1/admin/llm-config/enable",
        headers=headers,
        json={"expected_version": 1},
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFIG_VERSION_CONFLICT"

    app.state.supervisor = ShoppingSupervisor(app.state.product_repository, MockLLMProvider())


def test_admin_config_test_failure_does_not_enable_draft(client, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = {"X-Admin-Token": "test-admin-token"}
    was_active = app.state.llm_config_store.view().is_active
    draft_version = app.state.llm_config_store.view().draft_version

    class FailingProvider:
        name = "deepseek"

        async def generate_reply(self, message, products):
            raise LLMProviderError(
                "LLM_TIMEOUT",
                "provider unavailable",
                status_code=504,
                public_message="模型服务响应超时",
                retryable=True,
            )

    monkeypatch.setattr(
        app.state.llm_config_store,
        "build_provider",
        lambda *_args, **_kwargs: FailingProvider(),
    )
    response = client.post(
        "/api/v1/admin/llm-config/test",
        headers=headers,
        json={"provider": "deepseek", "api_key": "candidate-key", "expected_version": draft_version},
    )

    assert response.status_code == 504
    error = response.json()["error"]
    assert error["code"] == "LLM_TIMEOUT"
    assert error["message"] == "模型服务响应超时"
    assert error["request_id"] == response.headers["x-request-id"]
    assert "candidate-key" not in response.text
    assert app.state.llm_config_store.view().is_active is was_active
