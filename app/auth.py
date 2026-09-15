"""Auth lite — lightweight session-based auth for FINCO Model.

Architecture:
- Stateless signed cookies via itsdangerous URLSafeTimedSerializer
- Server-side session data (no DB, no Redis)
- bcrypt password hashing
- Session expiry enforced server-side
- Rate limiting on login (in-memory, per-IP)
- CSRF protection on login form via signed token

Env vars:
- FINCO_APP_MODE: development | internal | pilot (default: development)
  - development/internal: placeholder secrets allowed with WARNING
  - pilot: fails fast on placeholder/insecure secrets
- FINCO_SECRET_KEY: signing key (required in pilot/production)
- FINCO_ADMIN_USER: username (default: admin)
- FINCO_ADMIN_PASSWORD: plain password (default: FINCO Model2026!)
- FINCO_ADMIN_PASSWORD_HASH: bcrypt hash (overrides FINCO_ADMIN_PASSWORD)
- FINCO_SESSION_HOURS: session TTL in hours (default: 24)
- FINCO_COOKIE_SECURE: cookie security (default: true)
- FINCO_CSRF_SECRET: CSRF signing key (default: same as FINCO_SECRET_KEY)

Single-user mode: this app is single-user/internal or pilot-controlled only.
No multi-user roles, no tenant isolation, no enterprise permissions yet.
"""

import os
import re
import secrets
import time as time_module
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ── App mode ──────────────────────────────────────────────────────────────────

# Allowed FINCO_APP_MODE values
_VALID_APP_MODES = frozenset({"development", "internal", "pilot"})


def get_app_mode() -> str:
    """Return the current app mode, defaulting to 'development'."""
    raw = os.getenv("FINCO_APP_MODE", "").strip().lower()
    if raw in _VALID_APP_MODES:
        return raw
    if raw == "":
        return "development"
    # Unknown mode — warn and fall back to development
    print(f"WARNING: FINCO_APP_MODE={raw!r} is not recognized. "
          f"Valid values are: {', '.join(sorted(_VALID_APP_MODES))}. "
          f"Defaulting to 'development'.")
    return "development"


# ── Placeholder detection ──────────────────────────────────────────────────────

_INSECURE_KEYWORD_PATTERN = re.compile(
    # Standalone placeholder keywords preceded by non-word/non-hyphen
    r"(?<![A-Za-z0-9-])(?:changeme|example|password|admin|root|test|xxx|abc123|default|empty)(?!-[A-Za-z])"
    # Hyphen-prefixed keywords: dev-only, secret, password123, qwerty, openssh, placeholder
    r"|(?:^|[-_\s])(?:dev-only|secret|password123|qwerty|openssh|placeholder)\b"
    # Compound keywords: secret-key, secret-password, api-key (not preceded/followed by word/hyphen)
    r"|(?<!\w)(?:secret-key|secret-password|api-key)(?!\w)"
    # Not-for-* labeled placeholders
    r"|not-for-(?:production|pilot)"
    # FINCO Model variants
    r"|FINCO Model(?:2026|$|!|\s)",
    re.IGNORECASE
)


def is_placeholder_secret(value: str) -> bool:
    """
    Return True if ``value`` looks like an insecure placeholder.

    This is intentionally narrow: it catches common dev defaults and
    obviously-insecure strings. It does NOT guarantee a value is strong.
    """
    if not value:
        return True  # empty = placeholder
    return bool(_INSECURE_KEYWORD_PATTERN.search(value.strip()))


def _is_pilot_mode() -> bool:
    """Return True if app mode is 'pilot'."""
    return get_app_mode() == "pilot"


# ── Config ────────────────────────────────────────────────────────────────────

FINCO_APP_MODE = get_app_mode()  # expose for debugging/logging if needed

SECRET_KEY = os.getenv("FINCO_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = "dev-secret-please-change-in-production"
    print("WARNING: FINCO_SECRET_KEY not set. Using insecure default.")
elif is_placeholder_secret(SECRET_KEY) and _is_pilot_mode():
    raise RuntimeError(
        "FINCO_SECRET_KEY is a placeholder value in pilot mode. "
        "Set a real secret: FINCO_SECRET_KEY=<long-random-string>"
    )

ADMIN_USERNAME = os.getenv("FINCO_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH_ENV = os.getenv("FINCO_ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD_PLAIN = os.getenv("FINCO_ADMIN_PASSWORD", "FINCO Model2026!")

if is_placeholder_secret(ADMIN_PASSWORD_PLAIN) and _is_pilot_mode():
    raise RuntimeError(
        "FINCO_ADMIN_PASSWORD is a placeholder value in pilot mode. "
        "Set a real password: FINCO_ADMIN_PASSWORD=<secure-password>"
    )

import os
import re
import secrets
import time as time_module
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ── Config ───────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("FINCO_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = "dev-secret-please-change-in-production"
    print("WARNING: FINCO_SECRET_KEY not set. Using insecure default.")

ADMIN_USERNAME = os.getenv("FINCO_ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH_ENV = os.getenv("FINCO_ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD_PLAIN = os.getenv("FINCO_ADMIN_PASSWORD", "FINCO Model2026!")

SESSION_MAX_AGE_HOURS = int(os.getenv("FINCO_SESSION_HOURS", "24"))
COOKIE_NAME = "finco_session"
COOKIE_SECURE = os.getenv("FINCO_COOKIE_SECURE", "true").lower() in ("true", "1", "yes")
COOKIE_SAMESITE = os.getenv("FINCO_COOKIE_SAMESITE", "lax")

# ── CSRF configuration ─────────────────────────────────────────────────────────

CSRF_SECRET = os.getenv("FINCO_CSRF_SECRET") or SECRET_KEY
_csrf_serializer: Optional[URLSafeTimedSerializer] = None


def _get_csrf_serializer() -> URLSafeTimedSerializer:
    global _csrf_serializer
    if _csrf_serializer is None:
        _csrf_serializer = URLSafeTimedSerializer(CSRF_SECRET)
    return _csrf_serializer


# ── CSRF token helpers ────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    """Generate a new CSRF token (signed, single-use per form render)."""
    raw = secrets.token_hex(24)
    serializer = _get_csrf_serializer()
    return serializer.dumps(raw)


def validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token. Returns True if valid and not tampered."""
    if not token:
        return False
    serializer = _get_csrf_serializer()
    try:
        # Tokens valid for 24 hours (same-day is plenty for a login form)
        raw = serializer.loads(token, max_age=86400)
        return isinstance(raw, str) and len(raw) == 48
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False


# ── Rate limiting (login) ─────────────────────────────────────────────────────

MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 300  # 5 minutes

_rate_limit_lock = Lock()
_rate_limit_store: dict[str, dict] = {}  # IP -> {"failures": int, "locked_until": float | None}


def _record_failed_login(ip: str) -> None:
    """Record a failed login attempt for an IP."""
    with _rate_limit_lock:
        entry = _rate_limit_store.get(ip, {"failures": 0, "locked_until": None})
        entry["failures"] += 1
        _rate_limit_store[ip] = entry


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """
    Check if IP is rate-limited.
    Returns (allowed, seconds_remaining).
    """
    with _rate_limit_lock:
        entry = _rate_limit_store.get(ip, {"failures": 0, "locked_until": None})
        now = time_module.time()
        locked_until = entry.get("locked_until")
        if locked_until is not None and now < locked_until:
            return False, int(locked_until - now)
        if entry["failures"] >= MAX_LOGIN_FAILURES:
            entry["locked_until"] = now + LOCKOUT_SECONDS
            _rate_limit_store[ip] = entry
            return False, LOCKOUT_SECONDS
        return True, 0


def _clear_failed_logins(ip: str) -> None:
    """Clear failure record on successful login."""
    with _rate_limit_lock:
        _rate_limit_store.pop(ip, None)


# ── Password hashing ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> bytes:
    """Hash a password with bcrypt, rounds=12."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))


def _verify_password(password: str, hashed: bytes) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed)


# ── Session serializer ────────────────────────────────────────────────────────

_serializer: Optional[URLSafeTimedSerializer] = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(SECRET_KEY)
    return _serializer


# ── Session data ──────────────────────────────────────────────────────────────

class SessionData:
    """Lightweight session — user_id + username + login timestamp."""
    __slots__ = ("user_id", "username", "login_at")

    def __init__(self, user_id: str, username: str, login_at: datetime):
        self.user_id = user_id
        self.username = username
        self.login_at = login_at

    def is_expired(self, max_age_hours: int = SESSION_MAX_AGE_HOURS) -> bool:
        age = datetime.now(timezone.utc) - self.login_at
        return age > timedelta(hours=max_age_hours)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "login_at": self.login_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["SessionData"]:
        try:
            login_at = datetime.fromisoformat(data["login_at"])
            if login_at.tzinfo is None:
                login_at = login_at.replace(tzinfo=timezone.utc)
            return cls(data["user_id"], data["username"], login_at)
        except (KeyError, ValueError, TypeError):
            return None


# ── Core auth functions ──────────────────────────────────────────────────────

def verify_login(username: str, password: str) -> bool:
    """Verify username + password. Returns True if valid."""
    if username != ADMIN_USERNAME:
        return False
    if ADMIN_PASSWORD_HASH_ENV:
        stored_hash = ADMIN_PASSWORD_HASH_ENV.encode()
    else:
        stored_hash = _hash_password(ADMIN_PASSWORD_PLAIN)
    return _verify_password(password, stored_hash)


def create_session_token(user_id: str = "1", username: str = ADMIN_USERNAME) -> str:
    """Create a signed session token."""
    login_at = datetime.now(timezone.utc)
    session = SessionData(user_id=user_id, username=username, login_at=login_at)
    serializer = _get_serializer()
    return serializer.dumps(session.to_dict())


def decode_session_token(token: str) -> Optional[SessionData]:
    """Decode + validate session token. Returns SessionData or None."""
    serializer = _get_serializer()
    max_age_seconds = SESSION_MAX_AGE_HOURS * 3600
    try:
        data = serializer.loads(token, max_age=max_age_seconds)
        session = SessionData.from_dict(data)
        if session and not session.is_expired():
            return session
        return None
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def make_session_cookie(token: str) -> dict:
    """Build a session cookie dict for FastAPI responses."""
    return {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "max_age": SESSION_MAX_AGE_HOURS * 3600,
        "path": "/",
    }


def clear_session_cookie() -> dict:
    """Build a clearing cookie (logout)."""
    return {
        "key": COOKIE_NAME,
        "value": "",
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "max_age": 0,
        "path": "/",
    }
