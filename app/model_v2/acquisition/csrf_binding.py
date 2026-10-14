"""M6 purpose+session+project-bound envelope around canonical timed CSRF."""
import hashlib
import hmac
import json
from app import auth
from app.workbook.financing_csrf import _session_binding

PURPOSE = "m6-acquisition-case-and-admin-review-v1"

def _mac(binding, token):
    raw = json.dumps((PURPOSE, *binding, token), separators=(",", ":"))
    return hmac.new(auth.CSRF_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()

def issue_token(request, project):
    identity = _session_binding(request, project)
    if identity is None:
        return ""
    token = auth.generate_csrf_token()
    return token + "." + _mac(identity, token)

def extract_bound_token(request, project, supplied):
    identity = _session_binding(request, project)
    if identity is None or not isinstance(supplied, str):
        return ""
    token, sep, digest = supplied.rpartition(".")
    if not sep or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return ""
    if not hmac.compare_digest(digest, _mac(identity, token)):
        return ""
    return token
