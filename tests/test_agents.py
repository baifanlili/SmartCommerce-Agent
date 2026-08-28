from smart_commerce.agents.shopping_agents import ProductAgent
from smart_commerce.repositories.product_repository import ProductRepository


def test_product_agent_extracts_budget_and_category() -> None:
    agent = ProductAgent(ProductRepository())
    intent = agent.understand("我想买一台5000元以内的程序员笔记本")

    assert intent.name == "product_recommendation"
    assert intent.filters.max_price == 5000
    assert intent.filters.category == "Laptop"
    assert intent.filters.keywords == ["程序员"]


def test_product_agent_extracts_budget_before_within_suffix() -> None:
    agent = ProductAgent(ProductRepository())
    intent = agent.understand("推荐一台5000元以内适合程序员的笔记本")
    result = agent.search(intent)

    assert result.intent == intent
    assert result.products
    assert result.products[0].name == "ThinkPad T14 Gen 5"
    assert all(product.price <= 5000 for product in result.products)
