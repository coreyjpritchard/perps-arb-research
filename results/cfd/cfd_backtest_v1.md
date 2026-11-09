# CFD backtest v1 — Hyperliquid HIP-3 (trade.xyz) vs prop-firm demo MT5

Run 2026-10-27 ~08:20 UTC. Paper research only: public HL API + read-only copy of prop-firm demo feed broker bars/swaps. **No accounts, keys, wallets or orders.**

Pre-registration: `../../preregistration_cfd.md` (written 07:48 UTC, before PnL). Deviations logged at its end and below.

**Hard caveat:** The MT5 feed is a prop-firm demo feed, not the retail broker ATJ uses. The prop firm's general terms ban exploiting price feeds / latency / arbitrage. This is a **proxy for gap and cost structure only**, not a tradable setup.

## Verdict
- **(A) Price-gap convergence: no edge.** With next-bar fills (no same-bar look-ahead) the IS grid picks θ=80 bps / T_max=30 min and almost never trades. Portfolio OOS net annualised on total capital = **−7.8%** (1 losing trade). Same-bar fills had produced a spurious GBPUSD “edge”; that collapsed under the pre-registered no-look-ahead discipline.
- **(B) Carry (HL funding vs MT5 swap): no edge.** Directions chosen on IS only. Portfolio OOS **−39.0%** ann. on capital; FULL **−16.9%**. A few pairs (GBPUSD, XAUUSD, US500) are positive on the FULL window under docs-correct fees, but JP225 and US100 lose enough to sink the equal-capital book, and OOS does not clear the 4.5% hurdle.
- **(C) Passive gap:** H1 gaps are small (typical |μ| ≤ 3.2 bps, σ ≈ 3–8 bps; JP225 σ ≈ 16 bps). Half-lives ≈ 0.6–2.7 hours. Persistent mean offsets of a few bps exist (EUR +3.2, JPY −2.9, SP500 −3.2) — consistent with oracle/CFD basis, not a large tradable dislocation once round-trip costs (≈2–3 bps growth-mode; ≈19 bps for GOLD at standard fees) are charged.
- **Bottom line: none.** Neither ATJ-style gap mean-reversion nor passive funding-vs-swap harvest clears the pre-registered pass bar on this prop-firm demo feed proxy. The fee conflict is resolved (both schedules are official; see below). Swaps for all 8 symbols are from the 2026-10-27 07:43 UTC snapshot (historical swaps assumed constant).

## Fee conflict resolution
Official trade.xyz docs ([Fees](https://docs.trade.xyz/perp-mechanics/fees), fetched 2026-10-27):
| Schedule | Tier-0 taker | Tier-0 maker | Applies to |
|---|---|---|---|
| **Standard** HIP-3 | **0.090%** | **0.030%** | Markets not in growth mode; **gold not eligible** |
| **Growth mode** | **0.0090%** | **0.0030%** | Most `xyz:` markets (`growthMode: enabled` in meta) |

ATJ’s video (0.009%/0.003%) = growth mode. an earlier internal note (0.09%/0.03%) = standard. **Both are documented.** Headline results use **docs-correct** (growth for EUR/GBP/JPY/JP225/SP500/XYZ100; standard for GOLD). Sensitivity under pure growth and pure standard is in `gap_results.csv` / `carry_results.csv`.

## Data coverage (per market pair)
HL `candleSnapshot` returns ≤~5000 candles and does not page earlier → **1h from ~2026-04-01** (GBP from 2026-05-18; JP225 from 2026-04-09); **1m only from ~2026-10-23**. MT5 parquets end **2026-10-07** ⇒ **zero M1 overlap**. (A)/(C) run on **H1** (prereg deviation).

| HL | MT5 | Funding start (UTC) | H1 overlap | Overlap days | Notes |
|---|---|---|---|---|---|
| xyz:EUR | EURUSD | 2025-12-23 | 2026-04-01 → 2026-10-07 | 189 | growth |
| xyz:GBP | GBPUSD | 2026-05-18 | 2026-05-18 → 2026-10-07 | 142 | growth |
| xyz:JPY | USDJPY | 2025-12-23 | 2026-04-01 → 2026-10-07 | 189 | HL mark ~157 = USDJPY |
| xyz:GOLD | XAUUSD | 2025-12-22 | 2026-04-01 → 2026-10-07 | 189 | **standard fees**; M1 parquet not fully copied (H1 used) |
| xyz:JP225 | JP225.cash | 2026-04-09 | 2026-04-09 → 2026-10-07 | 181 | cash index vs perp |
| xyz:SP500 | US500.cash | 2026-03-18 | 2026-04-01 → 2026-10-07 | 189 | levels align (~7668) |
| xyz:XYZ100 | US100.cash | 2025-10-13 | 2026-04-01 → 2026-10-07 | 189 | Demo feed has US100 not NAS100 |
| — | US30.cash | — | n/a | — | **no HL pair**; excluded from A/B |

IS/OOS (frozen in `sample_split.json` before PnL): global 2026-04-01 → 2026-10-07 (189d); OOS starts **2026-08-30** (last 20%).

## Bid / mid check
See `bid_mid_check.md`.
- Parquet closes sit on the point grid (fractional part of close/point = 0).
- Live ticks (2026-10-10..15 sample): GBPUSD mean spread **0.40 pip**; US500.cash mean **0.61 pt** — matches the broker data notes. Bid < ask.
- **Cannot confirm** same-timestamp bid identity inside the backtest window (ticks start after parquet end). Mid = bid + 0.5×spread×point using inventory/live spreads (not snapshot spreads for EURUSD/US100/US30).

## Costs used
- MT5: raw spread once per RT + commission ($5/lot FX/metals; indices 0). Prefer live: GBPUSD ~0.3 pip median London open (+ commission → ~0.8 pip all-in per broker data notes); US500.cash 0.60 pt fixed. Else INVENTORY 90d means. **Not** `cost_table.csv`.
- Swaps: `data/mt5/live_costs/swaps_snapshot_2026-10-27.csv` for **all 8 symbols**. Constant historically. Triple Wed (FX/XAU), Fri (indices). USD/day from points × contract × point (USDJPY: /price). **No symbols lack swaps** after the 07:43 UTC snapshot.
- HL: docs-correct fees; leg-risk = median |1h HL return|; next-bar fills for (A).

## (C) Passive gap (H1)
| MT5 | n | mean bps | std bps | p90\|g\| | half-life (h) | frac \|g\| > RT docs |
|---|---|---|---|---|---|---|
| EURUSD | 3242 | +3.20 | 3.09 | 6.7 | 1.41 | 0.74 |
| GBPUSD | 2457 | −0.16 | 7.96 | 11.3 | 0.60 | 0.66 |
| USDJPY | 3243 | −2.93 | 3.75 | 7.2 | 1.66 | 0.65 |
| XAUUSD | 3072 | +2.91 | 3.93 | 7.6 | 1.33 | 0.001 |
| JP225.cash | 2973 | +0.21 | 15.93 | 26.2 | 0.71 | 0.71 |
| US500.cash | 3083 | −3.24 | 2.97 | 6.4 | 2.38 | 0.66 |
| US100.cash | 3084 | +0.12 | 3.76 | 5.9 | 2.73 | 0.52 |

Charts: `gap_histograms.png`, `gap_series_*.png`.

## (A) Gap convergence — portfolio (docs-correct, next-bar, θ=80 bps, T=30m)
| period | net USD | capital USD | ann. on capital | trades |
|---|---|---|---|---|
| IS | −51.00 | 2733 | **−4.51%** | 1 |
| OOS | −22.24 | 2733 | **−7.82%** | 1 |
| FULL | −101.18 | 2733 | **−7.15%** | 3 |

Capital = Σ (N/100 MT5 + N/HL_maxLev) at N=$10k. Pass/fail: **no edge** (OOS net ≤ 0).

## (B) Carry — IS-chosen direction, docs-correct
Mean HL funding (ann., short receives when positive): EUR +2.8%, GBP −3.7%, JPY −4.5%, GOLD +7.2%, JP225 +3.1%, SP500 −0.9%, XYZ100 +3.3%.

| MT5 | IS-chosen direction | FULL funding $ | FULL swap $ | FULL basis $ | FULL fees $ | FULL net $ | FULL ann. on cap |
|---|---|---|---|---|---|---|---|
| EURUSD | short HL / long MT5 | +146 | −141 | −10 | −2 | −7 | −4.7% |
| GBPUSD | long HL / short MT5 | +142 | −48 | +20 | −2 | +112 | +96.0% |
| USDJPY | long HL / short MT5 | +231 | −208 | −14 | −2 | +7 | +4.4% |
| XAUUSD | short HL / long MT5 | +376 | −256 | −13 | −19 | +88 | +34.0% |
| JP225.cash | short HL / long MT5 | +155 | −266 | −222 | −3 | −336 | −113% |
| US500.cash | long HL / short MT5 | +48 | +10 | +17 | −3 | +72 | +46.6% |
| US100.cash | long HL / short MT5 | −172 | −2 | +12 | −2 | −164 | −73.2% |

Portfolio (equal capital per pair): IS **+8.9%**, OOS **−39.0%**, FULL **−16.9%** ann. on capital. Pass/fail: **no edge**.

Chart: `carry_cum_funding.png` (funding leg only).

## Swaps status
All 8 symbols present in `swaps_snapshot_2026-10-27.csv`. **None marked placeholder/missing.** Historical path assumed constant at snapshot (stated limitation).

## Files
- Code: `../../pipeline/cfd/`
- Data: `../../data/mt5/`, `../../data/hl_hip3/`
- Results: this folder (`coverage.csv`, `sample_split.json`, `passive_*.csv`, `gap_*.csv`, `carry_*.csv`, `portfolio_summary.csv`, PNGs, `bid_mid_check.md`)
