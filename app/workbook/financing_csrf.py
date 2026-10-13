"""Request-local CSRF binding for Capital Stack instrument Save only."""
import hashlib
import hmac
import json

from app import auth


def _session_binding(request, project: str):
    if request is None:
        return None
    candidates = (
        (request.cookies.get(auth.COOKIE_NAME), auth.decode_session_token),
        (request.cookies.get(auth.DEMO_COOKIE_NAME), auth.decode_demo_session_token),
        (getattr(request.state, "demo_session_token", None), auth.decode_demo_session_token),
    )
    for cookie, decode in candidates:
        session = decode(cookie) if cookie else None
        if session:
            return (session.user_id, cookie, project)
    return None


def _digest(binding, token: str) -> str:
    payload = json.dumps(("capital-stack-save-v1", *binding, token), separators=(",", ":"))
    return hmac.new(auth.CSRF_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(request, project: str) -> str:
    binding = _session_binding(request, project)
    if binding is None:
        return ""
    token = auth.generate_csrf_token()
    return token + "." + _digest(binding, token)


def extract_bound_token(request, project: str, supplied) -> str:
    """Return signed payload only when actor, session and project match.

    The route must also apply the canonical timed CSRF validator to the payload.
    This binding neither grants access nor replaces owner/protected/CAS checks.
    """
    binding = _session_binding(request, project)
    if binding is None or not isinstance(supplied, str):
        return ""
    token, separator, digest = supplied.rpartition(".")
    if (not separator or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            or not hmac.compare_digest(digest, _digest(binding, token))):
        return ""
    return token
