# Cryptobot — Phase 0 Operational Checklist

**Date**: 2026-05-24
**Status**: live (use as a runbook; tick items as completed)

## Scope

The non-code prerequisites that unblock everything downstream. Most items here are exchange-UI clicks + KYC waits — nothing here is gated by code. Highest-leverage item is the HLP deposit which **starts earning immediately** with zero code dependency.

## Key findings

- **HLP deposit is the single highest-leverage non-code action.** ~10% APR currently + 3x HYPE airdrop multiplier on every dollar deposited; lifetime Sharpe 2.89. Every day delayed is foregone yield (no code blocker). — see `cryptobot-strategy-architecture.md` Round 2 + Round 7
- **KYC takes 1–7 business days.** Doing Binance + Bybit KYC now means it's done by the time Phase 5 (exchange adapters) lands — avoids being blocked at week 8+ waiting for KYC.
- **API keys without withdrawal permission are non-negotiable.** Trading-only scope + IP whitelist + separate key per strategy + quarterly rotation.
- **Hardware wallet is *conditional*, not mandatory.** Skip if capital < $2k; defer if $2k–$10k; mandatory at $10k+. — see Round 7 hardware-wallet decision table
- **Stablecoin diversification matters at scale.** USDC depegged March 2023. Target split USDT/USDC/AUD via `risk.stable_mix_pct` registry default (already 0.40 / 0.40 / 0.20).

## Phase 0 checklist (in suggested order)

### A. Today (zero KYC wait — start earning + set up trading wallet)

- [ ] **Sign up Hyperliquid** at `app.hyperliquid.xyz`. No KYC, no email. Connect a fresh wallet (MetaMask is fine for v1).
- [ ] **Authorise a separate Hyperliquid trading wallet** (HL lets you scope an API wallet that can act inside HL only). Limits blast radius if the key leaks.
- [ ] **Bridge USDC to Hyperliquid via Arbitrum.** Cheapest route in 2026 (~$1 gas). Source USDC = step C below.
- [ ] **Deposit 40–60% of starting capital into HLP vault.** Vaults page → HLP → deposit. **4-day lockup** from your last deposit before you can withdraw. Don't try to time this — earlier = more yield + bigger airdrop multiplier compound.

### B. This week (start KYC — they take 1–7 days)

- [ ] **Binance** — sign up + complete identity verification (passport + selfie). AU users: regular Binance.com works for spot; derivatives are restricted (we don't need them; Bybit + HL handle perps).
- [ ] **Bybit** — sign up + KYC. AU-legal as of 2026. Single-criterion VIP (asset OR volume triggers VIP1 — handy if you scale).
- [ ] **Anthropic API key** — sign up at `console.anthropic.com`, generate a key, stash in `.env` (NEVER commit). Pay-as-you-go; doesn't burn money until Phase 14 LLM overlay activates.

### C. Fiat on-ramp (AU)

```
AUD bank account
       │
       ▼ (Independent Reserve OR Swyftx — AU-registered, AUSTRAC compliant)
   AUD → USDC
       │
       ├──▶ Withdraw USDC to Binance     (Strategy A spot leg, Phase 5+)
       │
       └──▶ Withdraw USDC to Hyperliquid (HLP + Strategy A perp + Strategy B; Phase 0 + Phase 5+)
```

**Avoid**: PayPal, credit-card on exchanges (5%+ fees). Direct bank → exchange where possible.

### D. API key configuration (when you create them)

For each exchange API key, **set EXACTLY these scopes**:

| Scope | Setting |
|---|---|
| Spot trading | enabled |
| Derivatives trading | enabled (Bybit + HL only; Binance perps are AU-restricted) |
| **Withdrawal** | **DISABLED — non-negotiable** |
| Margin / lending / staking | disabled |
| IP whitelist | your dev machine's static IP (and later, the VPS IP) |
| Rotation | quarterly cadence + after any incident |

One key per strategy is the goal (avoids halting everything when rotating). For Phase 0 you only need *one* key per exchange; per-strategy keys come in Phase 9+.

### E. Pre-deployment (before Phase 7 testnet plumbing)

- [ ] **Bybit testnet account** at `testnet.bybit.com` — separate signup, separate keys. Free play money from the testnet faucet.
- [ ] **Hyperliquid testnet** at `app.hyperliquid-testnet.xyz` — same wallet flow as mainnet but on test chain.

These come into play around Phase 7 (week 7 in the plan) — don't worry about them until then.

### F. Hardware wallet (conditional)

Per Round 7 decision table:

| Starting capital | Hardware wallet? |
|---|---|
| < $2k | Skip. Software wallet (MetaMask) is fine. |
| $2k–$10k | Nice-to-have. Defer until capital scales. |
| **$10k+** | **Yes — buy Ledger Nano S Plus ($79) from `ledger.com` directly (NOT Amazon — supply-chain attacks have happened).** |
| $50k+ | Mandatory. Don't run without one. |

If you buy:
- [ ] **Initialize Ledger** with a fresh 24-word recovery phrase. Write it down on paper. Store in a safe. Do not photograph. Do not type it anywhere digital.
- [ ] **Use ONLY for cold storage** — sweep idle balance off CEX accounts periodically. Don't use it as your active trading wallet (would defeat the cold-storage purpose).

## Recommendation

**Do A immediately** (today). Then B + C in parallel over the next week.

E + F are gated by the build phase — don't worry about them until you're at the relevant milestone.

## Open questions

- **Capital amount.** Below $5k, the active-overlay build (Phase 3–9) probably isn't economic — just HLP. Above $20k, the full architecture starts paying for itself. The plan assumes $10k–$50k range. — Resolves by user committing to a specific amount.
- **Australian residency assumptions** are baked into the on-ramp recommendation. For other jurisdictions (US, EU, etc.) the fiat ramp differs.

## Sources

- `cryptobot-strategy-architecture.md` Round 2 (current HLP APY, fee tables, exchange selection)
- `cryptobot-strategy-architecture.md` Round 7 (operational primer — full mechanics of HLP, paper trading, sub-accounts, AU fiat ramp)
- [Hyperliquid HLP vault](https://app.hyperliquid.xyz/vaults) — actual deposit UI
- [Independent Reserve](https://www.independentreserve.com) — AU-registered AUD ramp
- [Swyftx](https://swyftx.com.au) — AU-registered AUD ramp
- [Ledger Nano S Plus](https://shop.ledger.com/products/ledger-nano-s-plus) — recommended hardware wallet

## Live-launch checklist (after Phase 9+)

Run BEFORE flipping `live.dry_run_mode=False`:

- [ ] `just preflight` returns ALL CHECKS PASSED
- [ ] `just pg-drill` succeeds (backup is restorable)
- [ ] `POST /api/v1/alerts/test` returns `{sent: true}` (webhook works)
- [ ] `just hl-calibrate` succeeds (HL signing accepted)
- [ ] Dry-run loop ran ≥ 24h with no halts
- [ ] Drawdown brake trigger reviewed (default 5%)
- [ ] $500 USDC funded to ONE venue (start small, scale up)
- [ ] You can stop the runner via `POST /api/v1/live/stop` within 10s
- [ ] Recovery procedure rehearsed: `oms/kill` → `live/stop` → manual position close on venue UI

## Items YOU still have to do operationally

Code can't do these:
1. **Deposit USDC to Hyperliquid HLP vault** (web UI click; ~10% APR + 3x HYPE airdrop multiplier)
2. **Complete KYC** on Binance + Bybit (1-7 days)
3. **Generate Anthropic API key** at console.anthropic.com
4. **AU fiat ramp** via Independent Reserve or Swyftx → USDC → bridge to venue
5. **Set `alerts.webhook_url`** in active profile (Discord/Slack/Telegram URL)
6. **First $500 live trade** — flip flags, monitor, scale based on results
