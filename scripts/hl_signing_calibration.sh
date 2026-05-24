#!/usr/bin/env bash
# hl_signing_calibration.sh — opt-in HL EIP-712 signing validation
#
# Runs the slow-marker HL order-placement smoke against testnet.
# Requires HYPERLIQUID_WALLET_PRIVATE_KEY + HYPERLIQUID_SMOKE_PLACE_ORDER=1.

set -euo pipefail

if [ -z "${HYPERLIQUID_WALLET_PRIVATE_KEY:-}" ]; then
  echo "❌ HYPERLIQUID_WALLET_PRIVATE_KEY env var not set"
  echo "   Set it to your testnet wallet's EVM private key (0x...)"
  exit 1
fi

export HYPERLIQUID_SMOKE_PLACE_ORDER=1
echo "==> Running HL signing calibration smoke test"
cd backend && uv run pytest \
  -m slow \
  tests/integration/test_hyperliquid_testnet_smoke.py::test_hyperliquid_testnet_place_tiny_order_calibrates_signing \
  -v

echo "✅ HL signing accepted by testnet. Code is calibrated."
