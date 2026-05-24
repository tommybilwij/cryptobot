# Cryptobot — Phase 9 First Live $500 Trade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.

**Goal:** Wire the live runner to real adapters via env keys + add halt-class alerting. After Phase 9 ships, flipping `live.dry_run_mode=False` + `exchanges.{venue}.use_testnet=False` enables real money trading. The $500 first trade itself is an OPS action by the user.

**Spec:** `docs/superpowers/specs/2026-05-24-cryptobot-live-design.md`.

**DoD:** ~236 tests (Phase 8 final 230). Adapter factory + Alerter + wired into `live_trade` worker + `/health` endpoint. README runbook.

---

### Task 1: Registry keys for alerts

Modify `backend/app/profile/defaults.py` + tests.

NUMERIC: `alerts.timeout_s = 5.0`
STRING: `alerts.webhook_url = ""`, `alerts.heartbeat_severity = "info"`
BOOL: `alerts.send_heartbeats = False`

Append 4 tests to `tests/test_profile_registry.py` (one per key).

Commit: `feat: profile registry keys for alerts`

---

### Task 2: Alerter service

Files: `backend/app/services/alerter.py`, `backend/tests/services/test_alerter.py`.

```python
"""Alerter — POSTs halt-class events to a webhook URL.

Empty ``alerts.webhook_url`` → no-op. Errors are caught + logged; alerter never
throws so the live runner is never disrupted by a flaky webhook.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

logger = logging.getLogger(__name__)


class Alerter:
    def __init__(self, *, params: ProfileParams, fetcher: RetryingFetcher) -> None:
        self._params = params
        self._fetcher = fetcher

    async def send(self, *, severity: str, event: str, details: dict[str, Any]) -> None:
        url = str(self._params.get("alerts.webhook_url"))
        if not url:
            return
        payload = {
            "severity": severity,
            "event": event,
            "details": details,
            "ts": datetime.now(UTC).isoformat(),
        }
        try:
            await self._fetcher.post_json(url, body=payload)
        except Exception:  # noqa: BLE001
            logger.exception("alerter webhook failed; continuing")
```

Tests:
- `test_alerter_no_url_is_noop` — empty URL → send returns, no HTTP call
- `test_alerter_posts_payload` — MockTransport asserts POST body contains severity/event/details/ts
- `test_alerter_swallows_post_failure` — handler returns 500 → send returns cleanly, no raise

Commit: `feat: Alerter service for halt-class webhook notifications`

---

### Task 3: Exchange factory

Files: `backend/app/services/exchange_factory.py`, `backend/tests/services/test_exchange_factory.py`.

```python
"""Adapter factory — dry-run-aware Exchange builder.

Returns PaperExchange in dry-run mode OR a real adapter built from env keys.
Falls back to PaperExchange when env keys are missing (defence in depth).
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.exchanges.base import Exchange
from app.exchanges.binance import BinanceExchange
from app.exchanges.bybit import BybitExchange
from app.exchanges.hyperliquid import HyperliquidExchange
from app.exchanges.paper import PaperExchange
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

logger = logging.getLogger(__name__)

_DEFAULT_INITIAL_CASH = 10_000.0


def build_exchange(
    venue: str,
    *,
    params: ProfileParams,
    fetcher: RetryingFetcher,
    settings: Settings,
    dry_run: bool,
) -> Exchange:
    if dry_run:
        return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)

    use_testnet = bool(params.get(f"exchanges.{venue}.use_testnet"))

    if venue == "binance":
        if not settings.binance_api_key or not settings.binance_api_secret:
            logger.warning("binance keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.binance.spot_base_url_testnet" if use_testnet
            else "exchanges.binance.spot_base_url_mainnet"
        )
        return BinanceExchange(
            fetcher=fetcher, params=params,
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "bybit":
        if not settings.bybit_api_key or not settings.bybit_api_secret:
            logger.warning("bybit keys missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.bybit.base_url_testnet" if use_testnet
            else "exchanges.bybit.base_url_mainnet"
        )
        return BybitExchange(
            fetcher=fetcher, params=params,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            base_url=str(params.get(url_key)),
        )

    if venue == "hyperliquid":
        if not settings.hyperliquid_wallet_private_key:
            logger.warning("hyperliquid key missing; falling back to paper")
            return PaperExchange(venue=venue, params=params, initial_cash=_DEFAULT_INITIAL_CASH)
        url_key = (
            "exchanges.hyperliquid.base_url_testnet" if use_testnet
            else "exchanges.hyperliquid.base_url_mainnet"
        )
        return HyperliquidExchange(
            fetcher=fetcher, params=params,
            wallet_private_key=settings.hyperliquid_wallet_private_key,
            base_url=str(params.get(url_key)),
        )

    raise ValueError(f"unknown venue: {venue}")
```

Tests:
- `test_factory_dry_run_returns_paper` — even with keys set, dry_run=True → PaperExchange
- `test_factory_missing_keys_falls_back_to_paper` — empty Settings + dry_run=False → PaperExchange (assert logged warning)
- `test_factory_binance_with_keys_returns_real_adapter` — Settings with keys → BinanceExchange instance
- `test_factory_unknown_venue_raises` — unknown venue → ValueError
- `test_factory_testnet_vs_mainnet_url` — flip `exchanges.binance.use_testnet` profile flag → adapter built with mainnet URL

Use `Settings(_env_file=None, binance_api_key="x", binance_api_secret="y")` to construct test settings.

Commit: `feat: exchange_factory — dry-run-aware adapter builder with env-key fallback`

---

### Task 4: Wire live_trade worker to use factory + alerter

Modify `backend/app/worker/jobs/live_trade.py`. Replace the hardcoded PaperExchange instantiation with `build_exchange()` for each venue (binance + bybit + hyperliquid all in the dict). The runner gets all 3; strategy picks via `venue=` constructor arg.

Also build `Alerter` from `params + fetcher + Settings()` and pass to `LiveRunner` (next task wires it).

Commit: `feat: live_trade worker uses exchange_factory + Alerter`

---

### Task 5: LiveRunner calls Alerter on halt classes

Modify `backend/app/services/live_runner.py`:
- Constructor takes `alerter: Alerter`
- On `DrawdownBrakeHalt` (already caught) → `await alerter.send(severity="critical", event="DrawdownBrakeHalt", details={...})` before re-raise
- On `KillSwitchActive` → same with `event="KillSwitchActive"`
- On `HedgeDriftHalt` / `ReconciliationDriftHalt` → `severity="warning"`
- On successful hourly snapshot → if `params.get("alerts.send_heartbeats")` → `severity="info"`, `event="heartbeat"`

Modify `tests/services/test_live_runner.py`:
- Existing tests pass an Alerter stub (no-op) so they keep working
- Add 1 new test: `test_runner_alerts_on_drawdown_brake` — assert alerter.send called with severity="critical", event="DrawdownBrakeHalt"

Use `unittest.mock.AsyncMock` for the stub alerter.

Commit: `feat: LiveRunner calls Alerter on halt classes + heartbeats`

---

### Task 6: /api/v1/exchanges/health uses factory

Modify `backend/app/api/exchanges.py` to call `build_exchange()` instead of hardcoded PaperExchange. `dry_run=True` if `live.dry_run_mode` set in profile, else False. This lets the health check ping real adapters when configured.

Tests in `test_exchanges_health.py` already use PaperExchange because env keys are empty in tests → fallback path → still PaperExchange → tests still pass.

Commit: `feat: /api/v1/exchanges/health uses exchange_factory`

---

### Task 7: README — Phase 9 live runbook

Append after Phase 8 section:

```markdown

## First live $500 (Phase 9 runbook)

Phase 9 ships the safety infrastructure for real-money trading. The first
$500 trade is an OPS action — flip flags, fund a wallet, monitor closely.

### Pre-flight checklist (DO ALL OF THESE)

- [ ] Phase 7 testnet smoke tests passed against your testnet wallets
- [ ] Phase 8 dry-run loop ran for ≥ 24h with no halts
- [ ] All halt classes tested by deliberately triggering them in dry-run
- [ ] Webhook URL configured (`alerts.webhook_url`) and verified working
- [ ] You can stop the runner via `POST /api/v1/live/stop` within 10s
- [ ] Drawdown brake trigger (`risk.drawdown_brake.trigger_pct`) reviewed and set
- [ ] $500 USDC deposited to ONLY the configured venue (start with one, not all three)
- [ ] API keys: withdrawals disabled, IP-whitelisted to deploy host

### Flag-flip sequence

1. Set `exchanges.{venue}.use_testnet=False` on active profile (switches URLs to mainnet)
2. Set `live.dry_run_mode=False` (switches PaperExchange → real adapter)
3. Restart `worker-live-trade` so the new flags take effect: `docker compose --profile live up -d --force-recreate worker-live-trade`
4. Tail logs: `docker compose logs -f worker-live-trade`
5. Monitor `/api/v1/live/status` every minute for the first hour

### Rollback

Halt immediately:
```bash
curl -X POST http://localhost:8000/api/v1/oms/kill   # stop dispatches mid-flight
curl -X POST http://localhost:8000/api/v1/live/stop  # exit the runner loop
```

The kill switch is the immediate stop — runner sees it on next tick and exits.

### Alerting

Halt classes (`DrawdownBrakeHalt`, `KillSwitchActive`, `HedgeDriftHalt`, `ReconciliationDriftHalt`) automatically POST to `alerts.webhook_url`. Set this to your Discord/Slack/Telegram webhook BEFORE flipping flags.

### Webhook payload shape

```json
{
  "severity": "critical | warning | info",
  "event": "DrawdownBrakeHalt | KillSwitchActive | HedgeDriftHalt | ReconciliationDriftHalt | heartbeat",
  "details": { ... event-specific ... },
  "ts": "2026-05-24T05:55:00Z"
}
```

### When to scale beyond $500

Spec at Phase 10+ — after the first $500 runs for 1-2 weeks with no halts, no
manual intervention, and positive funding-arb P&L net of fees.
```

Commit: `docs: README Phase 9 first live $500 runbook`

---

### Task 8: PR via /pr-summary

MINOR bump v0.8.0 → v0.9.0.

---

## Plan self-review

- Spec coverage: alerts registry (1), Alerter (2), factory (3), worker wiring (4), runner integration (5), health endpoint (6), runbook (7), PR (8).
- No new DB. Reuses existing schemas/services.
- Constraint #1: `_DEFAULT_INITIAL_CASH` in factory is unit-of-measure module constant. All other values from registry.
- Constraint #4: audit pipeline unchanged.
- Safe-by-default: factory falls back to paper when keys missing; alerter no-ops when URL empty.
