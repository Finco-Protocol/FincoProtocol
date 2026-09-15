"""Exception handling middleware — catches unhandled errors, logs, returns friendly response."""
import logging
import sys
import traceback

logger = logging.getLogger("finco.exceptions")


class ExceptionHandlerMiddleware:
    """Catches unhandled exceptions, logs with traceback, returns safe error page."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            request_id = scope.get("request_id", "unknown")
            path = scope.get("path", "")

            exc_type = sys.exc_info()[0].__name__ if sys.exc_info()[0] else "UnknownError"
            exc_msg = str(exc)
            tb = traceback.format_exc()

            logger.error(
                "request_id=%s path=%s exception_type=%s exception=%s\n%s",
                request_id, path, exc_type, exc_msg, tb,
            )

            # Determine if it's an API/JSON path or HTML path
            if self._is_api_path(path):
                await self._send_json_error(send, request_id, exc_type, exc_msg)
            else:
                await self._send_html_error(send, request_id, path)

    def _is_api_path(self, path: str) -> bool:
        """Detect if path expects JSON response."""
        api_indicators = ["/public-health", "/run", "/validate", "/compare", "/download", "/save-run", "/runs"]
        return any(path.startswith(p) for p in api_indicators)

    async def _send_json_error(self, send, request_id, exc_type, exc_msg):
        """Send JSON error response (API endpoints)."""
        body = '{"error":"Internal server error","request_id":"' + request_id + '"}'
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [[b"content-type", b"application/json"], [b"content-length", str(len(body)).encode()]],
        })
        await send({"type": "http.response.body", "body": body.encode()})

    async def _send_html_error(self, send, request_id, path):
        """Send friendly HTML error page."""
        body = (
            "<!DOCTYPE html><html><head><title>Error — FINCO Model</title></head>"
            "<body><h1>Something went wrong</h1>"
            "<p>An unexpected error occurred. If this persists, please contact support.</p>"
            f"<p>Reference: {request_id}</p>"
            "</body></html>"
        )
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                [b"content-type", b"text/html; charset=utf-8"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body.encode()})