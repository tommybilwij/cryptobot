# Cryptobot — Alembic Migrations

| Rev | File | Shipped | What |
|---|---|---|---|
| 0001 | create_strategy_profiles | Phase 1+2 | profile table + ix_strategy_profiles_active (later dropped in 0006) |
| 0002 | symbol_manifest_and_data_health | Phase 3 | symbol_manifest_snapshots + data_health_events |
| 0003 | create_backtest_runs | Phase 4 | backtest_runs table |
| 0004 | create_decision_audit_entries | Phase 5 | decision_audit_entries + composite indexes |
| 0005 | create_runner_state | HP2 | key/value JSONB for restart-safe runner state |
| 0006 | drop_orphan_strategy_profile_index | HP7 | drops ix_strategy_profiles_active (Phase 3 orphan) |

## Rules

1. **Never squash migrations that are already deployed.** Squashing changes the
   migration chain root; running databases will fail with "Can't locate revision
   identified by '0001'". The cost of carrying 20+ migrations is small;
   the cost of a borked production DB is total.

2. **Every migration must have a working downgrade.** Even if you never run it,
   reviewers verify it round-trips. Drop-only operations recreate the dropped
   object in downgrade for symmetry.

3. **Autogenerate is a starting point, not the answer.** Always inspect the
   generated upgrade()/downgrade() before committing. Common gotchas:
   - Postgres-specific types (ARRAY, JSONB, server_default) lose precision
   - Index renames show as drop+create
   - Orphaned indexes from prior migrations show up here

4. **Run `just mig-history` to print the chain locally.**

## Print the chain

```bash
just mig-history
```

Equivalent to `cd backend && uv run alembic history --verbose`.

## Future squash threshold

If migration count exceeds 20 AND the project is past v2.0 (post any major
schema breaking change), consider a full reset:

1. `pg_dump --schema-only` the current schema
2. Manually craft a new 0001 that creates it all in one go
3. Mark existing dbs as `alembic stamp head` then point at the new chain root

This is a one-time operation; do not script it.
