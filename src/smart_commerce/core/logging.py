import logging

from smart_commerce.core.context import request_id_var, trace_id_var


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.trace_id = trace_id_var.get() or "-"
        return True


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(request_id)s|%(trace_id)s] %(name)s: %(message)s",
        force=True,
    )
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if not any(isinstance(existing, RequestContextFilter) for existing in handler.filters):
            handler.addFilter(RequestContextFilter())
