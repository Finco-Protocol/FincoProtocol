"""Auth lite — lightweight session-based auth for FINCO Protocol.

Architecture:
- Stateless signed cookies via itsdangerous URLSafeTimedSerializer
- Server-side session data (no DB, no Redis)
- bcrypt password hashing
- Session expiry enforced server-side
- Rate limiting on login (in-memory, per-IP)
- CSRF protection on login form via signed token
- Demo session isolation: anonymous signed cookies, unique per-visitor

Env vars:
- FINCO_APP_MODE: development | internal | pilot (default: development)
  - development/internal: placeholder secrets allowed with WARNING
  - pilot: fails fast on placeholder/insecure secrets
- FINCO_SECRET_KEY: signing key (required in pilot/production)
- FINCO_ADMIN_USER: username (default: admin)
- FINCO_ADMIN_PASSWORD: plain password (default: FINCO Model2026!)
- FINCO_ADMIN_PASSWORD_HASH: bcrypt hash (overrides FINCO_ADMIN_PASSWORD)
- FINCO_SESSION_HOURS: admin session TTL in hours (default: 24)
- FINCO_DEMO_TTL_HOURS: demo session TTL in hours (default: 24)
- FINCO_COOKIE_SECURE: cookie security (default: true)
- FINCO_CSRF_SECRET: CSRF signing key (default: same as FINCO_SECRET_KEY)
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

_VALID_APP_MODES = frozenset({"development", "internal", "pilot"})


def get_app_mode() -> str:
    """Return the current app mode, defaulting to 'development'."""
    raw = os.getenv("FINCO_APP_MODE", "").strip().lower()
    if raw in _VALID_APP_MODES:
        return raw
    if raw == "":
        return "development"
    print(f"WARNING: FINCO_APP_MODE={raw!r} is not recognized. "
          f"Valid values are: {', '.join(sorted(_VALID_APP_MODES))}. "
          f"Defaulting to 'development'.")
    return "development"


# ── Placeholder detection ──────────────────────────────────────────────────────

_INSECURE_KEYWORD_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])(?:changeme|example|password|admin|root|test|xxx|abc123|default|empty)(?!-[A-Za-z])"
    r"|(?:^|[-_\s])(?:dev-only|secret|password123|qwerty|openssh|placeholder)\b"
    r"|(?<!\w)(?:secret-key|secret-password|api-key)(?!\w)"
    r"|not-for-(?:production|pilot)"
    r"|FINCO Model(?:2026|$|!|\s)",
    re.IGNORECASE
)


def is_placeholder_secret(value: str) -> bool:
    """Return True if value looks like an insecure placeholder."""
    if not value:
        return True
    return bool(_INSECURE_KEYWORD_PATTERN.search(value.strip()))


def _is_pilot_mode() -> bool:
    return get_app_mode() == "pilot"


# ── Config ────────────────────────────────────────────────────────────────────

FINCO_APP_MODE = get_app_mode()

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

SESSION_MAX_AGE_HOURS = int(os.getenv("FINCO_SESSION_HOURS", "24"))
DEMO_TTL_HOURS = int(os.getenv("FINCO_DEMO_TTL_HOURS", "24"))

COOKIE_NAME = "finco_session"
DEMO_COOKIE_NAME = "finco_demo"

COOKIE_SECURE = os.getenv("FINCO_COOKIE_SECURE", "true").lower() in ("true", "1", "yes")
COOKIE_SAMESITE = os.getenv("FINCO_COOKIE_SAMESITE", "lax")

# Demo session user_id prefix — never overlaps with admin ("1") or reference ("__reference__")
DEMO_USER_ID_PREFIX = "demo_"


# ── CSRF configuration ────────────────────────────────────────────────────────

CSRF_SECRET = os.getenv("FINCO_CSRF_SECRET") or SECRET_KEY
_csrf_serializer: Optional[URLSafeTimedSerializer] = None


def _get_csrf_serializer() -> URLSafeTimedSerializer:
    global _csrf_serializer
    if _csrf_serializer is None:
        _csrf_serializer = URLSafeTimedSerializer(CSRF_SECRET)
    return _csrf_serializer


def generate_csrf_token() -> str:
    """Generate a new CSRF token (signed, single-use per form render)."""
    raw = secrets.token_hex(24)
    return _get_csrf_serializer().dumps(raw)


def validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token. Returns True if valid and not tampered."""
    if not token:
        return False
    try:
        raw = _get_csrf_serializer().loads(token, max_age=86400)
        return isinstance(raw, str) and len(raw) == 48
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False


# ── Rate limiting (login) ─────────────────────────────────────────────────────

MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 300

_rate_limit_lock = Lock()
_rate_limit_store: dict[str, dict] = {}


def _record_failed_login(ip: str) -> None:
    with _rate_limit_lock:
        entry = _rate_limit_store.get(ip, {"failures": 0, "locked_until": None})
        entry["failures"] += 1
        _rate_limit_store[ip] = entry


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """Check if IP is rate-limited. Returns (allowed, seconds_remaining)."""
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
    with _rate_limit_lock:
        _rate_limit_store.pop(ip, None)


# ── Demo-session rate limiting ────────────────────────────────────────────────
# Separate bucket per demo user_id for model-run and project-create operations.

_demo_op_lock = Lock()
_demo_op_store: dict[str, dict] = {}  # user_id -> {op -> [timestamps]}

DEMO_RATE_LIMITS: dict[str, tuple[int, int]] = {
    # op_name -> (max_calls, window_seconds)
    "project_create": (5, 3600),     # 5 new projects per hour
    "model_run": (20, 3600),          # 20 model runs per hour
    "scenario_add": (15, 3600),       # 15 scenarios per hour
    "export_generate": (10, 3600),    # 10 exports per hour
}


def check_demo_rate_limit(user_id: str, op: str) -> tuple[bool, int]:
    """Check if a demo session is rate-limited for a specific operation.

    Returns (allowed, retry_after_seconds). Only applies to demo user IDs.
    """
    if not user_id.startswith(DEMO_USER_ID_PREFIX):
        return True, 0
    limit_max, window = DEMO_RATE_LIMITS.get(op, (100, 3600))
    now = time_module.time()
    cutoff = now - window
    with _demo_op_lock:
        bucket = _demo_op_store.setdefault(user_id, {})
        timestamps = bucket.get(op, [])
        # Evict expired timestamps
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= limit_max:
            oldest = min(timestamps)
            retry_after = int(window - (now - oldest)) + 1
            bucket[op] = timestamps
            _demo_op_store[user_id] = bucket
            return False, retry_after
        timestamps.append(now)
        bucket[op] = timestamps
        _demo_op_store[user_id] = bucket
    return True, 0


def purge_expired_demo_rate_entries() -> None:
    """Remove stale entries from the in-memory demo rate-limit store."""
    now = time_module.time()
    with _demo_op_lock:
        dead = [uid for uid, bucket in _demo_op_store.items()
                if all(max(ts, default=0) < now - 7200 for ts in bucket.values())]
        for uid in dead:
            del _demo_op_store[uid]


# ── Password hashing ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))


def _verify_password(password: str, hashed: bytes) -> bool:
    return bcrypt.checkpw(password.encode(), hashed)


# ── Session serializers ───────────────────────────────────────────────────────

_serializer: Optional[URLSafeTimedSerializer] = None
_demo_serializer: Optional[URLSafeTimedSerializer] = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(SECRET_KEY)
    return _serializer


def _get_demo_serializer() -> URLSafeTimedSerializer:
    """Separate serializer salt for demo tokens, so admin and demo tokens are not interchangeable."""
    global _demo_serializer
    if _demo_serializer is None:
        _demo_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="finco-demo-session")
    return _demo_serializer


# ── Session data ──────────────────────────────────────────────────────────────

class SessionData:
    """Lightweight session — user_id + username + login timestamp + session_type."""
    __slots__ = ("user_id", "username", "login_at", "session_type")

    def __init__(
        self,
        user_id: str,
        username: str,
        login_at: datetime,
        session_type: str = "admin",
    ):
        self.user_id = user_id
        self.username = username
        self.login_at = login_at
        self.session_type = session_type  # "admin" | "demo"

    @property
    def is_demo(self) -> bool:
        return self.session_type == "demo"

    def is_expired(self, max_age_hours: int = SESSION_MAX_AGE_HOURS) -> bool:
        age = datetime.now(timezone.utc) - self.login_at
        return age > timedelta(hours=max_age_hours)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "login_at": self.login_at.isoformat(),
            "session_type": self.session_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["SessionData"]:
        try:
            login_at = datetime.fromisoformat(data["login_at"])
            if login_at.tzinfo is None:
                login_at = login_at.replace(tzinfo=timezone.utc)
            return cls(
                data["user_id"],
                data["username"],
                login_at,
                data.get("session_type", "admin"),
            )
        except (KeyError, ValueError, TypeError):
            return None


# ── Core auth functions ───────────────────────────────────────────────────────

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
    """Create a signed admin session token."""
    login_at = datetime.now(timezone.utc)
    session = SessionData(user_id=user_id, username=username, login_at=login_at, session_type="admin")
    return _get_serializer().dumps(session.to_dict())


def decode_session_token(token: str) -> Optional[SessionData]:
    """Decode + validate admin session token. Returns SessionData or None."""
    max_age_seconds = SESSION_MAX_AGE_HOURS * 3600
    try:
        data = _get_serializer().loads(token, max_age=max_age_seconds)
        session = SessionData.from_dict(data)
        if session and not session.is_expired():
            return session
        return None
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def make_session_cookie(token: str) -> dict:
    """Build an admin session cookie dict for FastAPI responses."""
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
    """Build a clearing cookie (admin logout)."""
    return {
        "key": COOKIE_NAME,
        "value": "",
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "max_age": 0,
        "path": "/",
    }


# ── Demo session functions ────────────────────────────────────────────────────

def new_demo_user_id() -> str:
    """Generate a new cryptographically random demo user ID."""
    return DEMO_USER_ID_PREFIX + secrets.token_urlsafe(24)


def create_demo_session_token(demo_user_id: str) -> str:
    """Create a signed demo session token for an anonymous visitor."""
    login_at = datetime.now(timezone.utc)
    session = SessionData(
        user_id=demo_user_id,
        username="demo",
        login_at=login_at,
        session_type="demo",
    )
    return _get_demo_serializer().dumps(session.to_dict())


def decode_demo_session_token(token: str) -> Optional[SessionData]:
    """Decode + validate demo session token. Returns SessionData or None."""
    max_age_seconds = DEMO_TTL_HOURS * 3600
    try:
        data = _get_demo_serializer().loads(token, max_age=max_age_seconds)
        session = SessionData.from_dict(data)
        if session and not session.is_expired(max_age_hours=DEMO_TTL_HOURS):
            return session
        return None
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def make_demo_cookie(token: str) -> dict:
    """Build a demo session cookie dict for FastAPI responses."""
    return {
        "key": DEMO_COOKIE_NAME,
        "value": token,
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "max_age": DEMO_TTL_HOURS * 3600,
        "path": "/",
    }


def clear_demo_cookie() -> dict:
    """Build a clearing demo cookie."""
    return {
        "key": DEMO_COOKIE_NAME,
        "value": "",
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
        "max_age": 0,
        "path": "/",
    }
