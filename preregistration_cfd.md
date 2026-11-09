# Pre-registration: HL HIP-3 (trade.xyz) vs prop-firm demo MT5 CFD backtest v1

Written: **2026-10-27 07:48 UTC**, **before** any backtest results were computed.
Paper research only: no accounts, keys, wallets, orders.
Data availability probes only (MT5 file inventory from the demo terminal export; HL public `info` API; trade.xyz fee docs) were done before freezing this design.

**Hard caveat (stated up front):** The MT5 feed is a prop-firm demo feed, not the retail broker ATJ uses. The prop firm's general terms ban exploiting price feeds / latency / arbitrage. This study is a **proxy for gap and cost structure only**, not a tradable setup.

## 1. Universe and market map

HL HIP-3 markets on the `xyz` dex (trade.xyz) mapped to prop-firm demo MT5 symbols. The demo feed has **US100.cash**, not NAS100. No HL `xyz` US30 / Dow market is listed; US30.cash is therefore **measurement-only on the MT5 side** (no HL pair).

| HL coin | MT5 symbol | Asset | HL growthMode (meta) | Notes / contract differences |
|---|---|---|---|---|
| `xyz:EUR` | EURUSD | FX | enabled | HL quotes EURUSD-style (~1.11). MT5 bid OHLC; HL mid/oracle. |
| `xyz:GBP` | GBPUSD | FX | enabled | Same. |
| `xyz:JPY` | USDJPY | FX | enabled | HL `xyz:JPY` marks ~157 (USDJPY). Confirm scale in data; treat as USDJPY. |
| `xyz:GOLD` | XAUUSD | Metal | **not eligible** (docs: gold excluded from growth mode; meta has no growthMode) | Cash gold CFD vs HL gold perp oracle; weekend HL open / CFD closed. |
| `xyz:JP225` | JP225.cash | Index | enabled | Cash index CFD vs HL perp; session hours / JPY FX basis may differ from HL oracle. |
| `xyz:SP500` | US500.cash | Index | enabled | Same class of cash-index vs perp differences. |
| `xyz:XYZ100` | US100.cash | Index | enabled | Nasdaq-100 cash CFD; HL name is XYZ100 (Nasdaq-100 proxy per trade.xyz). Confirm level alignment. |
| — | US30.cash | Index | n/a | **No HL pair** — excluded from (A)/(B); optional passive MT5-only notes if useful. |

**Session / weekend:** MT5 CFDs are closed on weekends and have daily breaks; HL HIP-3 can trade 24/7. Gap and carry strategies **trade only when both legs have a valid concurrent price** (MT5 bar present). Weekend HL-only moves are reported under (C) as “HL orphan” gap, not traded.

**Price conventions:**
- MT5 bars: **bid** OHLC, `time` UTC. Ask ≈ bid + spread×point. Mid ≈ bid + 0.5×spread×point.
- HL: use mid when available (`midPx`), else mark; candles from `candleSnapshot`. Oracle reported for basis diagnostics.
- Alignment: **M1** bars for (A) and (C); H1/funding grid for (B). Join on UTC minute (HL candle close vs MT5 bar open/close convention documented in results).

## 2. Sample and IS/OOS split

HIP-3 markets are recent. **Actual overlap start = max(HL history start, MT5 M1 available, 2025-01-01) per pair**, reported after the fetch (not invented here). MT5 parquets end **2026-10-07**. Tick live-cost CSVs cover 2026-10-10..24 and **do not overlap** the bar sample.

Given expected short overlap:
- **Full sample:** first overlapping UTC day → 2026-10-07 21:00 UTC (last MT5 bar day).
- **IS / OOS:** if overlap ≥ 60 calendar days: OOS = last **20%** of overlapping days (time-based, not shuffled), IS = the rest. If overlap < 60 days: **no formal OOS**; report full-sample only and mark “sample too short for OOS — exploratory”. Split date frozen once overlap dates are known and written into `results/cfd/sample_split.json` **before** strategy PnL is computed (script writes split first, then backtests).

## 3. Strategies

Equal notional **N = $10,000** per leg unless noted. Delta-neutral by notional at entry.

### (A) Price-gap convergence
- Signal on M1 aligned bars when both venues have a print.
- Gap g_t = (HL_mid − MT5_mid) / MT5_mid.
- Enter when |g| > θ_gap + estimated round-trip cost (both legs) + leg-risk penalty.
  - Long the cheap leg, short the rich: if g > 0 short HL / long MT5; if g < 0 long HL / short MT5.
- Exit when |g| ≤ θ_exit, or timeout T_max minutes, or either leg missing (session end).
- θ_gap grid (IS only if OOS exists): {10, 20, 40, 80} bps. θ_exit = θ_gap / 2. T_max ∈ {30, 120} min — pick by IS Sharpe on portfolio of pairs, freeze for OOS.
- Leg-risk/latency penalty: median |1-minute return| of the HL coin over the prior 3 days (or available), charged once per entry and once per exit (same spirit as crypto v1).

### (B) Carry: HL funding vs MT5 swap (“funding vs swaps”)
- Always-on and threshold-timed variants.
- Hold HL perp one way vs MT5 CFD the other to collect **HL funding received − MT5 swap paid**, net of entry/exit costs when timed.
- Sign: HL positive funding ⇒ longs pay shorts. MT5 swap_long / swap_short in **points** (swap_mode 1); convert to USD using point × contract_size × (tick_value convention from snapshot) — code documents the formula; **never invent rates**.
- Swaps source: `data/mt5/live_costs/swaps_snapshot_2026-10-27.csv` (taken 07:43 UTC 2026-10-27) for **all 8 symbols**. Historical swaps **assumed constant** at that snapshot (state explicitly). Triple swap: **Wednesday** FX/XAUUSD, **Friday** indices.
- Timed variant: enter when 7d trailing net carry (ann.) > θ_c ∈ {5%, 10%, 20%}; exit when < θ_c/2. Always-on is the reference.

### (C) Passive measurement (no trading PnL pass/fail)
- Distribution of g_t (bps): mean, median, p90, p99, by London session hour and weekend vs weekday.
- Half-life of |g| (AR(1) on M1 when both open).
- Share of minutes with |g| above round-trip cost.
- HL orphan minutes (HL prints, MT5 closed).

## 4. Costs (fixed before the run)

### HL HIP-3 fees — official resolution of ATJ vs earlier-note conflict
Source: https://docs.trade.xyz/perp-mechanics/fees (fetched 2026-10-27).
- **Standard** HIP-3 tier 0: **0.090% taker / 0.030% maker** (2× HL validator perps; 50/50 to HL and trade.xyz).
- **Growth mode** tier 0: **0.0090% taker / 0.0030% maker** (≥90% reduction).
- Gold is **not growth-mode eligible**; `xyz:GOLD` uses standard. Other pairs in this universe have `growthMode: enabled` in meta → growth rates.
- ATJ video’s 0.009%/0.003% matches **growth mode**. an earlier internal note’s 0.09%/0.03% matches **standard**. **Both are official**; which applies depends on the market.
- **Run every result under both fee schedules** (growth and standard) for all pairs, and also a **docs-correct** column (growth for growthMode markets, standard for GOLD). Headline pass/fail uses **docs-correct + taker both sides**.

### MT5 (demo feed) costs
- **Do not use** `cost_table.csv` (known double-count of spread).
- Charge **raw spread once per round trip** + commission.
- Commission: FX/metals **$5/lot RT** (~0.5 pip FX majors); **indices 0**.
- Spreads preference: measured live where available (GBPUSD ~0.8 pip all-in London midday; US500.cash fixed 0.60 pt). Else INVENTORY `spread_mean_points_liquid_90d`. Else bar `spread` (per-bar minimum — understates).
- **Do not** use snapshot bid/ask/spread for US100.cash, US30.cash (returned 0) or EURUSD (zero-spread tick in snapshot); use bar/INVENTORY for those.
- Point sizes from inventory/swaps: EURUSD/GBPUSD 1e-5; USDJPY 0.001; XAUUSD/indices 0.01 (indices digits 2).

### Slippage / leg risk
- HL: half-spread proxy from impactPxs or 1 bp floor if thin; charged per fill.
- MT5: already in quoted spread (no extra slip beyond spread+commission) at $10k notional.
- Leg-risk as in §3(A).

## 5. Capital and returns
- Capital on **both** legs: CFD margin using the prop firm's published leverage for that symbol class (FX ~1:100 → margin N/100; indices ~1:100 → N/100; gold ~1:100 — if uncertain use 1:100 FX/index and 1:100 gold as base, and report sensitivity at 1:30). HL margin = N / maxLeverage from meta (or 2x conservative if we cap).
- Headline: **return on total capital** = sum of both margins (+ idle 0%).
- Also report return on notional and return while deployed.
- Annualise: mean daily PnL / capital × 365; Sharpe = mean/std daily × √365 (rf not subtracted; hurdle compared on return).

## 6. Metrics
Net ann. on capital, Sharpe, max DD, turnover, trades, hit rate, avg hold, gross funding, gross swap, spread+commission, HL fees, leg-risk, basis/price PnL. Per-pair and equal-capital portfolio.

## 7. Pass / fail (decided now)
Hurdle ≈ 4.5% (USD cash).
- **Edge:** OOS (or full if no OOS) portfolio net ann. on capital > 4.5% **and** Sharpe > 1.5 **and** max DD < 10% **and** still > 0% at 1.5× costs, under **docs-correct** fees. Judged separately for (A) and (B).
- **Marginal:** net > 0 but fails a hurdle.
- **None:** net ≤ 0.
(C) has no pass/fail; it informs whether (A) is even plausible.

## 8. Bid vs mid verification plan
Live ticks (2026-10-10..24) **do not overlap** parquet end 2026-10-07. Report:
1. Whether parquet `close` sits at tick-style bid levels (pip/point granularity).
2. Consistency of bar `spread` vs live tick spreads for GBPUSD / US500 where both exist (different dates — distributional only).
3. What **cannot** be confirmed: same-timestamp bid/mid identity across the backtest window.

## 9. Data paths
- MT5: `data/mt5/*_{M1,H1,D1}.parquet`, `data/mt5/inventory/`, `data/mt5/live_costs/` (incl. `swaps_snapshot_2026-10-27.csv`).
- HL: `data/hl_hip3/` (funding JSON, candles parquet, meta).
- Code: `pipeline/cfd/`. Results: `results/cfd/`.

## 10. Deviations log
(Append only after the run.)

## 10. Deviations log
- **2026-10-27 ~08:05 UTC (before PnL run):** HL `candleSnapshot` returns at most ~5000 candles and does **not** page earlier when `endTime` is walked back. Measured: 1h history from ~2026-04-01 (pair-dependent; JP225 from 2026-04-09, GBP from 2026-05-18); 1m only from ~2026-10-23. MT5 parquets end **2026-10-07** ⇒ **zero M1 overlap**. Strategies (A) and (C) therefore run on **H1 aligned bars** (prereg said M1). (B) uses hourly funding + H1 prices for basis.
- Swaps: all 8 symbols from `swaps_snapshot_2026-10-27.csv` (07:43 UTC); historical swaps assumed constant at that snapshot (steering update). No symbols marked placeholder/missing.
