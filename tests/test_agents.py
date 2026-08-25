from smart_commerce.agents.shopping_agents import ProductAgent
from smart_commerce.repositories.product_repository import ProductRepository


def test_product_agent_extracts_budget_and_category() -> None:
    agent = ProductAgent(ProductRepository())
    products = agent.search("我想买一台5000元以内的程序员笔记本")
    assert products
    assert all(product.category == "Laptop" for product in products)
    assert all(product.price <= 5000 for product in products)


def test_product_agent_extracts_budget_before_within_suffix() -> None:
    agent = ProductAgent(ProductRepository())
    products = agent.search("推荐一台5000元以内适合程序员的笔记本")
    assert products
    assert products[0].name == "ThinkPad T14 Gen 5"
    assert all(product.price <= 5000 for product in products)
