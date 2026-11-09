# Perpetual-futures arbitrage: pre-registered backtests

This repo holds research code and write-ups that test whether some popular perpetual-futures "arbitrage" trades leave any money after realistic costs. Everything here is **paper research**. No accounts, API trading keys, wallets or live orders were used. All price data came from public endpoints, except the MT5 CFD leg (see *Data* below).

**Short answer: none of the strategies tested showed a tradeable edge.**

## What was tested

| # | Study | Venues | Pre-registration | Write-up |
|---|---|---|---|---|
| 1 | Crypto funding carry, v1 (8h grid): (a) a threshold-timed cross-venue funding spread, and (b) cash-and-carry (short the HL perp, long Binance spot) | Hyperliquid, Binance USDT-M, Bybit linear | [`preregistration.md`](preregistration.md) | [`results/carry_backtest_v1.md`](results/carry_backtest_v1.md) |
| 2 | Crypto funding carry, v2: rerun on 1-minute marks with liquidations at 1x, 1.5x and 2x | Hyperliquid, Binance | [`preregistration_v2.md`](preregistration_v2.md) | [`results/v2/carry_backtest_v2.md`](results/v2/carry_backtest_v2.md) |
| 3 | HIP-3 (trade.xyz) perps vs MT5 CFDs, hourly: gap mean reversion and funding-vs-swap carry | Hyperliquid HIP-3, MT5 demo feed | [`preregistration_cfd.md`](preregistration_cfd.md) | [`results/cfd/cfd_backtest_v1.md`](results/cfd/cfd_backtest_v1.md) |
| 4 | HIP-3 vs MT5 CFDs, minute-level gap test | Hyperliquid HIP-3, MT5 demo feed | [`preregistration_cfd_m1.md`](preregistration_cfd_m1.md) | [`results/cfd_m1/cfd_m1_backtest_v1.md`](results/cfd_m1/cfd_m1_backtest_v1.md) |

Studies 3 and 4 test the HL-against-MT5 design that the ATJ Research YouTube channel promotes. **ATJ's own profit figures have not been verified** and are not relied on here.

A working paper covering studies 1 and 3 is in [`paper/`](paper/) ([`paper.pdf`](paper/paper.pdf), LaTeX source `paper.tex`).

## Method

- **Pre-registration.** The design, cost model and pass/fail criteria for each study were written down and frozen before any backtest result was seen. Later deviations are logged at the end of each pre-registration file.
- **In-sample / out-of-sample split.** Parameters are chosen in sample only. For the crypto studies the sample runs from 2024-11-01 to 2026-10-26, with out of sample starting on 2026-07-26.
- **Costs.** The model uses each venue's published base-tier taker and maker fees, slippage measured as VWAP against real order books for USD 10k (and a USD 100k stress), a leg-risk penalty, and for MT5, spreads and commission taken from tick bid/ask rather than bar spreads. Cost sensitivities run from 0x to 2x.
- **Minute-level liquidations (v2).** Each leg is checked against its own venue's mark price every minute, using tiered maintenance-margin tables. Collateral transfers between venues take 45 minutes and cost $5 each. A separate auto-deleveraging (ADL) stress force-closes the Hyperliquid short at 2025-10-10 21:15 UTC.
- **Gap handling (v2).** The pre-registered path closes both legs whenever the minute data has a gap, then re-enters. "Hold through gaps" is run as a sensitivity.

## Headline results

All figures are annualised returns on capital, taken from the files in `results/`.

**1. Carry v1** ([write-up](results/carry_backtest_v1.md))
- (a) The cross-venue funding spread showed **no edge**. It made +0.74%/yr in sample and **−0.20%/yr out of sample**, and all 8 out-of-sample trades lost money.
- (b) Cash-and-carry made **+3.13%/yr out of sample, which is below the pre-registered 4.5% hurdle, so it fails.**

**2. Carry v2, 1-minute with liquidations** ([write-up](results/v2/carry_backtest_v2.md), [`verdicts.csv`](results/v2/verdicts.csv)). **It fails at every leverage.**

| Leverage | OOS (pre-registered flat-at-gaps path) | Liquidations (flat) | OOS (hold-through-gaps sensitivity) | Liquidations (hold) |
|---|---:|---:|---:|---:|
| 1x | −20.0% | 0 | +1.2% | 6 |
| 1.5x | −31.0% | 9 | −2.9% | 20 |
| 2x | −49.8% | 23 | +0.5% | 38 |

- Most of the flat-path losses come from repeated exit and re-entry costs at gaps in the archive data.
- On 10 Oct 2025, the 2x hold path ended at about +3.5% in the base case and −6.1% under the ADL stress. v1's rough −19% estimate for that day overstated the loss.

**3. HIP-3 vs MT5, hourly** ([write-up](results/cfd/cfd_backtest_v1.md)). There was **no edge**. Gap convergence returned −7.8%/yr out of sample, and neither strategy cleared the pre-registered bar.

**4. HIP-3 vs MT5, minute gap test** ([write-up](results/cfd_m1/cfd_m1_backtest_v1.md)). This is **preliminary and not significant.** With only about 3.5 days of overlapping data, the test made 15 trades that netted **+$4.21 on $10k per leg**, almost all on JP225. A credible verdict needs about **30 days** of overlapping minute data, preferably with at least 100 trades.

## Data (not included)

No raw or derived market data is in this repo. The raw data runs to many gigabytes, and the MT5 broker feed may not be redistributed. The code writes data to `data/` by default, and you can point it elsewhere by setting the `PERPS_DATA` environment variable. To regenerate the data from public sources:

| Data | Source | Script |
|---|---|---|
| Funding history, 4h prices, order books (HL / Binance / Bybit) | Public REST APIs, no key needed | `pipeline/fetch_history.py`, `pipeline/measure_costs.py`, `pipeline/collector.py` |
| Binance 1m mark and spot klines, funding | [data.binance.vision](https://data.binance.vision) | `pipeline/v2/fetch_binance_1m.py` |
| Hyperliquid per-minute mark/oracle/funding (`asset_ctxs`) | `s3://hyperliquid-archive` (**requester-pays**: needs your own AWS credentials in the standard env vars and incurs small transfer charges) | `pipeline/minute/hl_archive_sync.py` |
| HIP-3 1m candles | Hyperliquid `info` API `candleSnapshot` (keeps only about 3.5 days of 1m bars, so run it every few days) | `pipeline/minute/hl_1m_backfill.py`, `pipeline/cfd/fetch_hl_candles.py` |
| HIP-3 order-book snapshots | Hyperliquid `info` API `l2Book` | `pipeline/cfd_m1/collect_l2book.py` |
| MT5 CFD M1 bars, ticks and swaps | Export these from any MT5 terminal you're licensed to use (parquet, columns `time, open, high, low, close, tick_volume, spread`; ticks with `bid, ask`). The originals came from a prop-firm demo terminal and are proxies only. | `pipeline/cfd/load_data.py`, `pipeline/cfd_m1/load_m1.py` (expected paths are in `common_cfd.py` / `common_m1.py`) |

Typical run order: `fetch_history.py` → `measure_costs.py` → `backtest.py` (v1), then `v2/fetch_binance_1m.py` → `minute/hl_archive_sync.py` → `v2/run_all.py` (v2), then `cfd/backtest_cfd.py` and `cfd_m1/backtest_m1.py` → `cfd_m1/write_report.py`. You'll need Python 3 with pandas, pyarrow, numpy, matplotlib and requests, plus boto3 and lz4 for the S3 archive. See [`docs/LAYOUT.md`](docs/LAYOUT.md) for the older per-study layout notes.

## Caveats

- The MT5 leg is a demo-feed proxy, not a retail broker. Many CFD brokers' and prop firms' terms prohibit latency or price-feed arbitrage.
- Venue access is restricted in some jurisdictions. For example, trade.xyz's terms exclude US, Canadian and UK persons. Check your own legal position.
- One cost snapshot underlies the slippage estimates. Spreads widen in stressed markets.
- v2 found that Binance funding timestamps with sub-second precision had silently dropped settlements. This was fixed in v2. v1 used a different (REST) source and has not been re-audited for the same issue.

## Disclaimer

This is **research only, not financial advice**. Nothing here is a recommendation to trade. Past or simulated performance does not predict future results, and these backtests may contain errors.
