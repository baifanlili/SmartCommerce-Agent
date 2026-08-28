import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from smart_commerce.models.schemas import Product, ShoppingIntent
from smart_commerce.services.intent_parser import parse_shopping_intent

logger = logging.getLogger(__name__)


LLMProviderErrorCode = Literal[
    "LLM_CONFIG_ERROR",
    "LLM_AUTH_ERROR",
    "LLM_REQUEST_ERROR",
    "LLM_RATE_LIMITED",
    "LLM_UPSTREAM_ERROR",
    "LLM_NETWORK_ERROR",
    "LLM_TIMEOUT",
    "LLM_RESPONSE_INVALID",
]


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot produce a usable answer."""

    def __init__(
        self,
        code: LLMProviderErrorCode,
        message: str,
        *,
        status_code: int,
        public_message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.public_message = public_message
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str

    async def extract_intent(self, message: str) -> ShoppingIntent:
        """Extract a validated shopping intent from the user message."""

    async def generate_reply(self, message: str, products: list[Product]) -> str:
        """Generate a shopping explanation for the selected products."""


def _response_invalid_error(message: str) -> LLMProviderError:
    return LLMProviderError(
        "LLM_RESPONSE_INVALID",
        message,
        status_code=502,
        public_message="模型服务返回结果异常",
    )


def _http_error(exc: httpx.HTTPStatusError) -> LLMProviderError:
    status_code = exc.response.status_code
    if status_code in {401, 403}:
        return LLMProviderError(
            "LLM_AUTH_ERROR",
            f"DeepSeek authentication failed with status {status_code}",
            status_code=502,
            public_message="模型服务认证失败",
        )
    if status_code == 429:
        return LLMProviderError(
            "LLM_RATE_LIMITED",
            "DeepSeek rate limit exceeded",
            status_code=503,
            public_message="模型服务当前繁忙，请稍后重试",
            retryable=True,
        )
    if status_code >= 500:
        return LLMProviderError(
            "LLM_UPSTREAM_ERROR",
            f"DeepSeek upstream failed with status {status_code}",
            status_code=502,
            public_message="模型服务暂时不可用",
            retryable=True,
        )
    return LLMProviderError(
        "LLM_REQUEST_ERROR",
        f"DeepSeek request failed with status {status_code}",
        status_code=502,
        public_message="模型服务请求无效",
    )


def _transport_error(exc: httpx.TimeoutException | httpx.NetworkError) -> LLMProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMProviderError(
            "LLM_TIMEOUT",
            "DeepSeek request timed out",
            status_code=504,
            public_message="模型服务响应超时",
            retryable=True,
        )
    return LLMProviderError(
        "LLM_NETWORK_ERROR",
        "DeepSeek network connection failed",
        status_code=503,
        public_message="模型服务网络连接失败",
        retryable=True,
    )


def _extract_usage(data: object) -> tuple[int | None, int | None, int | None]:
    if not isinstance(data, dict):
        return None, None, None

    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None, None, None

    def read_count(*keys: str) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                return value
        return None

    return (
        read_count("prompt_tokens", "input_tokens"),
        read_count("completion_tokens", "output_tokens"),
        read_count("total_tokens"),
    )


def _log_llm_call(
    *,
    outcome: Literal["completed", "failed"],
    provider: str,
    model: str,
    api_mode: str,
    duration_ms: float,
    attempts: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_type: str | None = None,
    error_code: LLMProviderErrorCode | None = None,
) -> None:
    message = (
        f"llm_call_{outcome} provider=%s model=%s api_mode=%s duration_ms=%.1f "
        "attempts=%d retries=%d prompt_tokens=%s completion_tokens=%s total_tokens=%s"
    )
    values: tuple[object, ...] = (
        provider,
        model,
        api_mode,
        duration_ms,
        attempts,
        max(attempts - 1, 0),
        prompt_tokens,
        completion_tokens,
        total_tokens,
    )
    if outcome == "failed":
        logger.warning(
            f"{message} error_type=%s error_code=%s",
            *values,
            error_type or "UnknownError",
            error_code or "UNKNOWN_ERROR",
        )
        return
    logger.info(message, *values)


def _extract_responses_text(data: object) -> str:
    if not isinstance(data, dict):
        raise _response_invalid_error("DeepSeek returned an invalid Responses payload")

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = data.get("output")
    if isinstance(output, list):
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
        if text_parts:
            return "\n".join(text_parts)

    raise _response_invalid_error("DeepSeek returned an empty Responses output")


def _extract_chat_text(data: object) -> str:
    if not isinstance(data, dict):
        raise _response_invalid_error("DeepSeek returned an invalid Chat payload")

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise _response_invalid_error("DeepSeek returned an invalid Chat payload") from exc

    if not isinstance(content, str) or not content.strip():
        raise _response_invalid_error("DeepSeek returned an empty Chat response")
    return content.strip()


def _parse_shopping_intent_json(content: str) -> ShoppingIntent:
    normalized = content.strip()
    fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", normalized, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        normalized = fenced_match.group(1).strip()

    try:
        return ShoppingIntent.model_validate(json.loads(normalized))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _response_invalid_error("DeepSeek returned an invalid shopping intent JSON") from exc


def _mock_reply(message: str, products: list[Product]) -> str:
    if not products:
        return "我暂时没有找到完全匹配的商品，可以放宽预算或换一个品类试试。"

    budget_match = re.search(r"(?:低于|不超过|预算|不高于)\s*[¥￥]?\s*(\d+(?:\.\d+)?)", message)
    if not budget_match:
        budget_match = re.search(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|以下|封顶)", message)
    budget = float(budget_match.group(1)) if budget_match else None
    budget_text = f"，并控制在 ¥{budget:,.0f} 以内" if budget else ""
    names = "、".join(product.name for product in products)
    return f"我根据你的需求{budget_text}筛选了 {names}。优先推荐列表中的第一款，它在评分、核心配置和价格之间更均衡。"


@dataclass(frozen=True)
class MockLLMProvider:
    name: str = "mock"

    async def extract_intent(self, message: str) -> ShoppingIntent:
        started = time.perf_counter()
        intent = parse_shopping_intent(message)
        _log_llm_call(
            outcome="completed",
            provider=self.name,
            model="rule_based",
            api_mode="local",
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=1,
        )
        return intent

    async def generate_reply(self, message: str, products: list[Product]) -> str:
        started = time.perf_counter()
        reply = _mock_reply(message, products)
        _log_llm_call(
            outcome="completed",
            provider=self.name,
            model="rule_based",
            api_mode="local",
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=1,
        )
        return reply


@dataclass(frozen=True)
class DeepSeekProvider:
    api_key: str
    model: str = "deepseekflash"
    base_url: str = "https://api.deepseek.com/v1"
    api_mode: Literal["chat", "responses"] = "chat"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    name: str = "deepseek"

    async def extract_intent(self, message: str) -> ShoppingIntent:
        content = await self._generate_text(
            "你是 SmartCommerce 的购物意图解析器。只返回一个合法 JSON 对象，不要 Markdown、解释或额外字段。"
            "JSON 必须符合以下结构："
            '{"name":"product_recommendation","raw_message":"用户原始诉求","filters":'
            '{"max_price":数字或 null,"category":"Laptop 或 Phone 或 Audio 或 Monitor 或 null",'
            '"keywords":["偏好关键词"]}}。'
            "raw_message 必须原样保留用户诉求；未识别的筛选条件使用 null 或空数组。",
            f"用户诉求：{message}",
        )
        return _parse_shopping_intent_json(content)

    async def generate_reply(self, message: str, products: list[Product]) -> str:
        product_context = json.dumps(
            [product.model_dump() for product in products],
            ensure_ascii=False,
        )
        system_prompt = (
            "你是 SmartCommerce 的购物研究助手。请基于给定商品结果回答用户，"
            "只能使用商品数据中存在的事实，不要编造库存、优惠或参数。"
            "用简洁自然的中文说明推荐理由；如果没有结果，请建议用户放宽条件。"
        )
        return await self._generate_text(system_prompt, f"用户需求：{message}\n候选商品 JSON：{product_context}")

    async def _generate_text(self, system_prompt: str, user_prompt: str) -> str:
        started = time.perf_counter()
        attempts = 0
        if not self.api_key:
            error = LLMProviderError(
                "LLM_CONFIG_ERROR",
                "DeepSeek API key is not configured",
                status_code=503,
                public_message="模型服务配置不完整",
            )
            _log_llm_call(
                outcome="failed",
                provider=self.name,
                model=self.model,
                api_mode=self.api_mode,
                duration_ms=(time.perf_counter() - started) * 1000,
                attempts=attempts,
                error_type=type(error).__name__,
                error_code=error.code,
            )
            raise error

        if self.api_mode == "responses":
            payload = {
                "model": self.model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            url = f"{self.base_url.rstrip('/')}/responses"
        else:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "stream": False,
            }
            url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: LLMProviderError | None = None
        last_cause: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    attempts = attempt + 1
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    prompt_tokens, completion_tokens, total_tokens = _extract_usage(data)
                    if self.api_mode == "responses":
                        text = _extract_responses_text(data)
                    else:
                        text = _extract_chat_text(data)
                    _log_llm_call(
                        outcome="completed",
                        provider=self.name,
                        model=self.model,
                        api_mode=self.api_mode,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        attempts=attempts,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )
                    return text
                except httpx.HTTPStatusError as exc:
                    last_error = _http_error(exc)
                    last_cause = exc
                except httpx.TimeoutException as exc:
                    last_error = _transport_error(exc)
                    last_cause = exc
                except httpx.NetworkError as exc:
                    last_error = _transport_error(exc)
                    last_cause = exc
                except LLMProviderError as exc:
                    last_error = exc
                    last_cause = exc.__cause__ if isinstance(exc.__cause__, Exception) else None
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    last_error = _response_invalid_error("DeepSeek returned an invalid response payload")
                    last_cause = exc

                if not last_error.retryable or attempt >= self.max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 4))

        _log_llm_call(
            outcome="failed",
            provider=self.name,
            model=self.model,
            api_mode=self.api_mode,
            duration_ms=(time.perf_counter() - started) * 1000,
            attempts=attempts,
            error_type=type(last_cause).__name__ if last_cause else "LLMProviderError",
            error_code=last_error.code if last_error else "LLM_UPSTREAM_ERROR",
        )
        if last_error is None:
            last_error = LLMProviderError(
                "LLM_UPSTREAM_ERROR",
                "DeepSeek request failed without a response",
                status_code=502,
                public_message="模型服务暂时不可用",
            )
        raise last_error from last_cause


def build_llm_provider(
    provider: str,
    api_key: str | None,
    model: str | None,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    api_mode: Literal["chat", "responses"] = "chat",
) -> LLMProvider:
    normalized = provider.strip().lower()
    if normalized == "mock":
        return MockLLMProvider()
    if normalized in {"deepseek", "deepseekflash", "deepseek_flash"}:
        return DeepSeekProvider(
            api_key=api_key or "",
            model=model or "deepseekflash",
            base_url=base_url,
            api_mode=api_mode,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    logger.warning("unknown_llm_provider provider=%s fallback=mock", provider)
    return MockLLMProvider()
