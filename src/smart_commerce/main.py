from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from smart_commerce.agents.shopping_agents import ShoppingSupervisor
from smart_commerce.api.routes import router
from smart_commerce.core.config import get_settings
from smart_commerce.core.errors import register_exception_handlers
from smart_commerce.core.logging import setup_logging
from smart_commerce.core.middleware import request_context_middleware
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.session_memory import SessionMemory

setup_logging()

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)
app.include_router(router)
app.state.product_repository = ProductRepository()
app.state.supervisor = ShoppingSupervisor(app.state.product_repository)
app.state.session_memory = SessionMemory(settings.redis_url)


async def _readiness():
    redis_status = await app.state.session_memory.status()
    if redis_status != "ok":
        return JSONResponse(status_code=503, content={"status": "degraded", "service": "api", "redis": "unavailable"})
    return {"status": "ok", "service": "api", "redis": redis_status}


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/health/ready")
async def readiness():
    return await _readiness()


@app.get("/health")
async def health():
    return await _readiness()
