import json
import logging
import secrets

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from smart_commerce.agents.shopping_agents import StreamDeltaEvent, StreamDoneEvent, StreamStepEvent
from smart_commerce.core.errors import ApiError, _request_ids
from smart_commerce.services.llm_provider import LLMProviderError
from smart_commerce.models.schemas import (
    AdminConnectionTestResponse,
    AdminLLMConfigEnable,
    AdminLLMConfigView,
    AdminLLMConfigWrite,
    ChatRequest,
    ChatResponse,
    Product,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def _require_admin(request: Request, admin_token: str | None) -> None:
    configured_token = request.app.state.settings.admin_token
    if not configured_token:
        raise ApiError(503, "ADMIN_AUTH_NOT_CONFIGURED", "管理员认证尚未配置")
    if not admin_token or not secrets.compare_digest(admin_token, configured_token):
        raise ApiError(401, "UNAUTHORIZED", "管理员认证失败")


@router.get("/products", response_model=list[Product])
def products(request: Request, max_price: float | None = Query(default=None, gt=0), category: str | None = None, keyword: str | None = None) -> list[Product]:
    result = request.app.state.product_repository.list_products(max_price=max_price, category=category, keyword=keyword)
    logger.info("products_filtered category=%s max_price=%s keyword=%s count=%d", category, max_price, keyword, len(result))
    return result


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    identity = request.state.identity
    logger.info("chat_started session_id=%s user_id=%s tenant_id=%s message_chars=%d", payload.session_id, identity.user_id, identity.tenant_id, len(payload.message))
    memory = request.app.state.session_memory
    await memory.append(identity, payload.session_id, "user", payload.message)
    reply, search_result, steps, mode = await request.app.state.supervisor.run(payload.message)
    await memory.append(identity, payload.session_id, "assistant", reply)
    response = ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        intent=search_result.intent,
        recommendations=search_result.products,
        steps=steps,
        mode=mode,
    )
    logger.info("chat_completed session_id=%s user_id=%s tenant_id=%s recommendations=%d mode=%s", payload.session_id, identity.user_id, identity.tenant_id, len(search_result.products), mode)
    return response

def _sse(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    identity = request.state.identity
    logger.info(
        "chat_stream_started session_id=%s user_id=%s tenant_id=%s message_chars=%d",
        payload.session_id,
        identity.user_id,
        identity.tenant_id,
        len(payload.message),
    )
    memory = request.app.state.session_memory
    await memory.append(identity, payload.session_id, "user", payload.message)
    request_id, trace_id = _request_ids(request)

    async def event_source():
        try:
            async for event in request.app.state.supervisor.stream_run(payload.message):
                if isinstance(event, StreamStepEvent):
                    yield _sse(
                        "step",
                        {
                            "agent": event.agent,
                            "label": event.label,
                            "status": event.status,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        },
                    )
                elif isinstance(event, StreamDeltaEvent):
                    yield _sse(
                        "delta",
                        {
                            "text": event.text,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        },
                    )
                elif isinstance(event, StreamDoneEvent):
                    await memory.append(identity, payload.session_id, "assistant", event.reply)
                    yield _sse(
                        "done",
                        {
                            "session_id": payload.session_id,
                            "reply": event.reply,
                            "intent": event.search_result.intent.model_dump(),
                            "recommendations": [product.model_dump() for product in event.search_result.products],
                            "steps": [step.model_dump() for step in event.steps],
                            "mode": event.mode,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        },
                    )
        except Exception:
            logger.exception(
                "chat_stream_failed session_id=%s user_id=%s tenant_id=%s",
                payload.session_id,
                identity.user_id,
                identity.tenant_id,
            )
            yield _sse(
                "error",
                {
                    "code": "INTERNAL_ERROR",
                    "message": "服务器内部错误",
                    "request_id": request_id,
                    "trace_id": trace_id,
                },
            )
        finally:
            logger.info(
                "chat_stream_completed session_id=%s user_id=%s tenant_id=%s",
                payload.session_id,
                identity.user_id,
                identity.tenant_id,
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/admin/llm-config", response_model=AdminLLMConfigView)
async def get_admin_llm_config(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminLLMConfigView:
    _require_admin(request, x_admin_token)
    return request.app.state.llm_config_store.view()


@router.post("/admin/llm-config", response_model=AdminLLMConfigView)
async def save_admin_llm_config(
    payload: AdminLLMConfigWrite,
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminLLMConfigView:
    _require_admin(request, x_admin_token)
    return request.app.state.llm_config_store.save_draft(payload, payload.expected_version)


@router.post("/admin/llm-config/test", response_model=AdminConnectionTestResponse)
async def test_admin_llm_config(
    payload: AdminLLMConfigWrite,
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminConnectionTestResponse:
    _require_admin(request, x_admin_token)
    store = request.app.state.llm_config_store
    candidate = store.config_for_test(payload)
    provider = store.build_provider(candidate)
    try:
        products = request.app.state.product_repository.list_products()[:1]
        await provider.generate_reply("测试管理员配置", products)
    except LLMProviderError as exc:
        logger.warning(
            "admin_llm_connection_test_failed provider=%s error_code=%s",
            candidate.provider,
            exc.code,
        )
        raise ApiError(exc.status_code, exc.code, exc.public_message) from exc
    mode = "mock" if provider.name == "mock" else "llm"
    return AdminConnectionTestResponse(ok=True, message="连接测试成功", mode=mode)


@router.post("/admin/llm-config/enable", response_model=AdminLLMConfigView)
async def enable_admin_llm_config(
    payload: AdminLLMConfigEnable,
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminLLMConfigView:
    _require_admin(request, x_admin_token)
    store = request.app.state.llm_config_store
    store.enable_draft(payload.expected_version)
    request.app.state.supervisor = request.app.state.supervisor.__class__(
        request.app.state.product_repository,
        store.build_provider(),
    )
    return store.view()
