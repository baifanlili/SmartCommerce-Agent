import re

from smart_commerce.models.schemas import AgentStep, Product
from smart_commerce.repositories.product_repository import ProductRepository


class ProductAgent:
    name = "product"
    label = "商品检索"

    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    def search(self, message: str) -> list[Product]:
        max_price = self._extract_budget(message)
        category = self._extract_category(message)
        products = self.repository.list_products(max_price=max_price, category=category)
        if not products and max_price is not None:
            products = self.repository.list_products(category=category)
        return products[:3]

    @staticmethod
    def _extract_budget(message: str) -> float | None:
        match = re.search(r"(?:低于|不超过|预算|不高于)\s*[¥￥]?\s*(\d+(?:\.\d+)?)", message)
        if not match:
            match = re.search(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|以下|封顶)", message)
        if not match:
            match = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", message)
        return float(match.group(1)) if match else None

    @staticmethod
    def _extract_category(message: str) -> str | None:
        category_map = {"笔记本": "Laptop", "电脑": "Laptop", "手机": "Phone", "耳机": "Audio", "显示器": "Monitor"}
        for keyword, category in category_map.items():
            if keyword in message:
                return category
        return None


class RecommendAgent:
    name = "recommend"
    label = "智能推荐"

    def explain(self, message: str, products: list[Product]) -> str:
        if not products:
            return "我暂时没有找到完全匹配的商品，可以放宽预算或换一个品类试试。"
        budget = ProductAgent._extract_budget(message)
        budget_text = f"，并控制在 ¥{budget:,.0f} 以内" if budget else ""
        names = "、".join(product.name for product in products)
        return f"我根据你的需求{budget_text}筛选了 {names}。优先推荐列表中的第一款，它在评分、核心配置和价格之间更均衡。"


class ShoppingSupervisor:
    def __init__(self, repository: ProductRepository) -> None:
        self.product_agent = ProductAgent(repository)
        self.recommend_agent = RecommendAgent()

    def run(self, message: str) -> tuple[str, list[Product], list[AgentStep]]:
        products = self.product_agent.search(message)
        reply = self.recommend_agent.explain(message, products)
        steps = [
            AgentStep(agent="supervisor", label="需求理解"),
            AgentStep(agent="product", label="商品检索"),
            AgentStep(agent="recommend", label="智能推荐"),
        ]
        return reply, products, steps
