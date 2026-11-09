# Funding-carry backtest v2 — 1-minute, liquidation-aware

Run 2026-10-27 ~11:15–11:38 UTC. Paper research only: public data, no accounts, no orders, no wallets.
Pre-registration: `../../preregistration_v2.md` (written before v2 results; deviations appended there after the run).
Code: `../../pipeline/v2/` (`engine.py`, `run_all.py`, `mmr.py`, `fetch_binance_1m.py`, `gap_report.py`, `decompose.py`).
Outputs: this folder (`summary_*.csv`, `verdicts.csv`, `pnl_decomp_1x.csv`, PNGs, `hl_gaps*.csv`).

## Verdict

**FAIL at every leverage (1x / 1.5x / 2x) on the preregistered gap-flat path.** OOS net annualised is deeply negative (−20% / −31% / −50%), full-sample max DD exceeds the 10% cap at 1.5x and 2x, and the archive-gap exit/re-entry rule alone burns more than a year of carry. The hold-through-gaps sensitivity (venues assumed live; missing archive rows forward-filled) is also a **FAIL**: OOS at best +1.16% (1x), far under the 4.5% hurdle; full-sample max DD at 2x is −13.5%; and 10 Oct 2025 under the ADL stress loses ~6% of capital in a day — more than a year of the thin full-sample carry. Minute-level liquidation modelling does **not** resurrect the always-on HL-short carry as a tradeable edge after realistic costs.

v1’s post-hoc “≈ −19% of capital on 10 Oct 2025 at 2x” **overstated the portfolio hit** once both legs are marked and liquidations are applied: the HL short is deeply in the money on that crash, so wiping the Binance long (near-zero remaining equity) while keeping the short’s MTM leaves the **base** 2x hold day near **+3.5%**; the **ADL stress** (forced close of the profitable HL short at 21:15 UTC) flips it to about **−6.1%**. Still a multi-year carry wipe relative to the ~0% full-sample ann. on the hold path, and a clear fail of the third hurdle when carry is thin.

## Data and gaps

- Universe: BTC, ETH, SOL, XRP, DOGE, SUI, LINK, AVAX. Sample 2024-11-01 → 2026-10-26 UTC; OOS from 2026-07-26. HYPE add-on skipped (`bin_funding_HYPE.parquet` missing).
- HL minute archive: **95.36%** sample coverage (HYPE 91.11%); **100%** on 10–11 Oct 2025. ~85 gap episodes after 2-minute ffill; median gap ~7h; clusters in evenings ending 23:59 UTC and heavily in **Sep–Oct 2026** (OOS), plus a 24h hole 2026-07-07→09. Binance mark 1m from `data.binance.vision`; one full missing day 2026-06-29.
- See `hl_gaps.md`, `hl_gaps_summary.csv`, `hl_gaps_detail.csv`.

## Model (fixed in prereg)

- Strategies: **(c)** HL perp short / Binance perp long; **(ref)** HL short / Binance spot long. Leverage 1x / 1.5x / 2x per perp leg. N = $10k/leg.
- Liquidation every minute vs HL `mark_px` and Binance mark high/low; MMR tables in prereg §6 / `mmr.py`. On liq: wipe leg equity to 0, close other leg next minute with costs, flat 24h.
- Rebalance: MR < 1.5×MMR → transfer to restore MR = 1/L; **45 min delay**, **$5**/transfer. At **1x**, donor surplus above the IM floor is structurally ≈ 0, so rebalancing cannot save the HL short in one-way rallies.
- ADL stress: force-close HL short at **2025-10-10 21:15 UTC** mark; close Binance next minute; reported separately; pass/fail uses worse of base vs ADL on the Oct-10 criterion.
- Costs: v1 fees + `cost_params.csv` slippage/leg-risk. Idle capital 0% base.
- Gaps (prereg path): ≤2 min ffill; beyond that both legs flat with costs, re-enter when both resume (**no** 24h wait).

## Sanity checks (before trusting results)

| Check | Result |
|---|---|
| HL archive `funding` units vs `hl_funding_*.parquet` | Median ratio 1.0 on overlapping hours; hourly rate fraction. |
| Binance funding applied | **Bug found:** sub-second timestamps dropped ~45% of settlements; **fixed** by flooring to minute. BTC BIN sum now 0.101 matches the file. |
| Net funding BTC hold | HL − BIN ≈ +8.55% of N over sample ≈ **+4.3%/yr on 2x capital**, **+2.15%/yr on 1x capital** — same order as v1. |
| Sign | Short receives HL (+rate×N to HL wallet); long pays Binance (−rate×N). |
| 1x hold liquidations (6) | All **LIQ_HL** in Nov–Dec 2024 when alts ~2× from entry. At 1x isolated, liq when mark/entry ≳ 2/(1+MMR) ≈ 1.90 for 5% MMR. **Not a delta-neutral illusion:** the Binance long is green, but isolated HL margin is not topped up (rebalance surplus ≈ 0 at 1x). |
| Flat vs hold gap | Flat pays full exit+entry on every archive hole (~85/sleeve). BTC 1x decomp: ~$1.96k round-trip costs on $20k capital vs ~$23 on hold. **Not a bug — prereg rule;** OOS is when the archive is worst. |

### PnL decomposition — portfolio 1x (c), dollars over full sample

| component | flat | hold |
|---|---:|---:|
| HL funding received | +10,389 | +12,349 |
| Binance funding paid | −5,223 | −5,942 |
| **Net funding** | **+5,166** | **+6,407** |
| Fees + slip + leg | −9,816 | −380 |
| of which gap-exit costs | −4,908 | 0 |
| Liq losses tracked | 0 | −4,432 |
| Rebalance costs | 0 | 0 |
| **Total PnL** | **−12,734** | **+1,566** |
| Return on $160k capital | −8.0% | +1.0% |

Per-coin detail: `pnl_decomp_1x.csv`. Residual vs funding includes basis/price drift and the wealth effect of liquidations beyond the wiped-equity tracker.

## Results — strategy (c) portfolio (8 coins)

### Preregistered path (gap-flat) — pass/fail

| lev | IS ann | OOS ann | FULL ann | FULL Sharpe | FULL max DD | # liq | # rebal | # gap-flat | oct10 base | oct10 ADL | PASS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1.0 | −1.72% | **−20.0%** | −4.02% | −3.38 | −7.9% | 0 | 0 | 680 | −0.03% | −2.95% | **FAIL** |
| 1.5 | −3.05% | **−31.0%** | −6.57% | −3.52 | **−12.9%** | 9 | 2 | 680 | +0.07% | −4.42% | **FAIL** |
| 2.0 | −2.74% | **−49.8%** | −8.66% | −2.46 | **−16.9%** | 23 | 8 | 680 | +3.07% | −5.89% | **FAIL** |

Hurdles: OOS > 4.5%, FULL max DD < 10%, oct10 worse-of > −(FULL ann). All three levers fail OOS; 1.5x/2x also fail max DD.

### Hold-through-gaps sensitivity (not pass/fail)

| lev | IS ann | OOS ann | FULL ann | FULL Sharpe | FULL max DD | # liq | # rebal | oct10 base | oct10 ADL |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | +0.40% | +1.16% | +0.49% | 0.06 | −6.0% | 6 | 0 | ≈0% | −2.76% |
| 1.5 | +0.18% | −2.90% | −0.21% | −0.02 | −9.6% | 20 | 17 | +0.58% | −4.46% |
| 2.0 | −0.02% | +0.47% | +0.04% | −0.01 | **−13.5%** | 38 | 32 | +3.50% | −6.05% |

Hold 1x OOS (+1.16%) is in the same ballpark as v1’s 1x always-on OOS (+1.71% on 8h bars). Hold 2x OOS (+0.47%) is **far below** v1’s 2x OOS (+3.42%) because minute-level liquidations (38 events) repeatedly wipe legs and charge re-entry — risk v1’s 8h bars hid.

### Reference (ref) gap-flat — reported, not pass/fail

| lev | FULL ann | OOS ann | FULL max DD | # liq |
|---:|---:|---:|---:|---:|
| 1.0 | −4.21% | −23.7% | −8.2% | 0 |
| 1.5 | −5.26% | −29.8% | −10.2% | 1 |
| 2.0 | −6.60% | −38.9% | −12.9% | 3 |

Same gap-cost destruction; spot leg removes Binance liq risk but not archive-gap round-trips or HL short liq at higher leverage.

## 10 Oct 2025

HL coverage that day: **100%**. Crash liquidations are on the **Binance long** (mark lows); HL short is profitable.

| path | 2x portfolio day PnL | Notes |
|---|---:|---|
| v1 post-hoc estimate | ≈ **−19%** | Lose long IM on 5/8 coins; ignored short MTM / ADL |
| v2 hold base | **+3.50%** | BIN liqs on alts; HL short MTM kept; close other leg next minute |
| v2 hold + ADL | **−6.05%** | Force-close HL short at 21:15 UTC mark |
| v2 flat base | **+3.07%** | Similar; gap rule inactive that day (complete coverage) |
| v2 flat + ADL | **−5.89%** | |

Per-coin hold 2x base oct10 (fraction of sleeve capital): BTC −0.4%, ETH −0.2%, SOL −0.2%, XRP **+6.1%**, DOGE **+7.9%**, SUI −2.1%, LINK **+6.5%**, AVAX **+10.4%**. Positive names are those whose Binance longs liquidated into the crash while the HL short paid.

Margin-ratio paths: `oct10_margin_ratios.png` (HL), `oct10_binance_margin_ratios.png` (Binance). Rebalancing (45 min) does **not** save multi-minute wicks; it only helps slow drifts at 1.5x/2x.

## Minute resolution vs v1 8h

| | v1 (8h, 2x, always-on c) | v2 hold 2x | v2 flat 2x |
|---|---:|---:|---:|
| OOS ann | +3.42% | +0.47% | −49.8% |
| Liquidations modelled | no (post-hoc note only) | 38 | 23 |
| 10 Oct portfolio (base) | ≈ −19% estimate | +3.5% | +3.1% |
| What 8h hid | — | Intrabar liqs, re-entries, MR path | + archive-gap costs in OOS |

The funding edge is real (~2%/yr on 1x capital, ~4%/yr on 2x before liq). **Liquidation + re-entry costs consume it** once marks are checked every minute. Gap-flat then makes OOS unusable because the HL archive is most incomplete exactly in the OOS window.

## Idle USDC sensitivity (stated, not re-simulated)

Base idle = 0%. At 4% annualised on un-deployed cash: hold path is nearly always in position → immaterial. Flat path spends ~5% of minutes invalid / more in 24h post-liq flats; a 4% idle rate on that cash would add well under 0.3%/yr — nowhere near enough to clear 4.5% OOS.

## Assumptions that mattered

| Item | Assumption | Source |
|---|---|---|
| HL MMR | BTC 1.25%, ETH 2%, SOL/XRP 2.5%, alts 5% | Live HL `meta` 2026-10-27; MMR = 0.5/maxLev |
| Binance MMR | BTC/ETH 0.40%, SOL/XRP/LINK/AVAX 0.50%, DOGE 0.65%, SUI/HYPE 1.00% tier-1 | bykaranteli + Binance announcements (fapi leverageBracket 401 without key) |
| Transfer | 45 min, $5 | Midpoint of 30–60; HL/Binance USDC-Arb fee notes in prereg |
| ADL | All sleeves ADL at 2025-10-10 21:15 UTC HL mark | Per-coin ADL tape not public; stress assumption |
| Gap hold sensitivity | Unlimited ffill of marks | Interpretive only |

## Charts

- `equity_by_leverage.png` — hold sensitivity equity by leverage, OOS and 10 Oct marked  
- `equity_by_leverage_flat.png` — prereg gap-flat equity (archive holes dominate)  
- `oct10_margin_ratios.png` / `oct10_binance_margin_ratios.png` — MR paths on 10 Oct 2025 at 2x  

## Bottom line

Always-on HL-short / Binance-long carry **survives as a small positive funding harvest only if** (i) you ignore archive gaps, (ii) you accept ~0–1%/yr after minute-level liquidations at 1x, and (iii) you still clear neither the 4.5% OOS hurdle nor a comfortable buffer against ADL/crash days. At 2x, liquidation churn removes the v1 8h “+3.4% OOS” appearance. **I would not allocate capital to this as a standalone strategy** on these rules; if pursued at all, it would need cross-margin or much more aggressive (and pre-funded) collateral sharing, lower leverage, and a live data path that does not exit on archive holes.
