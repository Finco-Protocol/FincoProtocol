#!/bin/bash
# smoke_test.sh — FINCO Model deployment smoke test
#
# Tests the critical paths of the deployed FINCO Model app.
# Checks /public-health JSON, / redirect, and /health auth behavior.
#
# Usage: ./smoke_test.sh [base_url]
# Default base_url: http://127.0.0.1:8000

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
FAILED=0

pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; FAILED=1; }

echo "=== FINCO Model Smoke Test ==="
echo "Base URL: $BASE_URL"
echo ""

# ── 1. /public-health (no auth, returns JSON) ─────────────────────────────
echo "--- /public-health ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/public-health")
if [[ "$HTTP_CODE" != "200" ]]; then
    fail "/public-health returned $HTTP_CODE (expected 200)"
else
    BODY=$(curl -s "${BASE_URL}/public-health")
    if echo "$BODY" | grep -q '"status":"ok"'; then
        pass "/public-health → 200 with {\"status\":\"ok\"}"
    else
        fail "/public-health body missing '\"status\":\"ok\"': $BODY"
    fi
fi
echo ""

# ── 2. GET / (unauthenticated root → redirect to /login) ───────────────────
echo "--- / (root, unauthenticated) ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/")
if [[ "$HTTP_CODE" == "302" ]]; then
    LOCATION=$(curl -s -I "${BASE_URL}/" | grep -i "^Location:" | tr -d '\r' || true)
    if echo "$LOCATION" | grep -qi "login"; then
        pass "/ → 302 redirect to /login"
    else
        fail "/redirect location missing 'login': $LOCATION"
    fi
else
    fail "/ returned $HTTP_CODE (expected 302)"
fi
echo ""

# ── 3. GET /health (unauthenticated → 302 redirect to /login) ─────────────
echo "--- /health (unauthenticated) ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health")
if [[ "$HTTP_CODE" == "302" ]]; then
    LOCATION=$(curl -s -I "${BASE_URL}/health" | grep -i "^Location:" | tr -d '\r' || true)
    if echo "$LOCATION" | grep -qi "login"; then
        pass "/health → 302 redirect to /login"
    else
        fail "/health redirect location missing 'login': $LOCATION"
    fi
else
    fail "/health returned $HTTP_CODE (expected 302)"
fi
echo ""

# ── 4. GET /login (public page, no redirect) ───────────────────────────────
echo "--- /login ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/login")
if [[ "$HTTP_CODE" == "200" ]]; then
    BODY=$(curl -s "${BASE_URL}/login")
    if echo "$BODY" | grep -qi "sign in\|login\|password"; then
        pass "/login → 200 with login page content"
    else
        fail "/login 200 but body doesn't look like login page"
    fi
else
    fail "/login returned $HTTP_CODE (expected 200)"
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