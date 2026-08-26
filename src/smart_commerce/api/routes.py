import logging

from fastapi import APIRouter, Query, Request

from smart_commerce.models.schemas import ChatRequest, ChatResponse, Product

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


@router.get("/products", response_model=list[Product])
def products(request: Request, max_price: float | None = Query(default=None, gt=0), category: str | None = None, keyword: str | None = None) -> list[Product]:
    result = request.app.state.product_repository.list_products(max_price=max_price, category=category, keyword=keyword)
    logger.info("products_filtered category=%s max_price=%s keyword=%s count=%d", category, max_price, keyword, len(result))
    return result


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    logger.info("chat_started session_id=%s message_chars=%d", payload.session_id, len(payload.message))
    memory = request.app.state.session_memory
    await memory.append(payload.session_id, "user", payload.message)
    reply, recommendations, steps = request.app.state.supervisor.run(payload.message)
    await memory.append(payload.session_id, "assistant", reply)
    response = ChatResponse(session_id=payload.session_id, reply=reply, recommendations=recommendations, steps=steps, mode="mock")
    logger.info("chat_completed session_id=%s recommendations=%d", payload.session_id, len(recommendations))
    return response
