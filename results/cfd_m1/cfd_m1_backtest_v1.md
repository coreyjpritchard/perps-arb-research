# CFD M1 backtest v1 — Hyperliquid HIP-3 (trade.xyz) vs prop-firm demo MT5

Run **2026-10-27 ~10:34 UTC**. Paper research only: public HL API + read-only prop-firm demo MT5 M1/ticks. **No accounts, keys, wallets or orders.**

Pre-registration: `../../preregistration_cfd_m1.md` (written **2026-10-27 10:23 UTC**, before PnL).

**Hard caveat:** The MT5 feed is a prop-firm demo feed, not the retail broker ATJ uses. The prop firm's terms ban arbitrage. This is a **proxy for gap and cost structure only**. ATJ profit claims are **unverified**.

## Verdict
- Overlap is only **3.55 calendar days** (HL 1m ∩ MT5 ticks). Per prereg: **descriptive / illustrative only — no formal pass/fail.**
- **(A) Gap mean reversion (k=2, T_max=30, next-minute fills):** 15 trades; portfolio gross **$31.58**, net **$4.21** on $10k/leg (~0.42 bp of notional). Illustrative IS net **$-5.58**, OOS **$9.79**. Almost all activity is noisy **JP225.cash** (14 trades); GBPUSD has 1 losing trade; other pairs **0 trades** because |gap - roll_median| rarely clears 2× RT cost (persistent basis is not a signal).
- **(B) Session-open / weekend:** 6 reopen events (all weekend after ~48h MT5 close); **0 trades** under k_open=2 (reopen |dev| did not clear threshold after costs, or median not yet available).
- **Bottom line: no evidence of a robust M1 ATJ-style edge on this prop-firm demo proxy.** Tiny positive full-sample net is **inconclusive** (short sample, JP225-dominated, fails under any seriousness bar). Prior hourly CFD work also found no edge (gap OOS −7.8%).

### How much more data for a verdict
- Need **≥10 calendar days** concurrent for the prereg’s non-descriptive mode; a credible test needs **≥30 calendar days** of HL∩MT5 M1 and preferably **≥100 gap trades** under k=2.
- HL `candleSnapshot` keeps ~5000 1m bars (~3.5 days). Keep archiving via `pipeline/minute/hl_1m_backfill.py` (Mon/Wed/Fri+) so history accumulates beyond the API window.
- The MT5 export refreshes weekdays **23:15 UTC** — continue copying `data/mt5_m1/{m1,ticks}/`.

## Time offset
- Chosen: **subtract 0 h** (i.e. labels already UTC). Votes EURUSD/XAUUSD/US500 all chose 0 by min MAE of gap vs offsets {0,2,3}. Evidence in `time_offset.json`.
- Offset +2/+3 roughly **doubled** MAE (EURUSD MAE 4.3 → 8.6/9.9 bps) — consistent with true UTC labeling on the export.

## Data inventory / issues
- Tick files: **140/140** (20 days × 7 symbols). M1: 7 symbols.
- Overlap: `2026-10-23 19:43:00+00:00` → `2026-10-27 08:49:00+00:00` (3.546 d). Mode `descriptive_illustrative_60_40`. Illustrative OOS from `2026-10-25 22:46:36+00:00`.
- **Weekend:** MT5 closed Sat 2026-10-24; Sun reopen ~21:05–22:05 UTC 2026-10-25.
- **XAUUSD Fri gap:** ticks on 2026-10-23 end **20:49 UTC**; HL `xyz:GOLD` 1m starts **20:55 UTC** → essentially no Friday concurrent gold minutes; gold aligned sample starts Sun 22:05.
- **HL candles are trades** (not bid/ask). HL half-spread from live l2Book collector (started this run; **56 coin-rows** so far — early median; floor 1 bp applied). Collector continues in background for ~3h total.
- M1 bar `spread` = min-in-bar — **not used for costs**; costs from tick bid/ask.

## (C) Passive gap / costs

| mt5        | hl         |   n_minutes |   gap_mean_bps |   gap_median_bps |   gap_std_bps |   half_life_min |   frac_abs_gap_gt_cost |   frac_abs_dev_gt_cost |   rt_cost_bps_median |   mt5_spread_bps_median |   hl_half_bps |
|:-----------|:-----------|------------:|---------------:|-----------------:|--------------:|----------------:|-----------------------:|-----------------------:|---------------------:|------------------------:|--------------:|
| EURUSD     | xyz:EUR    |        2196 |         4.1478 |           4.1483 |        1.3667 |          2.995  |                 0.4035 |                 0.0005 |               4.426  |                  0.0894 |        1      |
| GBPUSD     | xyz:GBP    |        2178 |        -1.4949 |          -1.2927 |        4.6196 |         22.0884 |                 0.1185 |                 0.0542 |               6.6798 |                  0.3747 |        1.8778 |
| USDJPY     | xyz:JPY    |        2171 |        -4.567  |          -4.5976 |        1.9406 |          3.2264 |                 0.3058 |                 0.0143 |               5.2191 |                  0.1913 |        1.2682 |
| XAUUSD     | xyz:GOLD   |        2010 |         5.7493 |           5.7113 |        2.1195 |          1.3199 |                 0      |                 0      |              22.1697 |                  1.0225 |        1      |
| JP225.cash | xyz:JP225  |        2074 |         2.9617 |           2.8796 |        4.8823 |          1.1266 |                 0.1543 |                 0.1061 |               7.5112 |                  1.5948 |        1.2608 |
| US500.cash | xyz:SP500  |        2076 |        -3.2546 |          -3.3372 |        1.0587 |          3.3107 |                 0.0101 |                 0      |               5.3651 |                  0.7826 |        1      |
| US100.cash | xyz:XYZ100 |        2011 |         3.1737 |           3.1262 |        0.9219 |          1.1536 |                 0.0303 |                 0      |               5.0062 |                  0.6031 |        1      |

Note: `frac_abs_gap_gt_cost` can be high when a **persistent basis** exceeds cost (e.g. EURUSD ~+4 bps mean), but `frac_abs_dev_gt_cost` (vs 60-min rolling median) is near zero — so mean-reversion signals are rare.

Charts: `gap_series_XAUUSD.png`, `gap_series_US500_cash.png`, `capturable_edge_hist.png`.

## (A) Gap mean reversion — per pair (lat 0s, k=2, T_max=30, $10k/leg)

| mt5        | hl         |   n_minutes |   frac_abs_gap_gt_cost |   trades |   gross_bp |   net_bp |   gross_usd |   net_usd |   is_trades |   oos_trades |   is_net_usd |   oos_net_usd |
|:-----------|:-----------|------------:|-----------------------:|---------:|-----------:|---------:|------------:|----------:|------------:|-------------:|-------------:|--------------:|
| EURUSD     | xyz:EUR    |        2196 |                 0.4035 |        0 |     0      |   0      |      0      |    0      |           0 |            0 |       0      |        0      |
| GBPUSD     | xyz:GBP    |        2178 |                 0.1185 |        1 |    -3.4079 |  -5.5819 |     -3.4079 |   -5.5819 |           1 |            0 |      -5.5819 |        0      |
| USDJPY     | xyz:JPY    |        2171 |                 0.3058 |        0 |     0      |   0      |      0      |    0      |           0 |            0 |       0      |        0      |
| XAUUSD     | xyz:GOLD   |        2010 |                 0      |        0 |     0      |   0      |      0      |    0      |           0 |            0 |       0      |        0      |
| JP225.cash | xyz:JP225  |        2074 |                 0.1543 |       14 |    34.9876 |   9.7876 |     34.9876 |    9.7876 |           0 |           14 |       0      |        9.7876 |
| US500.cash | xyz:SP500  |        2076 |                 0.0101 |        0 |     0      |   0      |      0      |    0      |           0 |            0 |       0      |        0      |
| US100.cash | xyz:XYZ100 |        2011 |                 0.0303 |        0 |     0      |   0      |      0      |    0      |           0 |            0 |       0      |        0      |

Portfolio sum: trades=15, gross_usd=31.5797, net_usd=4.2057, IS_net=-5.5819, OOS_net=9.7876.

## Latency stress (MT5 fill +1/2/5 s via ticks; HL still minute close ± half-spread)

| mt5        |   latency_s |   trades |   gross_usd |   net_usd |   net_bp |   oos_net_usd |
|:-----------|------------:|---------:|------------:|----------:|---------:|--------------:|
| GBPUSD     |           1 |        1 |     -3.3331 |   -5.5072 |  -5.5072 |        0      |
| GBPUSD     |           2 |        1 |     -3.4079 |   -5.5819 |  -5.5819 |        0      |
| GBPUSD     |           5 |        1 |     -2.9592 |   -5.1332 |  -5.1332 |        0      |
| JP225.cash |           1 |       14 |     32.674  |    7.474  |   7.474  |        7.474  |
| JP225.cash |           2 |       14 |     30.61   |    5.41   |   5.41   |        5.41   |
| JP225.cash |           5 |       14 |     29.5827 |    4.3827 |   4.3827 |        4.3827 |

JP225 net shrinks as latency rises (9.79 → 7.47 → 5.41 → 4.38 USD). GBPUSD stays negative. Headline remains latency=0.

## (B) Session-open / weekend

6 reopen events (weekend=6). None produced a k_open=2 entry after costs.
| reopen_time               |   gap_hours | weekend   |   gap_bps_reopen |   gap_bps_preclose |   gap_med_bps |   rt_cost_bps | mt5        |
|:--------------------------|------------:|:----------|-----------------:|-------------------:|--------------:|--------------:|:-----------|
| 2026-10-25 21:05:00+00:00 |     48.1833 | True      |           7.5295 |             0.8035 |        2.9925 |       12.6215 | EURUSD     |
| 2026-10-25 21:05:00+00:00 |     48.1833 | True      |         -18.252  |            -7.2173 |       -1.851  |       29.8666 | GBPUSD     |
| 2026-10-25 21:05:00+00:00 |     48.1833 | True      |          -6.6223 |            -3.3156 |       -3.2199 |       22.4112 | USDJPY     |
| 2026-10-25 22:05:00+00:00 |     49.2667 | True      |         -23.5107 |             4.7176 |        2.3995 |       13.1574 | JP225.cash |
| 2026-10-25 22:05:00+00:00 |     49.2667 | True      |          -3.3228 |            -0.5239 |       -0.8515 |        5.4451 | US500.cash |
| 2026-10-25 22:05:00+00:00 |     49.2667 | True      |           1.6801 |             4.1713 |      nan      |        5.2622 | US100.cash |

## Costs used
- HL docs-correct taker: growth **0.009%** (non-gold); GOLD **0.09%**. Half-spread = max(l2 median, 1 bp). Taker both sides.
- MT5: tick bid/ask each fill; FX/metal **$5/lot RT**; indices **$0**. Not M1 min-spread. Not `cost_table.csv`.
- Swaps snapshot `data/mt5/live_costs/swaps_snapshot_2026-10-27.csv` available; short M1 holds rarely cross swap/funding.
- HIP-3 fundingHistory pulled to `data/hl_m1_aux/funding_xyz_*.json` (179 hourly rows/coin from 2026-10-20).

## Files
- Code: `../../pipeline/cfd_m1/` (`common_m1.py`, `load_m1.py`, `backtest_m1.py`, `collect_l2book.py`, `write_report.py`)
- Data: `../../data/mt5_m1/`, `../../data/hl_1m/`, `../../data/hl_m1_aux/`
- Results: this folder (`pair_table.csv`, `passive_summary.csv`, `gap_trades.csv`, `latency_sensitivity.csv`, PNGs, …)

## Deviations
See append-only log at end of `preregistration_cfd_m1.md`.
