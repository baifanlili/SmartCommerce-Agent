import logging
import secrets

from fastapi import APIRouter, Header, Query, Request

from smart_commerce.core.errors import ApiError
from smart_commerce.models.schemas import (
    AdminConnectionTestResponse,
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
    return request.app.state.llm_config_store.save_draft(payload)


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
    except Exception:
        logger.warning("admin_llm_connection_test_failed provider=%s", candidate.provider, exc_info=True)
        return AdminConnectionTestResponse(ok=False, message="连接测试失败，当前配置未启用", mode="mock")
    mode = "mock" if provider.name == "mock" else "llm"
    return AdminConnectionTestResponse(ok=True, message="连接测试成功", mode=mode)


@router.post("/admin/llm-config/enable", response_model=AdminLLMConfigView)
async def enable_admin_llm_config(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> AdminLLMConfigView:
    _require_admin(request, x_admin_token)
    store = request.app.state.llm_config_store
    store.enable_draft()
    request.app.state.supervisor = request.app.state.supervisor.__class__(
        request.app.state.product_repository,
        store.build_provider(),
    )
    return store.view()
