import logging
import time
import uuid

from smart_commerce.core.context import request_id_var, trace_id_var

logger = logging.getLogger(__name__)


async def request_context_middleware(request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    trace_id = request.headers.get("x-trace-id") or request_id
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    request_id_token = request_id_var.set(request_id)
    trace_id_token = trace_id_var.set(trace_id)
    started = time.perf_counter()

    logger.info("request_start method=%s path=%s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed method=%s path=%s", request.method, request.url.path)
        request_id_var.reset(request_id_token)
        trace_id_var.reset(trace_id_token)
        raise

    response.headers["x-request-id"] = request_id
    response.headers["x-trace-id"] = trace_id
    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "request_end method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    request_id_var.reset(request_id_token)
    trace_id_var.reset(trace_id_token)
    return response
