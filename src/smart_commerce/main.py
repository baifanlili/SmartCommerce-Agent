from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smart_commerce.agents.shopping_agents import ShoppingSupervisor
from smart_commerce.api.routes import router
from smart_commerce.core.config import get_settings
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.session_memory import SessionMemory

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.state.product_repository = ProductRepository()
app.state.supervisor = ShoppingSupervisor(app.state.product_repository)
app.state.session_memory = SessionMemory(settings.redis_url)


@app.get("/health")
async def health() -> dict[str, str]:
    redis_status = await app.state.session_memory.status()
    return {"status": "ok", "service": "api", "redis": redis_status}
