#!/usr/bin/env bash
# preflight.sh — pre-live-trade go/no-go report

set -uo pipefail

PASS=0
FAIL=0
WARN=0

check() {
  local label="$1"
  local cmd="$2"
  if eval "${cmd}" >/dev/null 2>&1; then
    echo "  ✅ ${label}"
    PASS=$((PASS+1))
  else
    echo "  ❌ ${label}"
    FAIL=$((FAIL+1))
  fi
}

warn() {
  local label="$1"
  echo "  ⚠️  ${label}"
  WARN=$((WARN+1))
}

echo "=== Cryptobot Pre-Flight Checklist ==="
echo ""
echo "Env vars:"
check "BINANCE_API_KEY set" '[ -n "${BINANCE_API_KEY:-}" ]'
check "BINANCE_API_SECRET set" '[ -n "${BINANCE_API_SECRET:-}" ]'
check "BYBIT_API_KEY set" '[ -n "${BYBIT_API_KEY:-}" ]'
check "BYBIT_API_SECRET set" '[ -n "${BYBIT_API_SECRET:-}" ]'
check "HYPERLIQUID_WALLET_PRIVATE_KEY set" '[ -n "${HYPERLIQUID_WALLET_PRIVATE_KEY:-}" ]'

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  warn "ANTHROPIC_API_KEY missing — LLM overlay will be no-op"
fi

echo ""
echo "Postgres:"
check "Postgres reachable" 'docker compose ps postgres | grep -q "Up\|healthy"'

echo ""
echo "Migrations:"
check "Migration head matches" 'cd backend && uv run alembic current 2>&1 | grep -q "head"'

echo ""
echo "Tests:"
check "Backend tests green" 'cd backend && uv run pytest -q 2>&1 | grep -q "passed"'

echo ""
echo "Active profile + flags (via API; needs api running):"
if curl -sf http://localhost:8000/api/v1/oms/status >/dev/null 2>&1; then
  STATUS=$(curl -s http://localhost:8000/api/v1/oms/status)
  KILL=$(echo "$STATUS" | python3 -c "import sys,json;print(json.load(sys.stdin).get('kill_switch_active'))")
  if [ "$KILL" = "True" ]; then
    warn "kill_switch_active is TRUE — runner will refuse to dispatch"
  else
    echo "  ✅ kill_switch_active is False"
    PASS=$((PASS+1))
  fi
else
  warn "API not running — start with 'just api' to verify live flags"
fi

echo ""
echo "=== Summary: ${PASS} pass / ${FAIL} fail / ${WARN} warn ==="
if [ ${FAIL} -gt 0 ]; then
  echo "❌ NOT READY for live trading"
  exit 1
fi
if [ ${WARN} -gt 0 ]; then
  echo "⚠️  Ready with warnings — review above"
else
  echo "✅ ALL CHECKS PASSED — safe to enable live flags"
fi
