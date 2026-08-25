from fastapi.testclient import TestClient

from smart_commerce.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_products_can_be_filtered_by_budget() -> None:
    response = client.get("/api/v1/products", params={"max_price": 5000, "category": "Laptop"})
    assert response.status_code == 200
    products = response.json()
    assert products
    assert all(item["price"] <= 5000 for item in products)


def test_chat_returns_agent_steps_and_recommendations() -> None:
    response = client.post("/api/v1/chat", json={"session_id": "test-session", "message": "推荐一台5000元以内适合程序员的笔记本"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "mock"
    assert len(payload["steps"]) == 3
    assert payload["recommendations"][0]["name"] == "ThinkPad T14 Gen 5"
