#!/bin/bash
# smoke_test.sh — FINCO Model deployment smoke test (FINCO45C: aligned with the ACTUAL route contracts of main_web.py)
#
# Route contract checked (unauthenticated client, no cookies sent):
#   GET /public-health  200 JSON {"status":"ok"}                     public liveness, never sets a cookie
#   GET /readyz         200 JSON, status != "error"                  readiness (503 when the DB/backup dir is not usable)
#   GET /health         401 JSON {"status":"unauthenticated"}        PRIVATE health: never 200 without a session
#   GET /login          200 login page                               public
#   GET /               200 Protocol home + a demo session cookie    anonymous visitors get a provisioned demo identity
#                                                                    (demo middleware); never an admin session
#   security headers    X-Content-Type-Options: nosniff and X-Frame-Options: DENY on every response
#
# Optional authenticated check (never printed, never logged): export FINCO_SMOKE_SESSION_COOKIE to the VALUE of a
# valid finco_session cookie and /health must then return 200 {"status":"ok"}. Leave it unset otherwise.
#
# Usage: ./smoke_test.sh [base_url]          Default base_url: http://127.0.0.1:8000
# Exit 0 only when every check passed. Response bodies are never echoed in full (no secrets in output).

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
CURL=(curl -sS --max-time 15)
FAILED=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; FAILED=1; }

# fetch <path> [extra curl args...]  -> sets CODE, writes $TMP/body and $TMP/headers
fetch() {
    local path="$1"; shift
    : > "$TMP/headers"; : > "$TMP/body"
    CODE=$("${CURL[@]}" -o "$TMP/body" -D "$TMP/headers" -w "%{http_code}" "$@" "${BASE_URL}${path}" 2>/dev/null || true)
    CODE="${CODE:-000}"
}
header() { grep -i "^$1:" "$TMP/headers" | tr -d '\r' || true; }

echo "=== FINCO Model Smoke Test ==="
echo "Base URL: $BASE_URL"
echo ""

echo "--- /public-health ---"
fetch /public-health
if [[ "$CODE" == "200" ]] && grep -q '"status":"ok"' "$TMP/body"; then
    pass "/public-health → 200 {\"status\":\"ok\"}"
else
    fail "/public-health returned $CODE (expected 200 with status ok)"
fi
if [[ -n "$(header set-cookie)" ]]; then fail "/public-health set a cookie"; fi
if header x-content-type-options | grep -qi nosniff && header x-frame-options | grep -qi deny; then
    pass "security headers present (nosniff, DENY)"
else
    fail "security headers missing on /public-health"
fi
echo ""

echo "--- /readyz ---"
fetch /readyz
if [[ "$CODE" == "200" ]] && ! grep -q '"status":"error"' "$TMP/body"; then
    pass "/readyz → 200 (ready)"
else
    fail "/readyz returned $CODE (expected 200 and status != error)"
fi
echo ""

echo "--- /health (unauthenticated) ---"
fetch /health
if [[ "$CODE" == "401" ]] && grep -q '"status":"unauthenticated"' "$TMP/body"; then
    pass "/health → 401 unauthenticated (private health is not public)"
else
    fail "/health returned $CODE (expected 401 unauthenticated)"
fi
if [[ -n "$(header set-cookie)" ]]; then fail "/health provisioned a cookie"; fi
echo ""

if [[ -n "${FINCO_SMOKE_SESSION_COOKIE:-}" ]]; then
    echo "--- /health (authenticated, cookie from FINCO_SMOKE_SESSION_COOKIE; value not shown) ---"
    fetch /health -H "Cookie: finco_session=${FINCO_SMOKE_SESSION_COOKIE}"
    if [[ "$CODE" == "200" ]] && grep -q '"status":"ok"' "$TMP/body"; then
        pass "/health (authenticated) → 200 ok"
    else
        fail "/health (authenticated) returned $CODE (expected 200 ok)"
    fi
    echo ""
fi

echo "--- /login ---"
fetch /login
if [[ "$CODE" == "200" ]] && grep -qi "sign in\|login\|password" "$TMP/body"; then
    pass "/login → 200 with login page content"
else
    fail "/login returned $CODE (expected 200 login page)"
fi
echo ""

echo "--- / (anonymous) ---"
fetch /
COOKIES="$(header set-cookie)"
if [[ "$CODE" == "200" ]] && echo "$COOKIES" | grep -q "finco_demo="; then
    pass "/ → 200 with a provisioned demo session"
else
    fail "/ returned $CODE (expected 200 with a finco_demo cookie)"
fi
if echo "$COOKIES" | grep -q "finco_session="; then fail "/ issued an ADMIN session cookie to an anonymous client"; fi
if echo "$COOKIES" | grep -q "finco_demo=" && ! echo "$COOKIES" | grep -qi "httponly"; then
    fail "demo cookie is not HttpOnly"
fi
echo ""

echo "=== Results ==="
if [[ $FAILED -eq 0 ]]; then
    echo "All smoke tests passed."
    exit 0
else
    echo "Some tests failed."
    exit 1
fi
