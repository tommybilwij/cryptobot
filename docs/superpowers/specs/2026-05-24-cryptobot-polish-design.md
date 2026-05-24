# HP14 — Polish & Verification

**Date**: 2026-05-24

## Goal

Close all remaining polish items:
1. `.env.example` at repo root
2. `pyrightconfig.json` at repo root (silences LSP noise across PRs)
3. Frontend boot verification — actually `npm install && npm run build`
4. Frontend CI job in GitHub Actions
5. Fix HP9 profile editor — `/apply` takes no body; add new `POST /{id}/update-config` endpoint OR have editor use clone semantics
6. Pin Docker `python:3.12` to specific digest (or at least `python:3.12-slim` minor pin)
7. Worker healthchecks in docker-compose
8. `live_trade` worker calls `setup_logging()` at entry
9. Backfill `requirements.txt` from `uv export` for non-uv users

## Components

- `.env.example`
- `pyrightconfig.json`
- `frontend/package-lock.json` (after `npm install`)
- `.github/workflows/frontend.yml`
- `backend/app/api/strategy_profiles.py` — new `update_config` endpoint
- `frontend/src/app/profiles/[id]/edit/page.tsx` — POST to new endpoint
- `backend/Dockerfile` — pin Python image
- `docker-compose.yml` — healthchecks on worker services
- `backend/app/worker/jobs/live_trade.py` — call setup_logging() at start of run()
- `backend/requirements.txt` (uv export)
- Tests for the new endpoint

## DoD

- Frontend boots
- New endpoint accepts {config: {...}} → bumps version
- Editor saves successfully
- Worker logs are JSON
- CI checks frontend changes
