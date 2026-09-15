"""Request logging middleware — logs method, path, status, duration, request_id."""
import time
import uuid
import logging
import re

logger = logging.getLogger("finco.requests")

# Paths that should not be logged in detail
SAFE_PATHS = {"/public-health", "/login", "/health", "/ops-status"}


class RequestLoggingMiddleware:
    """Logs HTTP request/response summary without sensitive data."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        request_id = str(uuid.uuid4())[:8]

        # Add request_id to scope for downstream use
        scope["request_id"] = request_id

        # Safe path logging
        if path in SAFE_PATHS:
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        status_code = 500  # fallback

        async def logging_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                logger.info(
                    "request_id=%s method=%s path=%s status=%d",
                    request_id, method, path, status_code,
                )
            await send(message)

        try:
            await self.app(scope, receive, logging_send)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_id=%s method=%s path=%s duration_ms=%.1f error=unhandled",
                request_id, method, path, duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        if duration_ms > 1000:
            logger.warning(
                "request_id=%s method=%s path=%s status=%d duration_ms=%.0f SLOW",
                request_id, method, path, status_code, duration_ms,
            )