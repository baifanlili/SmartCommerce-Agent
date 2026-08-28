import logging

from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import AgentStep, Product, ProductSearchResult, ShoppingIntent
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.intent_parser import parse_shopping_intent
from smart_commerce.services.llm_provider import LLMProvider, LLMProviderError, MockLLMProvider, build_llm_provider

logger = logging.getLogger(__name__)


class ProductAgent:
    name = "product"
    label = "商品检索"

    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    def understand(self, message: str) -> ShoppingIntent:
        return parse_shopping_intent(message)

    def search(self, intent: ShoppingIntent) -> ProductSearchResult:
        products = self.repository.list_products(
            max_price=intent.filters.max_price,
            category=intent.filters.category,
        )
        if not products and intent.filters.max_price is not None:
            products = self.repository.list_products(category=intent.filters.category)
        return ProductSearchResult(intent=intent, products=products[:3])

class ShoppingSupervisor:
    def __init__(self, repository: ProductRepository, llm_provider: LLMProvider | None = None) -> None:
        self.product_agent = ProductAgent(repository)
        self.llm_provider = llm_provider or MockLLMProvider()

    async def run(self, message: str) -> tuple[str, ProductSearchResult, list[AgentStep], str]:
        active_provider = self.llm_provider
        mode = "mock" if active_provider.name == "mock" else "llm"
        try:
            intent = await active_provider.extract_intent(message)
        except LLMProviderError as exc:
            logger.warning(
                "llm_fallback provider=%s fallback=mock operation=intent reason=provider_error error_code=%s error_type=%s",
                active_provider.name,
                exc.code,
                type(exc).__name__,
            )
            active_provider = MockLLMProvider()
            intent = await active_provider.extract_intent(message)
            mode = "mock"

        search_result = self.product_agent.search(intent)
        try:
            reply = await active_provider.generate_reply(message, search_result.products)
        except LLMProviderError as exc:
            logger.warning(
                "llm_fallback provider=%s fallback=mock operation=reply reason=provider_error error_code=%s error_type=%s",
                active_provider.name,
                exc.code,
                type(exc).__name__,
            )
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
