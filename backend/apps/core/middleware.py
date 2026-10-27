import logging
import time
import uuid

logger = logging.getLogger("noxora.request")


class RequestIdMiddleware:
    """Identificador por requisição (X-Request-ID) e log de acesso SEM corpo, query string ou cabeçalhos."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request.request_id = incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        logger.info(
            "request",
            extra={
                "request_id": request.request_id,
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response
