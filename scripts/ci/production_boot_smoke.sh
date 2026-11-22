#!/usr/bin/env bash
# Production boot smoke (moved verbatim from .github/workflows/production_boot_smoke.yml; run by Model CI).
# Expects the synthetic CI-only FINCO_* environment set by the workflow and a ".venv" with requirements installed.
set -euo pipefail

echo "::group::Validate production command wiring"
(
set -euo pipefail
bash -n deploy/scripts/run_web.sh
bash -n deploy/scripts/start_prod.sh
bash -n deploy/scripts/restore.sh
bash -n deploy/scripts/healthcheck.sh
grep -Fq 'ExecStart=/bin/bash /opt/finco_protocol/deploy/scripts/run_web.sh' deploy/systemd/finco-web.service
if grep -R --line-number -E 'gunicorn[[:space:]]+main_web:app' deploy/systemd deploy/scripts; then
  echo "ERROR: stale broken Gunicorn/FastAPI production invocation remains" >&2
  exit 1
fi
)
echo "::endgroup::"

echo "::group::Mandatory configuration fails closed without leaking values"
(
set -euo pipefail
set +e
env -u FINCO_SECRET_KEY -u FINCO_ADMIN_USER -u FINCO_ADMIN_PASSWORD \
  /bin/bash deploy/scripts/run_web.sh >/tmp/finco-h6-missing.stdout 2>/tmp/finco-h6-missing.stderr
RC=$?
set -e
test "$RC" -eq 78
grep -Fq 'FINCO_SECRET_KEY' /tmp/finco-h6-missing.stderr
if grep -Fq "$FINCO_SECRET_KEY" /tmp/finco-h6-missing.stderr; then
  echo "ERROR: configuration value leaked to stderr" >&2
  exit 1
fi
)
echo "::endgroup::"

echo "::group::Secure mode is mandatory (P0-C)"
(
set -euo pipefail
for BAD in "" development internal; do
  set +e
  FINCO_APP_MODE="$BAD" /bin/bash deploy/scripts/run_web.sh >/tmp/finco-p0c-mode.out 2>/tmp/finco-p0c-mode.err
  RC=$?
  set -e
  test "$RC" -eq 78
  if grep -Fq "$FINCO_SECRET_KEY" /tmp/finco-p0c-mode.err; then
    echo "ERROR: configuration value leaked to stderr" >&2
    exit 1
  fi
done
set +e
FINCO_ADMIN_PASSWORD='FINCO Model2026!' /bin/bash deploy/scripts/run_web.sh >/tmp/finco-p0c-admin.out 2>/tmp/finco-p0c-admin.err
RC=$?
set -e
test "$RC" -eq 78
if grep -Fq 'FINCO Model2026' /tmp/finco-p0c-admin.err; then
  echo "ERROR: default credential echoed to stderr" >&2
  exit 1
fi
)
echo "::endgroup::"

echo "::group::Start declared production command and require live HTTP 200"
(
set -euo pipefail
LOG=/tmp/finco-h6-uvicorn.log
BODY=/tmp/finco-h6-health-body
PORT=8765
# Readiness window. A FRESH database makes application startup seed the reference models'
# canonical Last Runs (real model runs, about 70 s measured on a clean checkout, identical on
# main); later starts are idempotent and take seconds. The window is that measured cost
# with headroom, not an arbitrary value; on timeout the diagnostics below say why.
READY_SECONDS=150

/bin/bash deploy/scripts/run_web.sh >"$LOG" 2>&1 &
PID=$!

diagnostics() {
  echo "---- PRODUCTION_BOOT_DIAGNOSTICS ----" >&2
  if kill -0 "$PID" 2>/dev/null; then
    echo "process: ALIVE (pid $PID, state $(ps -o stat= -p "$PID" 2>/dev/null || echo '?'))" >&2
  else
    echo "process: EXITED" >&2
  fi
  if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
    echo "listener: PRESENT on :$PORT" >&2
  else
    echo "listener: ABSENT on :$PORT" >&2
  fi
  echo "last health status: ${STATUS:-none}" >&2
  echo "---- server log (complete) ----" >&2
  cat "$LOG" >&2 || true
  echo "---- end diagnostics ----" >&2
}

# Bounded shutdown: SIGTERM, wait at most 10 s, then SIGKILL. Never hangs the job.
stop_server() {
  kill "$PID" 2>/dev/null || true
  for _ in $(seq 1 40); do
    kill -0 "$PID" 2>/dev/null || return 0
    sleep 0.25
  done
  kill -9 "$PID" 2>/dev/null || true
}
trap stop_server EXIT

STATUS=000
for _ in $(seq 1 "$READY_SECONDS"); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "PRODUCTION_BOOT_FAILED: process exited during startup" >&2
    diagnostics
    exit 1
  fi
  STATUS=$(curl --max-time 1 -sS -o "$BODY" -w '%{http_code}' "http://127.0.0.1:$PORT/public-health" 2>/dev/null || true)
  if [[ "$STATUS" == "200" ]]; then
    break
  fi
  if [[ "$STATUS" != "000" ]]; then
    echo "PRODUCTION_BOOT_FAILED: /public-health returned HTTP $STATUS" >&2
    cat "$BODY" >&2 || true
    diagnostics
    exit 1
  fi
  sleep 1
done

if [[ "$STATUS" != "200" ]]; then
  echo "PRODUCTION_BOOT_TIMEOUT: no HTTP 200 within ${READY_SECONDS}s" >&2
  diagnostics
  exit 1
fi
grep -Fq '"status":"ok"' "$BODY"
kill -0 "$PID"
sleep 1
kill -0 "$PID"
echo "PRODUCTION_BOOT_HEALTH_HTTP_200=PASS"
echo "PRODUCTION_PROCESS_ALIVE_AFTER_HEALTH=PASS"

kill "$PID"
for _ in $(seq 1 40); do
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null || true
    trap - EXIT
    echo "PRODUCTION_PROCESS_CLEAN_TERMINATION=PASS"
    exit 0
  fi
  sleep 0.25
done

echo "ERROR: production process did not terminate after SIGTERM" >&2
kill -9 "$PID" 2>/dev/null || true
exit 1
)
echo "::endgroup::"

