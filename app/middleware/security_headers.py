"""Security headers middleware — adds HSTS, X-Frame-Options, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy, and CSP to every HTTP response.

P6.11: Added HSTS, Permissions-Policy. CSP retains unsafe-inline pending the
phase16-csp-clean-apply follow-up (inline workspace init scripts must be
migrated to data-attribute reads first).
"""
import os


class SecurityHeadersMiddleware:
    """Adds security headers to every HTTP response."""

    # CSP: unsafe-inline retained pending phase16-csp-clean-apply.
    # Inline scripts (workspace_state_meta init, applyScenarioSnapshot) block
    # CSP enforcement. Follow-up: move to data-attribute reads in static/app.js.
    CSP = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )

    # HSTS: only set on HTTPS deployments to avoid locking out HTTP dev servers.
    # Staging and production must set FINCO_COOKIE_SECURE=true (the default).
    _HSTS_ENABLED = os.getenv("FINCO_COOKIE_SECURE", "true").lower() in ("true", "1", "yes")
    _HSTS_VALUE = "max-age=31536000; includeSubDomains"

    HEADERS = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "Content-Security-Policy": CSP,
        # Deny access to sensitive browser APIs — no geolocation, camera, mic,
        # payment, USB, or cross-origin access needed by the modelling engine.
        "Permissions-Policy": (
            "geolocation=(), "
            "camera=(), "
            "microphone=(), "
            "payment=(), "
            "usb=(), "
            "interest-cohort=()"
        ),
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 200
        headers = []

        async def security_send(message):
            nonlocal status_code, headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                # Add security headers
                for name, value in self.HEADERS.items():
                    headers.append([name.encode(), value.encode()])
                # HSTS only on HTTPS deployments
                if self._HSTS_ENABLED:
                    headers.append([b"strict-transport-security", self._HSTS_VALUE.encode()])
                # HTML responses must not be cached — static assets use ?v= for cache busting
                content_type = next(
                    (v.decode() for k, v in headers if k.decode().lower() == "content-type"),
                    "",
                )
                if "text/html" in content_type:
                    headers.append([b"cache-control", b"no-store"])
                await send({
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": headers,
                })
            else:
                await send(message)

        await self.app(scope, receive, security_send)