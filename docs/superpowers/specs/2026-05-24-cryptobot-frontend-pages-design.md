# Cryptobot Hardening Pass 6 — Frontend Pages

**Date**: 2026-05-24

## Goal

Wire up 4 placeholder Next.js pages to real backend endpoints:
1. **`/profiles`** — list profiles, show active one, view config JSON
2. **`/live`** — live runner status + stop button
3. **`/audit`** — recent decision audit (paginated)
4. **`/exchanges`** — venue health rendering

Plus add an **equity chart** to `/live` using a lightweight inline SVG sparkline (no extra deps).

## Architecture

Each page is a client component (`"use client"`) that polls its respective endpoint every 5s. Same pattern as the existing `/oms` page.

The audit page uses `?limit=50` + a filter dropdown for `strategy_name` and `decision_type`.

The equity chart pulls the last 100 `DecisionAuditEntry` rows (decision_type=snapshot), extracts `input_state.equity` series, renders as inline SVG polyline. No D3/Recharts dep — keeps the scaffold lean.

## Components

- `frontend/src/app/profiles/page.tsx` — real list view
- `frontend/src/app/live/page.tsx` — status + stop + equity sparkline
- `frontend/src/app/audit/page.tsx` — paginated list with filters
- `frontend/src/app/exchanges/page.tsx` — venue table
- `frontend/src/components/Sparkline.tsx` — inline SVG sparkline

No backend changes. No tests (frontend test infra is its own follow-up).

## DoD

`npm run dev` boots; all 4 pages render real data when backend is up; equity sparkline draws when audit snapshots exist.
