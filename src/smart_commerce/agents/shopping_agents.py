import re
import logging

from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import AgentStep, Product, ProductSearchResult, ShoppingFilters, ShoppingIntent
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.llm_provider import LLMProvider, LLMProviderError, MockLLMProvider, build_llm_provider

logger = logging.getLogger(__name__)


class ProductAgent:
    name = "product"
    label = "商品检索"

    _category_map = {
        "笔记本": "Laptop",
        "电脑": "Laptop",
        "手机": "Phone",
        "耳机": "Audio",
        "显示器": "Monitor",
    }
    _preference_keywords = ("程序员", "游戏", "办公", "便携", "摄影", "学生")

    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    def understand(self, message: str) -> ShoppingIntent:
        return ShoppingIntent(
            raw_message=message,
            filters=ShoppingFilters(
                max_price=self._extract_budget(message),
                category=self._extract_category(message),
                keywords=[keyword for keyword in self._preference_keywords if keyword in message],
            ),
        )

    def search(self, intent: ShoppingIntent) -> ProductSearchResult:
        products = self.repository.list_products(
            max_price=intent.filters.max_price,
            category=intent.filters.category,
        )
        if not products and intent.filters.max_price is not None:
            products = self.repository.list_products(category=intent.filters.category)
        return ProductSearchResult(intent=intent, products=products[:3])

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
        for keyword, category in ProductAgent._category_map.items():
            if keyword in message:
                return category
        return None


class ShoppingSupervisor:
    def __init__(self, repository: ProductRepository, llm_provider: LLMProvider | None = None) -> None:
        self.product_agent = ProductAgent(repository)
        self.llm_provider = llm_provider or MockLLMProvider()

    async def run(self, message: str) -> tuple[str, ProductSearchResult, list[AgentStep], str]:
        intent = self.product_agent.understand(message)
        search_result = self.product_agent.search(intent)
        mode = "mock" if self.llm_provider.name == "mock" else "llm"
        try:
            reply = await self.llm_provider.generate_reply(message, search_result.products)
        except LLMProviderError:
            logger.warning("llm_reply_failed provider=%s fallback=mock", self.llm_provider.name, exc_info=True)
            reply = await MockLLMProvider().generate_reply(message, search_result.products)
            mode = "mock"
        steps = [
            AgentStep(agent="supervisor", label="需求理解"),
            AgentStep(agent="product", label="商品检索"),
            AgentStep(agent="recommend", label="智能推荐"),
        ]
        return reply, search_result, steps, mode


def supervisor_from_settings(repository: ProductRepository, settings: Settings) -> ShoppingSupervisor:
    provider = build_llm_provider(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_mode=settings.llm_api_mode,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return ShoppingSupervisor(repository, provider)
