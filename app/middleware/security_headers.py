"""Security headers middleware — adds X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP."""
import typing


class SecurityHeadersMiddleware:
    """Adds security headers to every HTTP response."""

    # PILOT_HOTFIX: 'unsafe-inline' needed for workspace init scripts.
    # Root cause: index.html inline scripts (workspace_state_meta init, applyScenarioSnapshot)
    # are blocked by CSP with script-src 'self' + no hash allowlist.
    # This is a confirmed production browser blocker for the pilot.
    #
    # The inline scripts call applyWorkspaceStateMeta / applyScenarioSnapshot from
    # static/app.js — they do NOT contain financial calculations.
    #
    # Follow-up: move these initializations to static/app.js reading from DOM
    # data attributes (no inline script needed). Target: phase16-csp-clean-apply.
    #
    # References:
    #   docs/phase16_csp_inline_script_fix.md
    CSP = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )

    HEADERS = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
        "Content-Security-Policy": CSP,
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