import asyncio
import logging
from typing import Literal, cast

import httpx
import pytest
from pydantic import ValidationError

from smart_commerce.agents.shopping_agents import ShoppingSupervisor
from smart_commerce.core.config import Settings
from smart_commerce.models.schemas import Product, ShoppingIntent
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.llm_provider import (
    DeepSeekProvider,
    LLMProviderError,
    LLMProviderErrorCode,
    MockLLMProvider,
    build_llm_provider,
)


class FakeSuccessResponse:
    def __init__(self, data: object) -> None:
        self.data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.data


class CapturingClient:
    response_data: object = {"choices": [{"message": {"content": "Chat reply"}}]}
    requests: list[tuple[str, dict[str, object]]] = []

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "CapturingClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> FakeSuccessResponse:
        self.requests.append((url, kwargs["json"]))  # type: ignore[arg-type]
        return FakeSuccessResponse(self.response_data)


def _product() -> Product:
    return Product(
        id=1,
        name="Test Laptop",
        category="Laptop",
        brand="Test",
        price=4999,
        rating=4.8,
        review_count=100,
        tags=["coding"],
        highlights=["16GB RAM"],
        description="A test product",
    )


def _intent_json(message: str = "推荐一台5000元以内适合程序员的笔记本") -> str:
    return (
        '{"name":"product_recommendation","raw_message":"'
        f'{message}'
        '","filters":{"max_price":5000,"category":"Laptop","keywords":["程序员"]}}'
    )


def _provider_error(
    code: LLMProviderErrorCode = "LLM_UPSTREAM_ERROR",
    *,
    retryable: bool = False,
) -> LLMProviderError:
    return LLMProviderError(
        code,
        "test provider failure",
        status_code=502,
        public_message="模型服务暂时不可用",
        retryable=retryable,
    )


def test_settings_use_chat_as_default_api_mode() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_api_mode == "chat"


@pytest.mark.parametrize(
    "field, value",
    [
        ("llm_timeout_seconds", 0),
        ("llm_timeout_seconds", 301),
        ("llm_max_retries", -1),
        ("llm_max_retries", 6),
    ],
)
def test_settings_reject_unsafe_retry_configuration(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_build_deepseek_provider_uses_default_flash_model() -> None:
    provider = build_llm_provider(
        provider="deepseek",
        api_key="test-key",
        model=None,
        base_url="https://api.deepseek.com/v1",
        timeout_seconds=30,
        max_retries=2,
    )

    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "deepseekflash"
    assert provider.api_mode == "chat"


def test_build_deepseek_provider_accepts_responses_mode() -> None:
    provider = build_llm_provider(
        provider="deepseek",
        api_key="test-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        timeout_seconds=30,
        max_retries=2,
        api_mode="responses",
    )

    assert isinstance(provider, DeepSeekProvider)
    assert provider.api_mode == "responses"


def test_deepseek_chat_mode_uses_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    CapturingClient.requests = []
    CapturingClient.response_data = {"choices": [{"message": {"content": "Chat reply"}}]}
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)

    provider = DeepSeekProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        api_mode="chat",
    )
    reply = asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert reply == "Chat reply"
    url, payload = CapturingClient.requests[0]
    assert url == "https://example.test/v1/chat/completions"
    assert payload["model"] == "deepseekflash"
    assert "messages" in payload
    assert "input" not in payload


@pytest.mark.parametrize(
    "response_data, expected",
    [
        ({"output_text": "Responses reply"}, "Responses reply"),
        (
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "First part"},
                            {"type": "output_text", "text": "Second part"},
                        ],
                    }
                ]
            },
            "First part\nSecond part",
        ),
    ],
)
def test_deepseek_responses_mode_uses_responses_payload(
    monkeypatch: pytest.MonkeyPatch,
    response_data: object,
    expected: str,
) -> None:
    CapturingClient.requests = []
    CapturingClient.response_data = response_data
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)

    provider = DeepSeekProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        api_mode="responses",
    )
    reply = asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert reply == expected
    url, payload = CapturingClient.requests[0]
    assert url == "https://example.test/v1/responses"
    assert payload["model"] == "deepseekflash"
    assert "input" in payload
    assert "messages" not in payload


def test_deepseek_responses_empty_output_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    CapturingClient.requests = []
    CapturingClient.response_data = {"output": []}
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)

    provider = DeepSeekProvider(api_key="test-key", api_mode="responses", max_retries=0)

    with pytest.raises(LLMProviderError, match="empty Responses output") as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert exc_info.value.code == "LLM_RESPONSE_INVALID"
    assert exc_info.value.status_code == 502
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    "api_mode, response_data",
    [
        ("chat", {"choices": [{"message": {"content": f"```json\n{_intent_json()}\n```"}}]}),
        ("responses", {"output_text": _intent_json()}),
    ],
)
def test_deepseek_extract_intent_parses_chat_and_responses_json(
    monkeypatch: pytest.MonkeyPatch,
    api_mode: str,
    response_data: object,
) -> None:
    CapturingClient.requests = []
    CapturingClient.response_data = response_data
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    provider = DeepSeekProvider(api_key="test-key", api_mode=cast(Literal["chat", "responses"], api_mode))

    intent = asyncio.run(provider.extract_intent("推荐一台5000元以内适合程序员的笔记本"))

    assert isinstance(intent, ShoppingIntent)
    assert intent.filters.max_price == 5000
    assert intent.filters.category == "Laptop"
    assert intent.filters.keywords == ["程序员"]
    _, payload = CapturingClient.requests[0]
    assert "购物意图解析器" in str(payload)


@pytest.mark.parametrize(
    "api_mode, response_data",
    [
        ("chat", {"choices": [{"message": {"content": ""}}]}),
        ("responses", {"output": []}),
    ],
)
def test_deepseek_extract_intent_rejects_empty_output(
    monkeypatch: pytest.MonkeyPatch,
    api_mode: str,
    response_data: object,
) -> None:
    CapturingClient.response_data = response_data
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    provider = DeepSeekProvider(
        api_key="test-key",
        api_mode=cast(Literal["chat", "responses"], api_mode),
        max_retries=0,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.extract_intent("推荐笔记本"))

    assert exc_info.value.code == "LLM_RESPONSE_INVALID"
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    "api_mode, response_data",
    [
        ("chat", {"choices": [{"message": {"content": "not-json"}}]}),
        ("responses", {"output_text": '{"filters": {}}'}),
    ],
)
def test_deepseek_extract_intent_rejects_invalid_json_or_schema(
    monkeypatch: pytest.MonkeyPatch,
    api_mode: str,
    response_data: object,
) -> None:
    CapturingClient.response_data = response_data
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    provider = DeepSeekProvider(
        api_key="test-key",
        api_mode=cast(Literal["chat", "responses"], api_mode),
        max_retries=0,
    )

    with pytest.raises(LLMProviderError, match="invalid shopping intent JSON") as exc_info:
        asyncio.run(provider.extract_intent("推荐笔记本"))

    assert exc_info.value.code == "LLM_RESPONSE_INVALID"
    assert exc_info.value.retryable is False


def test_supervisor_falls_back_to_mock_when_provider_fails() -> None:
    class FailingProvider:
        name = "deepseek"

        async def extract_intent(self, message: str) -> ShoppingIntent:
            raise _provider_error()

        async def generate_reply(self, message: str, products: list[Product]) -> str:
            raise _provider_error()

    supervisor = ShoppingSupervisor(ProductRepository(), FailingProvider())
    reply, search_result, steps, mode = asyncio.run(supervisor.run("推荐一台5000元以内的笔记本"))

    assert search_result.products
    assert reply
    assert len(steps) == 3
    assert mode == "mock"


def test_supervisor_does_not_use_llm_reply_after_intent_fallback() -> None:
    class InvalidIntentProvider:
        name = "deepseek"

        async def extract_intent(self, message: str) -> ShoppingIntent:
            raise _provider_error("LLM_RESPONSE_INVALID")

        async def generate_reply(self, message: str, products: list[Product]) -> str:
            raise AssertionError("reply generation should use Mock after intent fallback")

    supervisor = ShoppingSupervisor(ProductRepository(), InvalidIntentProvider())
    reply, search_result, _, mode = asyncio.run(supervisor.run("推荐一台5000元以内的笔记本"))

    assert reply
    assert search_result.products
    assert mode == "mock"


def test_supervisor_uses_the_provider_structured_intent_for_search() -> None:
    class StructuredProvider:
        name = "deepseek"

        async def extract_intent(self, message: str) -> ShoppingIntent:
            return ShoppingIntent(
                raw_message=message,
                filters={"max_price": 5000, "category": "Laptop", "keywords": ["模型解析"]},
            )

        async def generate_reply(self, message: str, products: list[Product]) -> str:
            return "模型推荐结果"

    supervisor = ShoppingSupervisor(ProductRepository(), StructuredProvider())
    reply, search_result, _, mode = asyncio.run(supervisor.run("随便推荐一台电脑"))

    assert reply == "模型推荐结果"
    assert search_result.intent.filters.keywords == ["模型解析"]
    assert search_result.products
    assert mode == "llm"


def test_mock_provider_keeps_deterministic_reply() -> None:
    provider = MockLLMProvider()
    reply = asyncio.run(provider.generate_reply("推荐一台5000元以内的笔记本", [_product()]))

    assert "Test Laptop" in reply


def test_mock_provider_returns_the_deterministic_shopping_intent() -> None:
    provider = MockLLMProvider()

    intent = asyncio.run(provider.extract_intent("推荐一台5000元以内适合程序员的笔记本"))

    assert intent == ShoppingIntent.model_validate_json(_intent_json())


def test_supervisor_reports_mock_mode_for_mock_provider() -> None:
    supervisor = ShoppingSupervisor(ProductRepository(), MockLLMProvider())
    _, search_result, steps, mode = asyncio.run(supervisor.run("推荐一台5000元以内的笔记本"))

    assert search_result.products
    assert len(steps) == 3
    assert mode == "mock"


def test_deepseek_does_not_retry_authentication_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class UnauthorizedResponse:
        def raise_for_status(self) -> None:
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> UnauthorizedResponse:
            nonlocal calls
            calls += 1
            return UnauthorizedResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    provider = DeepSeekProvider(api_key="test-key", max_retries=2)

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert calls == 1
    assert exc_info.value.code == "LLM_AUTH_ERROR"
    assert exc_info.value.status_code == 502
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_status", "retryable"),
    [
        (400, "LLM_REQUEST_ERROR", 502, False),
        (403, "LLM_AUTH_ERROR", 502, False),
        (429, "LLM_RATE_LIMITED", 503, True),
        (500, "LLM_UPSTREAM_ERROR", 502, True),
    ],
)
def test_deepseek_http_errors_have_stable_contract(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_code: LLMProviderErrorCode,
    expected_status: int,
    retryable: bool,
) -> None:
    calls = 0

    class FailingResponse:
        def raise_for_status(self) -> None:
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(status_code, request=request)
            raise httpx.HTTPStatusError("provider failure", request=request, response=response)

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FailingResponse:
            nonlocal calls
            calls += 1
            return FailingResponse()

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    provider = DeepSeekProvider(api_key="test-key", max_retries=1)

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == expected_status
    assert exc_info.value.retryable is retryable
    assert calls == (2 if retryable else 1)


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: httpx.ReadTimeout("timed out"),
        lambda: httpx.NetworkError("network down"),
    ],
    ids=["timeout", "network"],
)
def test_deepseek_retries_transient_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: object,
) -> None:
    calls = 0
    waits: list[float] = []

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeSuccessResponse:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise error_factory()  # type: ignore[operator]
            return FakeSuccessResponse({"choices": [{"message": {"content": "recovered"}}]})

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    provider = DeepSeekProvider(api_key="test-key", max_retries=2)

    assert asyncio.run(provider.generate_reply("推荐笔记本", [_product()])) == "recovered"
    assert calls == 3
    assert waits == [1, 2]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_deepseek_retries_rate_limit_and_server_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    calls = 0
    waits: list[float] = []

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeSuccessResponse:
            nonlocal calls
            calls += 1
            if calls < 3:
                request = httpx.Request("POST", "https://example.test/chat/completions")
                response = httpx.Response(status_code, request=request)
                raise httpx.HTTPStatusError("temporary failure", request=request, response=response)
            return FakeSuccessResponse({"choices": [{"message": {"content": "recovered"}}]})

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    provider = DeepSeekProvider(api_key="test-key", max_retries=2)

    assert asyncio.run(provider.generate_reply("推荐笔记本", [_product()])) == "recovered"
    assert calls == 3
    assert waits == [1, 2]


def test_deepseek_stops_after_configured_retry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    waits: list[float] = []

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeSuccessResponse:
            nonlocal calls
            calls += 1
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    async def fake_sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    provider = DeepSeekProvider(api_key="test-key", max_retries=1)

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert calls == 2
    assert waits == [1]
    assert exc_info.value.code == "LLM_UPSTREAM_ERROR"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    "error_factory, expected_code, expected_status",
    [
        (lambda: httpx.ReadTimeout("timed out"), "LLM_TIMEOUT", 504),
        (lambda: httpx.NetworkError("network down"), "LLM_NETWORK_ERROR", 503),
    ],
    ids=["timeout", "network"],
)
def test_deepseek_transport_errors_have_stable_contract(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: object,
    expected_code: LLMProviderErrorCode,
    expected_status: int,
) -> None:
    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FakeSuccessResponse:
            raise error_factory()  # type: ignore[operator]

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    provider = DeepSeekProvider(api_key="test-key", max_retries=0)

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == expected_status
    assert exc_info.value.retryable is True


def test_deepseek_without_api_key_has_stable_config_error() -> None:
    provider = DeepSeekProvider(api_key="")

    with pytest.raises(LLMProviderError) as exc_info:
        asyncio.run(provider.generate_reply("推荐笔记本", [_product()]))

    assert exc_info.value.code == "LLM_CONFIG_ERROR"
    assert exc_info.value.status_code == 503
    assert exc_info.value.public_message == "模型服务配置不完整"
    assert exc_info.value.retryable is False


def test_llm_call_log_records_usage_without_sensitive_request_data(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    CapturingClient.requests = []
    CapturingClient.response_data = {
        "choices": [{"message": {"content": "Chat reply"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    provider = DeepSeekProvider(api_key="secret-api-key", model="deepseek-test")

    with caplog.at_level(logging.INFO):
        assert asyncio.run(provider.generate_reply("private shopping request", [_product()])) == "Chat reply"

    message = next(record.getMessage() for record in caplog.records if record.getMessage().startswith("llm_call_completed"))
    assert "provider=deepseek" in message
    assert "model=deepseek-test" in message
    assert "api_mode=chat" in message
    assert "attempts=1 retries=0" in message
    assert "prompt_tokens=11 completion_tokens=7 total_tokens=18" in message
    assert "secret-api-key" not in message
    assert "private shopping request" not in message


def test_llm_call_failure_log_records_retry_count(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class FailingResponse:
        def raise_for_status(self) -> None:
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    class FailingClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FailingClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> FailingResponse:
            return FailingResponse()

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    provider = DeepSeekProvider(api_key="test-key", max_retries=1)

    with caplog.at_level(logging.WARNING), pytest.raises(LLMProviderError):
        asyncio.run(provider.generate_reply("private shopping request", [_product()]))

    message = next(record.getMessage() for record in caplog.records if record.getMessage().startswith("llm_call_failed"))
    assert "provider=deepseek" in message
    assert "attempts=2 retries=1" in message
    assert "error_type=HTTPStatusError error_code=LLM_UPSTREAM_ERROR" in message
    assert "private shopping request" not in message


def test_supervisor_fallback_log_does_not_include_user_message(caplog: pytest.LogCaptureFixture) -> None:
    class FailingProvider:
        name = "deepseek"

        async def extract_intent(self, message: str) -> ShoppingIntent:
            raise _provider_error()

        async def generate_reply(self, message: str, products: list[Product]) -> str:
            raise _provider_error()

    with caplog.at_level(logging.WARNING):
        asyncio.run(ShoppingSupervisor(ProductRepository(), FailingProvider()).run("private shopping request"))

    message = next(record.getMessage() for record in caplog.records if record.getMessage().startswith("llm_fallback"))
    assert "provider=deepseek fallback=mock operation=intent" in message
    assert "error_code=LLM_UPSTREAM_ERROR" in message
    assert "private shopping request" not in message
