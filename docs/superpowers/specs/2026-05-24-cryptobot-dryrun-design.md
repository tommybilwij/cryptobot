# Cryptobot Phase 8 — Dry-Run Mode + Live Runner Design Spec

**Date**: 2026-05-24
**Status**: approved (autonomous mode)
**Phase**: 8 of the cryptobot build
**Blocks**: Phase 9 ($500 live trade)
**Revision history**: v1 — initial. PR #10.

## Goal

Ship the **live runner loop** that ties Strategy A + OMS + LiveStateFetcher into a continuous cycle, behind a **dry-run safety toggle** that swaps PaperExchange in for live adapters. No real money is at risk in Phase 8. After Phase 8 lands, the same loop with `dry_run_mode=false` goes to $500 live in Phase 9.

## Non-goals

- **Real money trading** → Phase 9. Phase 8 ships the loop but defaults to dry-run (paper fills against live state).
- **Kelly / Bayesian sizing, vol targeting** → Phase 10+ (after the loop is proven safe with simple sizing from Phase 6).
- **Multi-strategy meta-allocator** → Phase 18.
- **WebSocket fills** → Phase 11+ when latency matters.
- **Auto-restart / supervision** → Docker + the worker job handle restart on crash; sophisticated supervision (k8s, systemd) is ops scope.

## Architecture

### LiveRunner service

`backend/app/services/live_runner.py` — runs a continuous loop:

```
while not stopped:
    1. state = LiveStateFetcher.fetch_market_state(venue, symbols)
    2. orders = strategy.evaluate(state, params)
    3. if orders: oms.dispatch(orders, state, ...)
    4. if hourly_snapshot_due: audit.log_snapshot(...)
    5. drawdown_brake.check(equity_curve)
    6. await asyncio.sleep(live.tick_interval_s)
```

Mode is determined by **`live.dry_run_mode` profile bool** (default `True`):
- `True` → adapters dict swapped with `PaperExchange` instances seeded from live state at first tick. All orders fill in-memory; no real money moves.
- `False` → real adapters (Binance / Bybit / Hyperliquid) built from env keys.

A second registry flag **`live.enabled`** (default `False`) must be flipped to start the loop at all. Defence-in-depth — `dry_run_mode=True` AND `enabled=False` means even if someone fires the worker, nothing happens.

### Drawdown brake

`backend/app/risk/drawdown_brake.py`. Tracks rolling peak equity. If current equity drops > `risk.drawdown_brake.trigger_pct` (default 5%) from peak, raises `DrawdownBrakeHalt`. The runner catches → flips the kill switch → exits.

Phase 8 ships ONLY the drawdown brake; full Phase 10+ risk machinery (Kelly, vol target, Bayesian) is deferred.

### Worker job

`backend/app/worker/jobs/live_trade.py` — entry point for `WORKER_JOB=live_trade`. Loads active profile, builds the runner, calls `runner.start()`. The loop runs until `stop()` is invoked (via SIGTERM handler or a future API endpoint).

### docker-compose service

`worker-live-trade` under `profiles: ["live"]`. Not started by default. Triggered explicitly:
```bash
docker compose --profile live up worker-live-trade
```

### API

- **`GET /api/v1/live/status`** — current dry_run_mode, enabled flag, last tick ts, last reconciliation status, current equity (from the audit log's most recent snapshot)
- **`POST /api/v1/live/stop`** — graceful stop signal (sets a DB flag the runner polls; loop exits after current tick)

The "stop" endpoint sets `live.enabled = False` on the active profile via the same path-rewrite pattern as `POST /api/v1/oms/kill`.

## Components

```
app/services/live_runner.py            # NEW: the loop
app/services/live_state_fetcher.py     # EXISTING (Phase 7): unchanged
app/risk/__init__.py                   # NEW package
app/risk/drawdown_brake.py             # NEW: equity peak tracking + halt
app/risk/exceptions.py                 # NEW: DrawdownBrakeHalt
app/worker/jobs/live_trade.py          # NEW: WORKER_JOB entry
app/worker/main.py                     # MODIFY: register live_trade job
app/api/live.py                        # NEW: GET /status + POST /stop
app/schemas/live.py                    # NEW: Pydantic models
app/main.py                            # MODIFY: register live router
docker-compose.yml                     # MODIFY: add worker-live-trade service
justfile                               # MODIFY: add `just live-trade` recipe
tests/services/test_live_runner.py     # NEW: loop unit tests with mocked deps
tests/risk/__init__.py                 # NEW
tests/risk/test_drawdown_brake.py      # NEW
tests/api/test_live.py                 # NEW: status + stop endpoints
tests/test_worker_jobs.py              # MODIFY: assert live_trade dispatches
```

## Profile registry additions

Numeric (`PROFILE_SCOPED_DEFAULTS`):
```
live.tick_interval_s              60.0         # 1 minute between iterations
live.snapshot_interval_s          3600.0       # hourly heartbeat snapshots
live.cold_start_grace_s           300.0        # wait 5 min after start before allowing trades (let state settle)
risk.drawdown_brake.peak_equity   0.0          # initialized to 0; first tick seeds it
```

Bool (`PROFILE_SCOPED_BOOL_DEFAULTS`):
```
live.enabled                      False        # gate the loop entirely
live.dry_run_mode                 True         # default to paper fills
```

String (`PROFILE_SCOPED_STRING_DEFAULTS`):
```
live.venue                        "binance"    # which adapter to use
```

Existing risk keys already provide:
- `risk.drawdown_brake.enabled = 1.0`
- `risk.drawdown_brake.trigger_pct = 0.05` (5%)
- `risk.drawdown_brake.full_pct = 0.15` (15% halt level)
- `risk.drawdown_brake.min_mult = 0.25`

Phase 8 reads these and triggers ONLY the binary halt at `trigger_pct`. Graduated halts (mult-scaling) come Phase 10+.

## Database / migrations

**None new.** Phase 8 reuses `DecisionAuditEntry` for hourly snapshots and `StrategyProfile` for config.

## API

### `GET /api/v1/live/status`

```json
{
  "enabled": true,
  "dry_run_mode": true,
  "venue": "binance",
  "last_tick_ts": "2026-05-24T05:50:00Z",
  "last_reconciliation_status": "ok",
  "last_equity_quote": 10042.15,
  "peak_equity_quote": 10100.0,
  "drawdown_pct": -0.0057
}
```

`last_*` fields populated from the most recent `DecisionAuditEntry`. `peak_equity_quote` from the profile registry (updated on each tick).

### `POST /api/v1/live/stop`

Sets `live.enabled = False` on active profile (creates new version). Idempotent.

```json
{ "active_profile_id": "...", "live_enabled": false, "new_version": 5 }
```

## Testing strategy

~14 new tests:

**Unit (risk)**:
- `test_drawdown_brake_seeds_peak_on_first_tick` — peak starts at 0; first equity sample sets peak
- `test_drawdown_brake_updates_peak_on_new_high` — higher equity → peak updates
- `test_drawdown_brake_halts_below_trigger` — equity 5% below peak → DrawdownBrakeHalt
- `test_drawdown_brake_holds_above_trigger` — equity 3% below peak → no halt

**Unit (live runner)**:
- `test_live_runner_skips_when_disabled` — `live.enabled=False` → no tick happens
- `test_live_runner_dry_run_uses_paper_exchange` — `dry_run_mode=True` → fills go through PaperExchange
- `test_live_runner_single_tick_dispatches_via_oms` — happy path: state → evaluate → dispatch → audit
- `test_live_runner_kills_on_drawdown_brake` — runner catches `DrawdownBrakeHalt`, flips kill switch
- `test_live_runner_hourly_snapshot_logged` — after `snapshot_interval_s` elapses, snapshot row written

**API**:
- `test_live_status_returns_dry_run_state` — GET /status reflects active profile
- `test_live_stop_flips_enabled_flag` — POST /stop sets enabled=False
- `test_live_status_reflects_recent_audit_entry` — last equity from latest decision audit

**Worker**:
- `test_live_trade_job_dispatches` — `_resolve_job("live_trade")` returns callable
- `test_live_trade_requires_loop_inputs` — missing config → KeyError

**Audit (Constraint #4)**: covered by Phase 5's existing audit-trail test — runner uses the same OMS pipeline.

## Edge cases

- **Profile flips `live.enabled=False` mid-loop** → runner reads on next tick → exits cleanly. Pending dispatches finish first.
- **Drawdown brake at cold start** → peak = 0, first equity sample sets peak. No halt possible on tick 1.
- **State fetch fails** (network) → exception caught, log to audit with reconciliation_status="state_fetch_failed", continue to next tick. Repeated failures (> N consecutive) → kill switch.
- **OMS kill switch already active** → runner detects, logs snapshot, exits.
- **Empty positions + cash = 0** → strategy returns [], runner loops with no-op until cash arrives.

## Definition of done (gate to Phase 9)

- ~223 tests pass (Phase 7 final 209) — mypy --strict + ruff + AST lint clean
- `LiveRunner` runs end-to-end in a single-tick test against PaperExchange
- Drawdown brake halts at 5% drop (default registry threshold)
- `WORKER_JOB=live_trade` resolves to the runner entry point
- `GET /api/v1/live/status` reports state
- `POST /api/v1/live/stop` flips `live.enabled=False`
- `worker-live-trade` docker-compose service under `profiles: ["live"]` (not started by default)
- `just live-trade` recipe for local invocation
- Default profile config: `live.enabled=False`, `live.dry_run_mode=True` — safe by default

## Out of scope (deferred)

- Real money / mainnet → Phase 9
- Kelly sizing / vol targeting → Phase 10+
- Multi-strategy meta-allocator → Phase 18
- WebSocket fills → Phase 11+
- Supervisord / k8s restart policies → ops

## References

- `docs/superpowers/specs/2026-05-24-cryptobot-testnet-design.md` — Phase 7 LiveStateFetcher
- `docs/superpowers/specs/2026-05-24-cryptobot-strategy-a-design.md` — Phase 6 strategy
- `docs/superpowers/specs/2026-05-24-cryptobot-oms-design.md` — Phase 5 OMS dispatch
- `backend/app/services/live_state_fetcher.py` — state input to the runner
