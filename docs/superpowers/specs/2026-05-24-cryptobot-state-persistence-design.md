# Cryptobot Hardening Pass 2 — State Persistence

**Date**: 2026-05-24

## Goal

Make runner state survive restarts:
1. **`peak_equity`** — currently registry default `0.0`; never written back; brake effectively resets every restart
2. **IC tracker history** — in-memory deque; lost on restart
3. **Component graveyard** — in-memory set; lost on restart

## Architecture

Single new table `runner_state` (key/value JSONB):

```python
class RunnerState(Base):
    __tablename__ = "runner_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = ... server_default=now()
```

Keys used:
- `peak_equity` → `{"value": 10042.15, "ts_ms": ...}`
- `ic_tracker.{component}` → `{"records": [{"ts_ms":, "score":, "forward_return":}, ...]}`
- `component_graveyard` → `{"buried": [{"component":, "reason":}, ...]}`

`backend/app/services/runner_state.py` — `RunnerStateService`:
- `async get(key) → dict | None`
- `async set(key, value) → None` (upsert)

`LiveRunner` reads peak on startup, writes after every snapshot.
`ICTracker` + `ComponentGraveyard` accept optional `RunnerStateService` for persist/load.

## Components

- `backend/app/models/runner_state.py` — ORM
- `backend/alembic/versions/0005_create_runner_state.py` — migration
- `backend/app/services/runner_state.py` — service
- `backend/app/services/live_runner.py` — hydrate peak on init + persist after snapshot
- `backend/app/risk/{ic_tracker, component_graveyard}.py` — accept service, load/persist
- Tests for each

## DoD

~308 tests. Migration applies cleanly. Restart preserves drawdown peak.
