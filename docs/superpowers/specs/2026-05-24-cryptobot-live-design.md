# Cryptobot Phase 9 — First Live $500 Trade Design Spec

**Date**: 2026-05-24
**Status**: approved (autonomous mode)
**Phase**: 9 of the cryptobot build
**Blocks**: Phase 10+ (scale + risk machinery)
**Revision history**: v1 — initial. PR #11.

## Goal

Land the **adapter factory** + **alerting webhook** so the Phase 8 live runner can be flipped from paper-fill mode to real-money mode via two profile toggles (`live.dry_run_mode=False` AND `exchanges.{venue}.use_testnet=False`). $500 first live trade is an OPERATIONAL action — Phase 9 makes it safe to perform; the user pulls the trigger.

## Non-goals

- **Sub-accounts per strategy** → Phase 13+ (capital scaling).
- **Kelly / vol-target sizing** → Phase 10+.
- **Strategy B factor portfolio** → Phase 14+.
- **WebSocket fills** → Phase 11+.
- **Auto-flip enabled** → user manually flips via the existing profile API. Phase 9 ships the safety infra; the toggle is hands-on.
- **Prometheus / Grafana monitoring** → ops scope, not the bot's code.

## Architecture

Three new pieces:

### 1. Adapter factory

`backend/app/services/exchange_factory.py`:

```python
def build_exchange(
    venue: str,
    *,
    params: ProfileParams,
    fetcher: RetryingFetcher,
    settings: Settings,
    dry_run: bool,
) -> Exchange:
    """Return PaperExchange in dry-run mode OR a real adapter built from env keys.
    
    Falls back to PaperExchange when env keys are missing — defence in depth so
    a misconfigured deploy can't accidentally hit live without keys present.
    """
```

Logic:
- If `dry_run=True` → always `PaperExchange`
- Else if env keys missing → `PaperExchange` (with a `logger.warning`)
- Else → real adapter, picking testnet vs mainnet URL from registry per `exchanges.{venue}.use_testnet`

Used by:
- `live_trade` worker job (replaces the hardcoded PaperExchange instantiation)
- `/api/v1/exchanges/health` endpoint (replaces the always-PaperExchange ping)

### 2. Alerting webhook

`backend/app/services/alerter.py`:

```python
class Alerter:
    def __init__(self, *, params: ProfileParams, fetcher: RetryingFetcher) -> None: ...
    
    async def send(self, severity: str, event: str, details: dict) -> None: ...
```

POSTs to `alerts.webhook_url` (string registry, default empty). When empty, `send()` is a no-op (still works in dev/test). Payload shape:
```json
{
  "severity": "critical",
  "event": "DrawdownBrakeHalt",
  "details": {"equity": 481.23, "peak": 510.0, "drawdown_pct": -0.057},
  "ts": "2026-05-24T05:55:00Z"
}
```

Compatible with Discord/Slack/Telegram webhooks via simple URL convention. Phase 9 ships the dispatcher; the user picks the destination URL.

Called from the live runner on:
- `KillSwitchActive` → `severity="critical"`
- `DrawdownBrakeHalt` → `severity="critical"`
- `HedgeDriftHalt` → `severity="warning"`
- `ReconciliationDriftHalt` → `severity="warning"`
- Successful hourly snapshot → `severity="info"` (only if profile has `alerts.send_heartbeats=True`)

### 3. Real-adapter `live_trade` worker

Modify `backend/app/worker/jobs/live_trade.py` to use `build_exchange()` for each configured venue. The runner gets a `dict[str, Exchange]` containing all 3 venues; the strategy picks one via its constructor `venue=` arg.

## Components

```
app/services/exchange_factory.py       # NEW: dry-run-aware adapter builder
app/services/alerter.py                # NEW: webhook dispatcher
app/worker/jobs/live_trade.py          # MODIFY: use exchange_factory + alerter
app/services/live_runner.py            # MODIFY: call alerter on halt classes
app/api/exchanges.py                   # MODIFY: real adapters in /health when keys present
tests/services/test_exchange_factory.py  # NEW
tests/services/test_alerter.py         # NEW
tests/services/test_live_runner.py     # MODIFY: assert alerter invoked
```

## Profile registry additions

String (`PROFILE_SCOPED_STRING_DEFAULTS`):
```
alerts.webhook_url                  ""    (empty disables)
alerts.heartbeat_severity           "info"
```

Bool (`PROFILE_SCOPED_BOOL_DEFAULTS`):
```
alerts.send_heartbeats              False  (only halts by default; opt-in to hourly pings)
```

Numeric (`PROFILE_SCOPED_DEFAULTS`):
```
alerts.timeout_s                    5.0
```

## API

**`GET /api/v1/exchanges/health`** — refactored to use `exchange_factory` instead of hardcoded PaperExchange. With env keys present + `use_testnet=False`, the endpoint pings real mainnet. Reports `configured: false` per-venue when keys missing.

## Testing strategy

~6 new tests:

- `test_factory_dry_run_returns_paper` — dry_run=True → PaperExchange regardless of env keys
- `test_factory_missing_keys_falls_back_to_paper` — dry_run=False + empty env → PaperExchange + warning log
- `test_factory_with_keys_returns_real_adapter` — dry_run=False + Binance env keys → BinanceExchange instance
- `test_factory_testnet_vs_mainnet_url_selection` — flips `use_testnet` flag → adapter built with mainnet URL
- `test_alerter_no_url_is_noop` — empty `alerts.webhook_url` → send() doesn't fail
- `test_alerter_posts_payload` — MockTransport asserts POST body shape

## Edge cases

- **Webhook URL invalid / unreachable** → alerter catches + logs; runner continues (alerter never throws)
- **Both `dry_run_mode=False` AND no env keys** → factory uses PaperExchange + WARN log. Runner continues, no real money risk. The `/health` endpoint reports `configured: false`.
- **`use_testnet=False` AND `dry_run_mode=False` AND keys present** → first time real money path runs. Alerter MUST be configured (Phase 9 docs make this explicit).

## Definition of done (gate to Phase 10)

- ~236 tests pass (Phase 8 final 230) — mypy + ruff + AST lint clean
- `build_exchange()` factory shipped + tested for 4 cases (dry-run, missing keys, real, testnet/mainnet)
- `Alerter` shipped + tested (no-op + post)
- `live_trade` worker uses factory + alerter
- `/health` endpoint uses factory
- README "Phase 9: $500 live runbook" section with: pre-flight checklist, flag-flip sequence, monitoring, rollback procedure

## Out of scope (deferred)

- Sub-accounts per strategy → Phase 13+
- Kelly + vol-target → Phase 10+
- Multi-strategy meta-allocator → Phase 18
- Real-time monitoring (Prometheus/Grafana) → ops
- Telegram bot integration → if user wants beyond webhook

## References

- `docs/superpowers/specs/2026-05-24-cryptobot-dryrun-design.md` — Phase 8 LiveRunner
- `docs/superpowers/specs/2026-05-24-cryptobot-testnet-design.md` — Phase 7 adapter completions
- `docs/superpowers/research/cryptobot-phase-0-ops-checklist.md` — ops setup (HLP, KYC, API keys)
