from fastapi.testclient import TestClient
import pytest

from smart_commerce.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


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
    assert len(payload["steps"]) == 3
    assert payload["recommendations"][0]["name"] == "ThinkPad T14 Gen 5"
