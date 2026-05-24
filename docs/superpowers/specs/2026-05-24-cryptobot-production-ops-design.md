# Cryptobot Phase 20 — Production Ops Design Spec

**Date**: 2026-05-24
**Phase**: 20 (FINAL)

## Goal

Land the **production-ops baseline**: structured JSON logging, `/api/v1/metrics` Prometheus-compatible endpoint, a deploy runbook, and a 1.0.0 release tag. Everything beyond this is operational tuning, not new feature code.

## Architecture

### Structured logging

`backend/app/logging_config.py`: configures stdlib `logging` to emit JSON lines. Compatible with Loki/Datadog/Cloudwatch.

### Prometheus metrics

`backend/app/api/metrics.py`: exposes `GET /api/v1/metrics` returning text/plain in Prometheus format. Tracks:
- `cryptobot_tests_passing` (always 1 if up — proxy for app health)
- `cryptobot_decision_audit_total` (count of DecisionAuditEntry rows)
- `cryptobot_backtest_runs_total` (count of BacktestRun rows)
- `cryptobot_oms_kill_switch_active` (0 or 1)

### Deploy runbook

`docs/DEPLOY.md`: a single page covering Docker Compose + bare-metal Python install, env-var checklist, Postgres backup cadence, log-aggregation hookup.

### Release: v1.0.0

After PR merges → tag v1.0.0 explicitly (the bumper outputs 0.20.0; this final phase does a MAJOR bump to mark feature-complete).

## Components

- `backend/app/logging_config.py` — JSON formatter
- `backend/app/api/metrics.py` — Prometheus endpoint
- `backend/app/main.py` — register metrics router + call setup_logging() on startup
- `docs/DEPLOY.md` — deploy runbook
- `backend/tests/api/test_metrics.py` — 2 tests

## DoD

~292 tests pass. JSON logs emit. `/api/v1/metrics` returns Prometheus format. v1.0.0 tagged.
