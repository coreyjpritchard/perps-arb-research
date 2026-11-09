# Pre-registration: HL HIP-3 (trade.xyz) vs prop-firm demo MT5 CFDs — minute-level v1

Written: **2026-10-27 ~10:25 UTC**, **before** any minute-level strategy PnL or gap-vs-cost verdicts were computed.
Paper research only: no accounts, keys, wallets, orders.
Prior context only (not this run’s results): hourly CFD proxy in `preregistration_cfd.md` / `results/cfd/cfd_backtest_v1.md` found **no edge** (gap OOS −7.8%). ATJ Research profit claims are **unverified**. The prop firm's terms ban arbitrage; the MT5 demo data is a **broker proxy only**.

Data-availability probes allowed before freezing this design: confirming MT5 M1/tick copy is in progress, listing HL `data/hl_1m/` file presence, and reading prior fee/swap constants from `pipeline/cfd/common_cfd.py`. No aligned gap series, no trade counts, no PnL.

## 1. Universe and market map (reused from hourly CFD work)

| HL coin | MT5 symbol | Asset | HL growthMode | Notes |
|---|---|---|---|---|
| `xyz:EUR` | EURUSD | FX | enabled | |
| `xyz:GBP` | GBPUSD | FX | enabled | |
| `xyz:JPY` | USDJPY | FX | enabled | HL marks ~USDJPY scale (no inversion of HL). |
| `xyz:GOLD` | XAUUSD | Metal | **not eligible** | Standard HIP-3 fees. |
| `xyz:JP225` | JP225.cash | Index | enabled | Cash index vs perp; JPY FX basis possible. |
| `xyz:SP500` | US500.cash | Index | enabled | Level/basis check required. |
| `xyz:XYZ100` | US100.cash | Index | enabled | Nasdaq-100 proxy. |

Contract sizes / points from `pipeline/cfd/common_cfd.py`: FX 100k (USDJPY 100k USD/lot); XAU 100 oz; JP225 contract 10; US500/US100 contract 1. Point: FX 1e-5 (USDJPY 1e-3); metals/indices 0.01.

## 2. Data sources (this run)

- **MT5 M1 BID bars:** `data/mt5_m1/m1/<SYMBOL>_M1.parquet`. Bar `spread` is the **minimum inside the bar** — **not** used for costs.
- **MT5 ticks (bid/ask):** `data/mt5_m1/ticks/<SYMBOL>_YYYY-MM-DD.parquet`. **Executable** MT5 prices and spreads come from ticks.
- **HL 1m candles:** `data/hl_1m/xyz_<COIN>.parquet` (trade closes, not bid/ask). Extended via `pipeline/minute/hl_1m_backfill.py` before analysis.
- **HL l2Book (optional live):** public `https://api.hyperliquid.xyz/info` snapshots in background for a few hours → measured half-spread + depth per coin. If live sample is thin at analysis time, use whatever snapshots exist and state the window; do not invent spreads.
- **HL HIP-3 funding:** `fundingHistory` with coin `xyz:GOLD` etc. for the overlap window.
- **Swaps:** `data/mt5/live_costs/swaps_snapshot_2026-10-27.csv` (or `swaps*.csv` under the same folder). **Do not use** `cost_table.csv` (double-counts spread).
- Symbols’ MT5 calendar: ~2026-10-08 → this morning; HL 1m from ~2026-10-23 19:43 UTC. **Overlap ≈ 2026-10-23 → now** (a few days).

### Time alignment (must verify before joining)
MT5 server time may be **UTC+2 / UTC+3** (DST). Procedure frozen now:
1. Compare MT5 bar timestamps to HL candle timestamps around a known liquid window (e.g. London open on a weekday).
2. Also compare tick `time` vs M1 bar `time` consistency.
3. Choose a single integer-hour offset (0, +2, or +3) that maximises concurrent-minute overlap of economically sensible levels (EURUSD ≈ 1.1-scale, not off by a full session). Document the chosen offset and evidence in results. **Do not** cherry-pick offset after seeing strategy PnL.

## 3. Sample and IS/OOS — short-sample rule

Expected overlap is **on the order of a few calendar days** of concurrent minutes (HL 1m starts ~2026-10-23).

**Pre-declared rule:**
- If concurrent overlap minutes with both legs valid **across the portfolio** span **< 10 calendar days**, the run is **DESCRIPTIVE ONLY**: report full-sample stats and strategy PnL as exploratory; **no formal pass/fail**; still compute a mechanical first-60% / last-40% time split for transparency and label it “illustrative split, not confirmatory OOS”.
- If overlap ≥ 10 calendar days: IS = first 60% of overlapping UTC minutes (global cut, not shuffled); OOS = remainder. Freeze cut in `results/cfd_m1/sample_split.json` **before** strategy PnL.

Given the known HL start (~2026-10-23) and “today” 2026-10-27, this run is expected to fall under the **descriptive-only** rule. That expectation is frozen here; the script still writes the measured overlap and split file first.

## 4. Strategies

Equal notional **N = $10,000** per leg. Delta-neutral by notional at entry. Trade only when **both** legs have a valid concurrent price (MT5 session open with ticks; HL candle present).

### (A) Gap mean reversion (minute)
- Gap \( g_t = (P^{HL}_t - P^{MT5}_{mid,t}) / P^{MT5}_{mid,t} \) in fraction (report in bps).
  - \( P^{HL} \): HL 1m **close** (trade).
  - \( P^{MT5}_{mid} \): from ticks in that UTC minute: mid = 0.5*(best bid + best ask) using last tick in the minute, or minute VWAP of mid if multiple ticks; if no tick that minute, minute is non-tradable.
- Rolling median \( m_t \) = median of \( g \) over the prior **R = 60** concurrent minutes (min 30 observations or skip).
- Round-trip cost estimate \( c_t \) (fraction): docs-correct HL taker×2 (entry+exit) + HL half-spread×2 + MT5 tick spread (entry+exit, measured) + MT5 FX/metal commission RT + optional latency penalty (see §5). Use **fixed** inventory/live fallback spreads only when tick spread for that minute is missing — and mark those minutes non-primary.
- **Enter** when \( |g_t - m_t| > k \cdot c_t \) with **k fixed in advance: k = 2.0**. Direction: short rich / long cheap (if \( g-m > 0 \): short HL / long MT5; else opposite).
- **Exit** when \( |g_t - m_t| \le 0.5 \cdot c_t \), or hold ≥ **T_max = 30** minutes, or either leg session ends / missing.
- **No IS grid on k or T_max.** Sensitivity (k ∈ {1.5, 2.0, 3.0}) may be reported as secondary, but headline uses k=2, T_max=30.
- Fills: next-minute signal → execute at that next minute’s executable prices (no same-minute look-ahead).

### (B) Session-open / weekend dislocation
- Identify MT5 reopen minutes after daily break or weekend (first minute with ticks after a gap ≥ 3 hours).
- Measure \( g \) at reopen (first concurrent HL+MT5 minute) vs last pre-close gap and vs rolling median from prior session.
- **Trade rule (pre-registered):** if at reopen \( |g - m_{prior}| > k_{open} \cdot c \) with **k_open = 2.0**, enter same direction rule as (A); exit by T_max = 60 min or reversion to 0.5·c. Weekend reopen (gap ≥ 24h) reported separately from intraday reopen.
- This is measurement-first; if fewer than 5 reopen events in the sample, report distributions only and skip pass language.

### Execution model (both)
1. **MT5 leg:** executable tick bid (sell) / ask (buy) at signal minute (or latency-shifted — see below).
2. **HL leg:** candle close ± half measured l2Book spread (buy pays +half, sell receives −half) + slippage floor **1 bp** if measured half-spread < 1 bp or book missing.
3. **Fees:** trade.xyz docs-correct — growth 0.009% taker / 0.003% maker for growth-eligible; **GOLD standard 0.09% / 0.03%**. Headline = **taker both sides**.
4. **MT5 commission:** FX/metals **$5/lot RT**; indices **$0**. Spread from ticks (not M1 bar min-spread).
5. **Latency test (mandatory):** primary = simultaneous minute. Stress: delay MT5 fill by **1s, 2s, 5s** using ticks after the signal timestamp; HL still at that minute’s close+half-spread. Report net PnL sensitivity; headline remains 0s delay.

## 5. Costs summary (frozen)

| Leg | Item | Rule |
|---|---|---|
| HL | Fee | docs-correct taker (growth 0.009% except GOLD 0.090%) per fill |
| HL | Spread/slip | half l2Book touch spread; else 1 bp floor |
| MT5 | Spread | from ticks bid/ask each fill |
| MT5 | Commission | $5/lot RT FX+metal; 0 indices |
| Both | Swaps/funding | accrue while held (HL fundingHistory; MT5 swap snapshot constant) for holds crossing funding/swap events; state if no event in short holds |

**Do not use** `cost_table.csv`.

## 6. Descriptive stats (always; no pass/fail)
Per pair on concurrent minutes:
1. Gap distribution (mean, median, std, p10/p90 of g in bps).
2. Half-life of gap (AR(1) on minute g, or on g − rolling median); report in minutes.
3. Share of minutes where \|g − median_60\| > round-trip cost c (and where \|g\| > c).
4. Spreads by hour-of-day (UTC): MT5 tick spread and HL half-spread (if l2 available).
5. Charts (2–3 PNGs): gap time series with ±cost bands for **GOLD** and **SP500**; distribution of “capturable edge” = (|\tilde g| − c)_+ across pairs.

## 7. Capital and metrics
- Capital both legs as in hourly work: MT5 N/100 + HL N/maxLev.
- Report per pair: overlap minutes, % minutes \|gap\| > cost, trades, gross and **net** PnL in **bp of notional** and **USD on $10k**, IS/illustrative-OOS split.
- Portfolio: equal capital across pairs that traded.

## 8. Pass / fail
Because the sample is expected **< 10 days**, **no formal pass/fail**. Narrative verdict only:
- If illustrative OOS and full-sample net ≤ 0 after costs under docs-correct + latency≥1s: **no evidence of edge at M1 on this proxy**.
- If full-sample net > 0 but sample < 10d: **inconclusive — needs more data** (state how many weeks of overlap would be needed for ≥30 calendar days concurrent and ≥100 trades under k=2).
- Never claim ATJ claims are validated.

## 9. Outputs
- Code: `pipeline/cfd_m1/`
- Results: `results/cfd_m1/` including `cfd_m1_backtest_v1.md`, CSVs, 2–3 PNGs, `sample_split.json`, funding/l2 snapshot files under `data/` as appropriate.
- Deviations: append-only section at end of this file after the run.

## 10. Deviations log
- **2026-10-27 ~10:34 UTC (after PnL):** Overlap measured **3.546 calendar days** (2026-10-23 19:43 → 2026-10-27 08:49 UTC) → mode `descriptive_illustrative_60_40` as pre-declared for <10 days.
- Time offset probes (EURUSD, XAUUSD, US500) all chose **0 h** (export timestamps already UTC); documented in `results/cfd_m1/time_offset.json`.
- HL l2Book half-spreads from a **short live collector** started this run (not multi-hour yet at analysis time); 1 bp floor applied. Collector left running for ~3h total into `data/hl_m1_aux/l2book/`.
- XAUUSD Friday concurrent minutes essentially empty (MT5 ticks end 20:49 UTC; HL GOLD 1m starts 20:55 UTC).
- Session-open strategy: 6 weekend reopens, **0 trades** (threshold not met / median unavailable at first post-gap minute for US100).
- Gap strategy produced trades only in GBPUSD (1) and JP225.cash (14); other pairs 0 under frozen k=2.
- Sensitivity k∈{1.5,3.0} **not** run (prereg allowed as secondary; omitted to keep headline clean on short sample).
- Funding/swaps not accrued into M1 trade PnL (holds mostly 1–8 minutes; no funding timestamp crossed in recorded trades).
