# cryptobot — Project CLAUDE.md

Multi-strategy crypto trading system. Currently **planning stage** — no application code in this repo yet. Stack decisions deferred; revisit this file once committed.

The dev-toolkit's methodology (workflow, branch-hygiene, doc layout under `docs/superpowers/`, commit conventions, code-standards) is in the `using-dev-toolkit` skill and auto-fires on every conversation. Don't duplicate it here.

## What this project is

A profile-driven, multi-strategy crypto trading bot. Planned strategies:

- **Funding-rate arbitrage** (delta-neutral; perp short + spot long when funding is positive). Cash-flow leg.
- **Cross-sectional alt factor portfolio** (multi-component composite score over a ~100-coin universe, top/bottom decile selection). Alpha leg.
- **Meta-allocator** (Sharpe-weighted across strategies).

Reference benchmark: Hyperliquid HLP vault. Every active strategy must beat HLP's risk-adjusted return or get killed.

## Core architectural principles (load-bearing)

These constrain every implementation choice. Violating any of them creates the bug class the system is designed to prevent.

1. **No hardcoded values in strategy / risk / execution code.** Every numeric, boolean, list, enum lives in a profile JSONB blob, fronted by a registry of profile-scoped keys + safe defaults. Strategies read parameters through one accessor (`params.get("strategies.funding_arb.entry_bps_per_8h")`). If you find yourself typing a literal in a strategy file, that is the bug — move it to the registry.

2. **Same profile drives backtest and live.** Strategy logic is a pure function `evaluate(state, params) -> Action`. The backtester and the live engine instantiate the same `ProfileParams` from the same `profile_id` and call the same function. No "backtest defaults" parallel to "live defaults". If a knob changes in Strategy Lab, the next backtest and the live bot pick it up identically.

3. **Leak-gap prevention on profile switch.** Applying a profile walks the entire registry; any key absent from the new profile resets to its registry default. Never inherit silently from the previous profile.

4. **Decision audit per trade.** Every trade decision row stores `profile_id`, `profile_version`, and `profile_hash` (sha256 of the JSONB at decision time). Six months later you must be able to reconstruct exactly which config produced any historical trade.

5. **CI lints enforce 1–4.** AST lint fails any numeric literal in strategy files. Test asserts every `params.get(path)` call has its path in the registry, and vice versa.

## Reference patterns (sibling project)

No code in this repo yet. For patterns we plan to fork or adapt, read these from `../stockbot/`:

- **Profile system** — `backend/app/services/profile_defaults.py` (registry), `backend/app/models/strategy_profile.py` (table), `backend/app/api/strategy_profiles.py` (apply mechanism, leak-gap prevention).
- **Composite scoring** — `backend/app/services/scoring.py`. The structure (weights, max_scores, thresholds, weights_by_regime, cs_alpha, llm_overlay) maps directly onto the planned factor portfolio.
- **IC discipline** — `services/signal_analytics.py`, `composite_ic.py`, `sub_component_ic.py`, `live_ic_tracker.py`, `component_graveyard.py`, `drift_monitor.py`.
- **Risk machinery** — `services/kelly_sizer.py`, `bayesian_kelly.py`, `vol_targeting.py`, `drawdown_brake.py`, `kill_switch.py`.
- **Decision audit pattern** — `models/trade_decision_log.py`, `services/decision_audit.py`.
- **Strategy Lab UI** — `frontend/src/app/strategy-lab/page.tsx` (FieldDef → registry mapping).

These are reference, not dependencies. Cryptobot does not import from stockbot.

## Differences from stockbot (don't blindly copy)

- **24/7 markets, no overnight risk premium, funding paid 1–8h.** Schedulers and risk windows are continuous, not session-bound.
- **Funding-rate accounting** in P&L and backtest is non-negotiable. A backtest that omits funding payments is off by ±10–30% APR on perp positions.
- **Multi-venue position reconciliation** across CEX (Binance, Bybit) and on-chain (Hyperliquid). Stockbot is single-venue (IBKR).
- **Hedge consistency check** between spot and perp legs. Drift > 5% halts the pair. No stockbot equivalent.
- **Counterparty caps per exchange** (no >30% on any single CEX). Sweep idle balance to cold storage.
- **Stablecoin diversification** (split USDT/USDC/AUD). USDC depegged March 2023; do not pretend stables are risk-free.
- **Survivorship-bias-safe universe**: snapshot historical symbol list per backtest window, do not use today's listed-coins set.

## Domain skills

None yet. Add `.claude/skills/<name>/SKILL.md` and mention it here as we build:

- (planned) `funding-arb-debug` — runbook for hedge-drift / basis-blowout incidents
- (planned) `profile-registry-discipline` — auto-fires when editing strategy code; reinforces "no literals"
- (planned) `backtest-realism` — checklist for fees/slippage/funding/survivorship before trusting a backtest result

## Stack

**Undecided.** No `dev-toolkit-*` stack plugin installed. When committed (likely Python FastAPI backend + Next.js frontend mirroring stockbot's shape), install the matching plugins:

```
/plugin install dev-toolkit-python-fastapi@dev-toolkit
/plugin install dev-toolkit-nextjs@dev-toolkit
/plugin install dev-toolkit-react-tailwind@dev-toolkit
```

…or re-run the filesystem installer with the stacks:

```
~/Workstation/personal/project/dev-toolkit/claude/setup/install.sh \
  ~/Workstation/personal/project/cryptobot python-fastapi nextjs react-tailwind
```

Until then, only core methodology applies.

## Precedence

1. Superpowers plugin (generic methodology — brainstorming, TDD, debugging).
2. `using-dev-toolkit` skill (project conventions — branch hygiene, doc layout, per-scenario flows).
3. This file (cryptobot-specific principles + reference patterns).
4. Direct user instructions in the current conversation (overrides everything above).
