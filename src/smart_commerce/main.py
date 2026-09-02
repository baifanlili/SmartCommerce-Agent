import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from smart_commerce.agents.shopping_agents import supervisor_from_settings
from smart_commerce.api.routes import router
from smart_commerce.core.config import get_settings
from smart_commerce.core.errors import error_response, register_exception_handlers
from smart_commerce.core.logging import setup_logging
from smart_commerce.core.middleware import request_context_middleware
from smart_commerce.repositories.product_repository import ProductRepository
from smart_commerce.services.session_memory import SessionMemory
from smart_commerce.services.runtime_config import RuntimeLLMConfigStore
from smart_commerce.services.runtime_config import RuntimeConfigConflictError, RuntimeConfigEncryptionError

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)


@app.exception_handler(RuntimeConfigConflictError)
async def handle_config_conflict(request: Request, exc: RuntimeConfigConflictError) -> JSONResponse:
    return error_response(
        request,
        409,
        "CONFIG_VERSION_CONFLICT",
        "配置已被其他操作修改，请重新读取后重试",
        [{"field": "expected_version", "message": f"当前版本为 {exc.current_version}"}],
    )


@app.exception_handler(RuntimeConfigEncryptionError)
async def handle_config_encryption_error(request: Request, exc: RuntimeConfigEncryptionError) -> JSONResponse:
    logger.error("runtime_config_encryption_error %s", exc)
    return error_response(request, 500, "RUNTIME_CONFIG_ENCRYPTION_FAILED", "运行期配置加密初始化失败", [])


app.include_router(router)
app.state.product_repository = ProductRepository()
app.state.settings = settings
app.state.llm_config_store = RuntimeLLMConfigStore(settings)
app.state.supervisor = supervisor_from_settings(app.state.product_repository, settings)
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
