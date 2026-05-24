# Cryptobot Hardening Pass 9 — Frontend Polish

**Date**: 2026-05-24

## Goal

1. **Prettier setup** — unblock the dev-toolkit-react-tailwind pre-commit hook that's been blocking TSX commits
2. **Vitest scaffold** — add a test runner + 3 starter tests for the Sparkline + an api helper
3. **Profile editor** — `/profiles/<id>/edit` page with a JSON textarea + Save button (POSTs the config back)
4. **Equity drilldown** — `/live` page links to a detail view showing recent ticks + per-tick equity

## Components

- `frontend/.prettierrc` + `frontend/.prettierignore`
- `frontend/package.json` — add prettier + vitest + @vitest/ui + jsdom
- `frontend/vitest.config.ts`
- `frontend/src/components/Sparkline.test.tsx` — 2 tests
- `frontend/src/lib/api.test.ts` — 1 test
- `frontend/src/app/profiles/[id]/edit/page.tsx` — editor
- `frontend/src/app/live/ticks/page.tsx` — drilldown
- Update `/profiles` to link to edit; update `/live` to link to drilldown

## DoD

- `npx prettier --check .` passes (or runs cleanly with the config)
- `npx vitest run` passes 3 tests
- Editor saves config back via PUT (need backend support — fall back to client-side preview if endpoint doesn't accept config mutation)
