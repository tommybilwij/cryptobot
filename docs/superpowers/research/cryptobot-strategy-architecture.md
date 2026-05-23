# Cryptobot strategy architecture for high risk-adjusted return

**Date**: 2026-05-23
**Status**: draft

## Scope

Architecture for a solo-dev cryptobot with $1k–$50k starting capital, ~$0–$100/mo OpEx target, running locally, on a 6–12 month horizon — maximising **realised risk-adjusted profit** (not raw APR). Excluded: market making (out of retail reach), MEV, hosted-bot platforms (closed-source, poor unit economics).

## Constraints (load-bearing — carried from project CLAUDE.md)

These precede every choice below. They are *not* market-driven findings but user-imposed architectural principles ported from stockbot's hard-won discipline. Violating any of them creates the bug class the system is designed to prevent.

1. **No hardcoded values in strategy / risk / execution code.** Every numeric, boolean, list, enum lives in a profile JSONB blob fronted by a registry of profile-scoped keys + safe defaults. Strategies read parameters through one accessor: `params.get("strategies.funding_arb.entry_bps_per_8h")`. If a literal appears in a strategy file, that is the bug — move it to the registry.

2. **Same profile drives backtest and live.** Strategy logic is a pure function `Strategy.evaluate(state, params) -> Action`. The backtester and the live engine instantiate the same `ProfileParams` from the same `profile_id` and call the same function. No "backtest defaults" parallel to "live defaults". If a knob changes in Strategy Lab, the next backtest and the live bot pick it up identically.

3. **Leak-gap prevention on profile switch.** Applying a profile atomically walks the entire registry; any key absent from the new profile resets to its registry default — never inherits silently from the previous profile. Critical when toggling between conservative / aggressive named profiles in Strategy Lab.

4. **UI tunability — Strategy Lab driven from the registry.** All FieldDefs in the Next.js Strategy Lab page are machine-generated (or asserted-equal) from the registry. Saving = writing JSONB; applying = atomic registry walk; cloning + diff + A/B compare backtests are first-class UI operations.

5. **Decision audit per trade.** Every trade decision row stores `profile_id`, `profile_version`, and `profile_hash` (sha256 of JSONB at decision time). Six months later you must be able to reconstruct exactly which config produced any historical trade.

6. **CI lints enforce 1–5.** AST lint fails any numeric literal in `backend/app/strategies/*.py`. A test asserts every `params.get(path)` call has its path in the registry, and vice versa. A test asserts every FieldDef key in the frontend has a corresponding registry default.

Reference patterns to fork from: `../stockbot/backend/app/services/profile_defaults.py` (registry), `models/strategy_profile.py` (JSONB table), `api/strategy_profiles.py` (atomic apply + leak-gap prevention), `frontend/src/app/strategy-lab/page.tsx` (FieldDef → registry mapping).

## Key findings

- **HLP's lifetime Sharpe is ~2.89, not 5.2.** Annualised return ~20% / vol 17.89% over lifetime. The Sharpe-5.2 figure circulated in promotional content was a cherry-picked recent 52-week window. Documented tail-loss events: $7M (Dec-2024 SOL squeeze), $4M (Mar-2025 toxic liquidation), $4.9M (Nov-2025 POPCAT adversarial attack). HLP is high-Sharpe but **has real left-tail exposure roughly once a year** — not a treasury substitute. — [Geronimo HLP analysis](https://medium.com/@RyskyGeronimo/a-risk-return-analysis-of-hyperliquids-hlp-vault-7c164cd00a0d), [The Block — HLP $4M loss](https://www.theblock.co/post/345866/hype-drop-hlp-vault-loss-hyperliquid-whale-liquidation), [Cointelegraph — POPCAT attack](https://cointelegraph.com/news/hyperliquid-hlp-popcat-attack-3m-wipeout)

- **HLP's structural (fee-only) yield is ~1.69%/yr.** DefiLlama primary-source data: $6.31M annualised fees on $373.62M TVL. The ~18 percentage points of additional historical return come from volatile MM + liquidation alpha. Treating HLP as "passive yield" is a misreading — most of its return is variance-bearing active alpha. — [DefiLlama HLP](https://defillama.com/protocol/hyperliquid-hlp)

- **Retail algo traders fare materially better than discretionary day traders.** ~60% of retail *algorithmic* traders post positive annual returns; the catastrophic 89–95% fail rate applies to *discretionary* day traders. But ~80% of first-attempt backtested strategies fail in live — the survival path requires walk-forward discipline, paper-trading proof, and live-small before scaling. — [HedgeFundAlpha study](https://hedgefundalpha.com/news/retail-traders-lost-volatility-event/), [Tradealgo 2026 reality check](https://www.tradealgo.com/trading-guides/tools/is-algorithmic-trading-worth-it-costs-returns-and-a-reality-check-for-2026)

- **Funding-rate arbitrage realised returns are regime-dependent: 5–30% APR.** BTC/ETH calm markets: 5–8% APR. Alt funding spikes: 20–40% APR. Cannot be assumed constant. Live verification of current funding-rate level is required before committing capital. — [Buildix delta-neutral 2026](https://www.buildix.trade/blog/cash-and-carry-crypto-delta-neutral-funding-rate-strategy-2026), [Bitget funding-arb guide](https://www.bitget.com/news/detail/12560604395607)

- **Cross-sectional multi-factor crypto portfolios remain validated** for retail-scale alpha. Capacity ~$100k–$200k before alt liquidity binds. Realised Sharpe 0.8–1.5 — below HLP's lifetime Sharpe but **uncorrelated to HLP's edges** (HLP makes no directional alt picks). Stockbot's scoring engine (`services/scoring.py`) is forkable for this with crypto-native components. — [Quantt — strategies that work 2026](https://www.quantt.co.uk/resources/quant-trading-strategies-guide), [Sentora multi-factor crypto](https://medium.com/sentora/thinking-like-a-crypto-quant-multi-factor-strategies-for-crypto-assets-106b765abfb2)

## Trade-offs

| Path | Expected APR | Sharpe | Tail risk | Build time | Pays for itself at |
|---|---|---|---|---|---|
| HLP only (deposit + ignore) | ~20% historical | 2.89 | Real: $4–7M event drawdowns ~1×/yr | 5 min | $5k |
| Pure custom multi-strategy from scratch | 15–25% if you survive Y1 | 1.0–2.0 | High: ~40% of attempts go negative Y1 | 5–6 months | $20k |
| **HLP base + focused active overlay** (alt funding arb + factor portfolio) | **18–25% blended** | **2.0–3.5** | HLP tail + overlay errors (uncorrelated) | **8–12 weeks** | **$10k** |
| Hosted bot (3Commas / Cryptohopper / Pionex) | 5–15% net of fees | 0.5–1.5 | Fee drag, vendor lock-in, no control | Days | Rarely beats HLP |

## Recommendation

**HLP base (40–60% of capital) + a focused active overlay on the remaining 40–60%.** The overlay runs two strategies *uncorrelated* to HLP's edges:

- **Alt funding arbitrage** (HLP barely touches the deep tail of alt perps; this is genuine complementary edge during funding spikes)
- **Cross-sectional alt factor portfolio** (HLP makes no directional alt picks; forked from stockbot's scoring engine with crypto-native components)

**Why this dominates the alternatives:** HLP's risk-adjusted return is hard to replicate as a solo dev — don't compete with it on the same edges (CEX MM, majors funding capture). Use it as the high-Sharpe yield engine on most of your capital, and build a small overlay that is *additive, not heroic*. Combined target: 18–25% APR at Sharpe 2.0–3.5, build time 8–12 weeks, profitable at $10k+ capital.

This revises the earlier "50–70% HLP" recommendation downward because primary-source data shows HLP has more tail risk than promotional sources implied.

## Open questions

- **Current funding-rate regime.** Live May-2026 BTC/ETH funding rates could not be retrieved from data sources in the research round. If currently compressed (<0.005% per 8h), the funding-arb leg contributes only ~3% APR and the overlay should lean factor-portfolio. — Resolves by manually checking [coinglass.com/FundingRate](https://www.coinglass.com/FundingRate) before committing capital.
- **HLP's behaviour in extended sideways markets.** All documented loss events were liquidation-driven; calm markets compress HLP returns toward the 1.7% fee floor. No 2026 data on HLP's worst calendar *quarter* (only worst day). — Resolves by waiting for / requesting longer-horizon analyst writeups, or paper-tracking HLP across a known low-vol regime.
- **Actual capital target.** Below $5k this is uneconomic vs HLP alone; above $200k the overlay's capacity binds and the mix should tilt heavier to HLP. The 8–12 week build is most justifiable in the $20k–$100k band. — Resolves by user committing to a specific capital range.

## Implementation findings (Round 2)

These extend the strategic recommendation above with concrete platform, framework, data-source, and OpEx choices. The Round 1 recommendation (HLP base + active overlay, 40–60% allocation) stands; this section answers *how* to execute it.

### How the load-bearing constraints shape the Round 2 stack

| Constraint | Implication for the stack choice |
|---|---|
| No hardcoded values in strategy code | Registry + `ProfileParams` accessor sits *between* Freqtrade strategy classes and the centralised JSONB profile. Freqtrade's own per-strategy config is treated as a thin shim that reads from our registry, not as the source of truth. |
| Same profile drives backtest + live | Freqtrade's `dry_run` mode and `backtesting` mode both load the strategy class with the same `ProfileParams` instance. We do **not** use Freqtrade's hyperopt directly — the registry is canonical; hyperopt-style sweeps run via our backtester against `profile_id` candidates. |
| Leak-gap prevention | Profile apply is a single Postgres transaction that walks the registry; never an in-place JSONB merge. Mirrors `api/strategy_profiles.py` in stockbot. |
| UI tunability from registry | Next.js Strategy Lab page fetches the registry + active profile from the FastAPI brain layer (not from Freqtrade). FieldDefs auto-generated from registry, with validators. A/B compare runs two backtests with two `profile_id`s. |
| Decision audit per trade | Every Freqtrade fill is written via a callback into our Postgres `trade_decisions` table with `profile_id`/`version`/`hash` snapshot. Freqtrade's own trade log is *not* the source of truth. |
| CI lints | AST scan over the strategy modules under `backend/app/strategies/` (the layer we control, not Freqtrade core); registry ↔ FieldDef cross-check; pre-commit hook enforces. |

The bridge layer (between our central profile and Freqtrade strategy classes) is the single most important piece of infrastructure the build creates — it's what allows us to use Freqtrade's plumbing without surrendering the profile-as-source-of-truth discipline.

### Round 2 updates to Round 1 findings

- **HLP's *current* APY is ~10%**, not the lifetime ~20%. May 2026 is a calmer regime — less liquidation activity = less HLP alpha. Sharpe-strong but raw yield is lower than promotional figures imply right now. The HLP allocation reasoning still holds; the absolute return number for budgeting purposes should use 10% APY, not 20%. — [ARX HLP Vaults Explained 2026](https://arx.trade/blog/hyperliquid-vaults-explained/)
- **HLP depositors earn a 3x HYPE airdrop multiplier** on deposited capital — meaningful kicker not in the Round 1 analysis, contingent on HYPE token holding value.

### Concrete stack — exchanges

| Exchange | Use for | Rationale |
|---|---|---|
| **Hyperliquid** | HLP deposit + alt perp leg of overlay | Cheapest perp fees (0.045%/0.015% base; 0.025%/-0.005% rebate on top pairs); on-chain transparent; no KYC; HYPE airdrop multiplier on HLP. |
| **Binance** | Spot leg (arb hedge) + historical data archive | Deepest spot liquidity; USDC-M perps surprisingly competitive at 0.04%/0.00%; Binance Vision is free primary-source data. AU-accessible for spot. |
| **Bybit** | Backup perp venue + alt funding arb fallback | Single-criterion VIP (asset OR volume), AU-legal. Use if HL liquidity binds on a specific alt. |
| Kraken | Failover spot venue only | AU-legal anchor for counterparty diversification. Skip in v1. |
| ~~Coinbase~~ | Skip unless US-based | Fees too high (~0.4–0.6%), shallower liquidity. |

— [CoinPerps fee comparison 2026](https://www.coinperps.com/learn/hyperliquid-vs-binance-fees), [Bitget Bybit fees compare](https://www.bitget.com/academy/bybit-fees-compare)

### Concrete stack — framework

**Freqtrade** for the active overlay strategies. One Freqtrade process per strategy (funding arb + factor portfolio = two processes). Reasons: 25k+ GitHub stars, 7 years battle-tested; 30+ exchanges via CCXT; native dry-run paper trading (same code as live, one flag); FreqAI for walk-forward ML retraining; native Hyperliquid HIP3 support in 2026.1. Custom "brain" layer (FastAPI + Postgres + Next.js, forking stockbot's shape) sits on top for scoring engine, IC tracker, regime detector, allocator, UI.

Skip: NautilusTrader (overkill for retail scale), Hummingbot (market-making only — not our strategies), hosted bots like 3Commas/Cryptohopper (closed source, poor unit economics).

— [Gainium Top 6 Open-Source 2026](https://gainium.io/best/open-source), [alexbobes Freqtrade alternatives honest](https://alexbobes.com/crypto/best-freqtrade-alternatives/)

### Concrete stack — strategies (build priority)

| # | Strategy | Allocation | Realistic APR | Reason for order |
|---|---|---|---|---|
| 0 | **HLP deposit** | 40–60% of capital | ~10% APY (current) + HYPE airdrop | Day-1 yield while you build. Capture even if the build stalls. |
| 1 | **Alt funding arbitrage** | 15–25% | 15–30% (regime-dependent) | Forces all the multi-leg execution, position reconciliation, funding accounting plumbing the harder strategy needs. Structural edge, not predictive. |
| 2 | **Cross-sectional alt factor portfolio** | 15–25% | 10–25% at Sharpe 0.8–1.5 | Forks stockbot's `services/scoring.py` with crypto-native components. Uncorrelated to HLP's edges (HLP doesn't pick alts directionally). Where stockbot expertise pays the highest dividend. |
| 3 | **Meta-allocator** | (orchestration, no own capital) | Adds 1–3% blended | Risk-parity / Sharpe-weighted across HLP, A, B. Build only after 30+ days of live data on each. |

### Concrete stack — data sources

| Tier | Items | Cost/mo | When |
|---|---|---|---|
| Free essentials (start here) | Binance Vision + Bybit public + HL archive + DefiLlama + CoinGecko free (50 calls/min) + Token Unlocks free + Binance public API (1200 weight/min, no key) | **$0** | Day 1 — covers ~85% of needs |
| Pay-when-IC-proves-it | Glassnode Standard ($39, only if on-chain IC ≥0.02 for 30+ days), CryptoQuant Standard ($29) | $0–$70 | Phase 2 (factor portfolio live) |
| Pay-if-strategy-evolves | Nansen Lite ($150 — smart-money flow), Tardis ($200–400 — L2 book history, only if pivoting to MM) | $0–$550 | Phase 3 (proven base) |
| Skip | Glassnode API tier ($700), CryptoQuant API ($800), CoinAPI/Kaiko institutional, Twitter/X API ($100+) | — | Never at retail scale |

— [CoinMarketCap Free API Comparison 2026](https://coinmarketcap.com/academy/article/best-free-crypto-api-in-2026-free-tier-comparison), [Slashdot CryptoQuant vs Glassnode pricing](https://slashdot.org/software/comparison/CryptoQuant-vs-Glassnode/)

### OpEx envelope (local deployment)

| Phase | Components | $/month |
|---|---|---|
| Phase 0 (build only, no live trades) | Local Postgres + Docker + free APIs | **$0–10** |
| Phase 1 (funding arb live) | Above + Claude API LLM overlay ($20–80) + Sentry free tier | **$20–90** |
| Phase 2 (factor portfolio live) | Above + Glassnode Standard $39 (only if IC validated) | **$60–130** |
| Phase 3 (scaling capital ≥$20k) | Above + Hetzner CX22 VPS ($6) + offsite Postgres backup ($1–5) | **$70–140** |

Year-1 OpEx envelope: **$300–$1,500 total**. Phase 3 ceiling stays under $150/mo. Single biggest line is the Claude API for the LLM overlay; everything else combined is under $50/mo.

### Realistic returns by capital tier (the money answer)

| Capital | Year-1 net | Year-2 net | Verdict |
|---|---|---|---|
| $1k–$5k | -$200 to +$300 | $400–$900 | Educational only. Just deposit in HLP. Don't build for money at this scale. |
| **$10k–$20k** | $500–$2,500 | $2,000–$4,500 | **First tier where the build pays for itself.** Mostly HLP yield + small overlay alpha. |
| $20k–$50k | $2,500–$7,500 | $4,000–$11,000 | Sweet spot for the architecture. Overlay alpha becomes meaningful. |
| $50k–$100k | $7,500–$18,000 | $10,000–$25,000 | Real side income. Overlay capacity limits begin binding. |
| $100k+ | Diminishing | Tilt heavier to HLP (overlay capacity-limited) | Architecture caps around $200k–$300k of overlay capital. |

**Year-1 is mostly break-even** because 8–12 weeks of building captures no return, first 30–60 days live are tiny-position learning, and the 73% retail bot failure rate is mostly people who quit before Year 2. Survivors are paid to wait.

### Marketplace context

- Phemex Bot Marketplace: 20,403 active bots, $10.49M combined TVL = **average $514/bot**. Most retail operators run tiny capital — small bot operators are not the right comparison set. — [Phemex Q1 2026 Top 10](https://phemex.com/blogs/top-10-profitable-bot-strategies-q1-2026)
- Disclosed institutional benchmark (read with marketing caveat): multi-pair stat-arb across Binance + Bybit + 3 DEXes — 42% APR, Sharpe 2.3, max DD 9%. Achievable with proper infra; not a retail outcome out of the gate. — [SaintQuant 2026 guide](https://saintquant.com/blog/161-how-to-build-a-profitable-crypto-trading-bot-in-2026-a-quantitative-guide-for-algorithmic-traders)

### Phased milestones (detailed plan = `superpowers:writing-plans`)

| Weeks | Milestone | Trigger to advance |
|---|---|---|
| 0 | Deposit X% of capital in HLP. Day-1 yield begins. | HLP balance reflects |
| 1–2 | Profile system + registry + leak-gap-prevented Postgres tables | All registry keys have validators + test asserts FieldDefs ↔ registry |
| 3–4 | Data pipeline (Binance Vision + Bybit + HL → DuckDB on Parquet) | DuckDB query plotting funding rates vs price for 2yr passes eyeball check |
| 5–6 | Backtester with funding accrual + survivorship-safe universe | Replay BTC 2024 produces realistic return distribution within ±10% of independent published numbers |
| 7–9 | Strategy 1 (alt funding arb) in Freqtrade — backtest, 14-day paper, $500 live | 14 consecutive days where live P&L tracks paper within reasonable bounds |
| 10–14 | Strategy 2 (factor portfolio) in second Freqtrade process | Out-of-sample 30-day backtest Sharpe ≥0.8 + IC tracker shows ≥3 components with positive IC |
| 15 | Meta-allocator (risk-parity Sharpe-weighted between HLP, A, B) | Both A and B have 30+ days of live data |
| 16+ | Production ops + scaling capital | 60d of stable live P&L within ±50% of backtest expectation |

Implementation detail (profile schema DDL, strategy class signatures, registry key list, etc.) belongs in `superpowers:writing-plans` once the user is ready to start.

## Sources

- [DefiLlama — Hyperliquid HLP TVL/fees](https://defillama.com/protocol/hyperliquid-hlp) — primary-source fee yield, TVL
- [Geronimo — Risk & Return Analysis of HLP (Medium)](https://medium.com/@RyskyGeronimo/a-risk-return-analysis-of-hyperliquids-hlp-vault-7c164cd00a0d) — Sharpe / vol / cumulative return calculations
- [The Block — HYPE drops 8.5% amid $4M HLP loss](https://www.theblock.co/post/345866/hype-drop-hlp-vault-loss-hyperliquid-whale-liquidation) — Mar-2025 toxic liquidation event
- [Cointelegraph — Attacker burns $3M to trigger $4.9M HLP loss](https://cointelegraph.com/news/hyperliquid-hlp-popcat-attack-3m-wipeout) — POPCAT adversarial attack
- [KuCoin — HLP vault mechanics](https://www.kucoin.com/news/articles/maximizing-the-liquidation-alpha-how-hyperliquid-s-hlp-vault-converts-whale-losses-into-liquidity-provider-yield) — strategy breakdown
- [ARX — Hyperliquid Vaults Explained (2026)](https://arx.trade/blog/hyperliquid-vaults-explained/) — APY composition
- [On-Chain Times — Analyzing HLP & JLP Returns](https://www.onchaintimes.com/analyzing-hlp-jlp-returns/) — comparative vault returns
- [AInvest — Hyperliquid trader exits $4M loss to HLP](https://www.ainvest.com/news/hyperliquid-trader-exit-shifts-4m-loss-hlp-vault-sparks-systemic-risk-debates-2509/) — systemic risk debate
- [HedgeFundAlpha — Retail Traders Lost 74–89% During Volatility Events](https://hedgefundalpha.com/news/retail-traders-lost-volatility-event/) — retail failure rates
- [Tradealgo — Is Algorithmic Trading Worth It (2026)](https://www.tradealgo.com/trading-guides/tools/is-algorithmic-trading-worth-it-costs-returns-and-a-reality-check-for-2026) — algo trader subset analysis
- [Buildix — Cash-and-Carry / Funding-Rate Delta-Neutral 2026](https://www.buildix.trade/blog/cash-and-carry-crypto-delta-neutral-funding-rate-strategy-2026) — funding-arb realised return ranges
- [Bitget — Funding Rate Arbitrage Decoded](https://www.bitget.com/news/detail/12560604395607) — strategy walkthrough
- [Quantt — 9 Quant Trading Strategies That Work in 2026](https://www.quantt.co.uk/resources/quant-trading-strategies-guide) — factor portfolio capacity
- [Sentora — Multi-Factor Strategies for Crypto-Assets](https://medium.com/sentora/thinking-like-a-crypto-quant-multi-factor-strategies-for-crypto-assets-106b765abfb2) — factor model design for crypto

### Round 2 sources

- [ARX — Hyperliquid Vaults Explained 2026](https://arx.trade/blog/hyperliquid-vaults-explained/) — current ~10% HLP APY + HYPE 3x airdrop multiplier
- [CoinPerps — Hyperliquid vs Binance Fees 2026](https://www.coinperps.com/learn/hyperliquid-vs-binance-fees) — base-tier perp fee comparison
- [Bitget — Bybit Fees Compare 2026](https://www.bitget.com/academy/bybit-fees-compare) — Bybit single-criterion VIP tiers
- [MEXC — Hyperliquid Fees Explained](https://www.mexc.com/news/1034701) — top-pair rebate details
- [Gainium — Top 6 Open-Source Bots 2026](https://gainium.io/best/open-source) — framework landscape consensus
- [alexbobes — Best Freqtrade Alternatives Honest 2026](https://alexbobes.com/crypto/best-freqtrade-alternatives/) — non-promotional framework take
- [CoinMarketCap — Best Free Crypto API 2026](https://coinmarketcap.com/academy/article/best-free-crypto-api-in-2026-free-tier-comparison) — free-tier rate limits
- [Slashdot — CryptoQuant vs Glassnode pricing 2026](https://slashdot.org/software/comparison/CryptoQuant-vs-Glassnode/) — premium-tier pricing
- [Phemex — Q1 2026 Top 10 Profitable Bot Strategies](https://phemex.com/blogs/top-10-profitable-bot-strategies-q1-2026) — marketplace TVL/bot count
- [SaintQuant — Quantitative Guide 2026](https://saintquant.com/blog/161-how-to-build-a-profitable-crypto-trading-bot-in-2026-a-quantitative-guide-for-algorithmic-traders) — institutional case study (marketing caveat)
