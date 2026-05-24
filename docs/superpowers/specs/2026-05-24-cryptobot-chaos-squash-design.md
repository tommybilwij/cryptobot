# HP12 — Chaos Tests + Migration Hygiene

**Date**: 2026-05-24

## Goal

1. **Chaos tests** — slow-marker tests verifying graceful degradation:
   - Venue returns 503 mid-dispatch → OMS records venue_error, no crash
   - Postgres connection drops during dispatch → audit retry / clean error
   - Network partition (httpx ConnectionError) → adapter raises, OMS catches
   
2. **Migration hygiene** — NOT a squash (too risky for live data); instead, document the 6 migrations + add a `just mig-history` recipe to print the chain.

## Components

- `backend/tests/chaos/test_venue_503.py` — adapter returns 503 → recorded as venue_error
- `backend/tests/chaos/test_network_partition.py` — httpx ConnectionError → adapter raises
- `backend/tests/chaos/__init__.py`
- `justfile` — add `mig-history` recipe
- `docs/MIGRATIONS.md` — documents the 6 migrations + ordering rules

## DoD

~356 tests. Chaos tests skip without slow marker; document explains migration evolution.
