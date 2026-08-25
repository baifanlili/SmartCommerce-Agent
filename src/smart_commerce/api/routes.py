from fastapi import APIRouter, Query, Request

from smart_commerce.models.schemas import ChatRequest, ChatResponse, Product

router = APIRouter(prefix="/api/v1")


@router.get("/products", response_model=list[Product])
def products(request: Request, max_price: float | None = Query(default=None, gt=0), category: str | None = None, keyword: str | None = None) -> list[Product]:
    return request.app.state.product_repository.list_products(max_price=max_price, category=category, keyword=keyword)


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    memory = request.app.state.session_memory
    await memory.append(payload.session_id, "user", payload.message)
    reply, recommendations, steps = request.app.state.supervisor.run(payload.message)
    await memory.append(payload.session_id, "assistant", reply)
    return ChatResponse(session_id=payload.session_id, reply=reply, recommendations=recommendations, steps=steps, mode="mock")
