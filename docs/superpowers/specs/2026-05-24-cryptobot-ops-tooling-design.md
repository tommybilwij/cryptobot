# HP13 — Operational Tooling

**Date**: 2026-05-24

## Goal

Close the remaining operational items as far as code can:
1. **pg_dump restore drill** — `scripts/pg_backup_restore_drill.sh` + `just pg-drill` recipe
2. **Pre-flight checklist script** — `scripts/preflight.sh` that checks env vars, webhook URL, drift thresholds, kill switch state, and outputs a go/no-go report
3. **HL signing test runner** — `scripts/hl_signing_calibration.sh` that runs the opt-in HL testnet smoke
4. **Phase 0 ops checklist** — polish + add live-trade-specific items
5. **Webhook self-test endpoint** — `POST /api/v1/alerts/test` fires a synthetic alert through the configured webhook (so users can verify the URL works before flipping live flags)

## Components

- `scripts/pg_backup_restore_drill.sh`
- `scripts/preflight.sh`
- `scripts/hl_signing_calibration.sh`
- `backend/app/api/alerts.py` — `POST /api/v1/alerts/test`
- `docs/superpowers/research/cryptobot-phase-0-ops-checklist.md` — append live-launch section
- `justfile` — `pg-drill`, `preflight`, `hl-calibrate` recipes

## DoD

- `just preflight` runs and outputs a report
- `just pg-drill` dumps + restores into a temp DB
- `POST /api/v1/alerts/test` fires a test webhook
