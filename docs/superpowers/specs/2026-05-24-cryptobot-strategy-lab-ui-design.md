# Cryptobot Phase 19 — Strategy Lab UI Design Spec

**Date**: 2026-05-24
**Phase**: 19

## Goal

Minimal Next.js Strategy Lab UI. Displays:
1. **Profile list** with active-profile indicator (`GET /api/v1/strategy-profiles`)
2. **OMS status** + kill button (`GET /api/v1/oms/status`, `POST /api/v1/oms/kill`)
3. **Live runner status** + stop button (`GET /api/v1/live/status`, `POST /api/v1/live/stop`)
4. **Recent decision audit** (last 50 entries, `GET /api/v1/decision-audit/recent`)
5. **Exchange health** (`GET /api/v1/exchanges/health`)

Phase 19 ships scaffolding + 5 pages. No charts, no editor — those are Phase 20+.

## Architecture

`frontend/` directory (NEW). Next.js 15 + App Router + Tailwind. Backend URL via `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

```
frontend/
├── package.json
├── next.config.js
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                  # Dashboard
│   │   ├── profiles/page.tsx         # Profile list
│   │   ├── oms/page.tsx              # OMS status + kill
│   │   ├── live/page.tsx             # Live runner status + stop
│   │   ├── audit/page.tsx            # Recent decisions
│   │   └── exchanges/page.tsx        # Health
│   ├── lib/
│   │   └── api.ts                    # fetch wrapper with NEXT_PUBLIC_API_BASE_URL
│   └── components/
│       └── StatusBadge.tsx
```

Phase 19 ships scaffold + ONE working page (`/oms`) to prove the API integration. Remaining pages are TODO placeholders.

## Components

- Frontend scaffold (package.json, next.config, tailwind, tsconfig)
- `src/lib/api.ts` — typed `apiGet/apiPost`
- `src/app/page.tsx` — landing
- `src/app/oms/page.tsx` — OMS status + kill button
- `frontend/README.md` — dev quickstart

No tests this phase — frontend tests deserve their own infra (Phase 20+).

## DoD

`cd frontend && npm install && npm run dev` boots the Next.js dev server. `/oms` page reads `/api/v1/oms/status` from the backend (CORS handled).
