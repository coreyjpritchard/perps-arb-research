# perps-arb — funding-carry research (paper only)

Read-only research on perp funding carry between Hyperliquid, Binance USDT-M and Bybit linear. Public unauthenticated endpoints only;
no accounts, API keys, wallets or orders. Nothing here is scheduled (no cron/systemd).

## Layout
```
preregistration.md          design, costs, pass/fail criteria, written before the backtest; deviations log at the end
pipeline/
  common.py                 HTTP helpers (retry/backoff, rate-limit sleeps, 403/451 geo-block detection), coin list
  fetch_history.py          historical funding (HL fundingHistory, Binance fundingRate, Bybit funding/history) + 4h prices
                            (HL candleSnapshot, Binance perp + spot klines, Bybit kline) -> data/*.parquet
  snapshots.py              order-book fetch + VWAP slippage helpers (HL l2Book, Binance depth, Bybit orderbook)
  measure_costs.py          3 book snapshots + HL 1m vol -> data/cost_params.csv (slippage $10k/$100k, leg-risk penalty)
  collector.py              one-shot snapshot of current funding, HL predictedFundings, Binance premiumIndex, Bybit tickers,
                            top of book + $10k/$100k slippage -> data/collector/snapshots_YYYYMMDD.csv (safe to run hourly by hand or by a scheduler you add)
  backtest.py               the pre-registered backtest; writes results/bt_*.csv and charts
data/                       raw data (git-ignored)
results/
  carry_backtest_v1.md      write-up and verdict
  cum_net_pnl.png, funding_spread.png
  bt_*.csv                  machine-readable outputs; oct10_2025_wick_check.txt, liquidation_stress.txt
```

## Reproduce
```
cd pipeline
python3 fetch_history.py 2024-10-20 2026-10-26   # ~8 min, polite rate limits
python3 measure_costs.py                          # ~5 min (3 snapshots, 2 min apart). NB: overwrites cost_params.csv with today's books
python3 backtest.py                               # ~20 s
python3 collector.py                              # one snapshot
```
Needs python3 with pandas, pyarrow, requests, matplotlib.


## CFD / HIP-3 extension (2026-10-27)
- Pre-registration: `preregistration_cfd.md` (before PnL)
- Pipeline: `pipeline/cfd/` (`fetch_hl_candles.py`, `load_data.py`, `backtest_cfd.py`, `bid_mid_check.py`)
- Data: `data/mt5/` (prop-firm demo feed copy), `data/hl_hip3/`
- Results: `results/cfd/cfd_backtest_v1.md` — verdict **no edge** for gap and carry on this proxy
- Paper: `paper/paper.tex` / `paper/paper.pdf` updated with Section on HIP-3 vs MT5 CFD


## CFD M1 / HIP-3 extension (2026-10-27)
- Pre-registration: `preregistration_cfd_m1.md` (before PnL)
- Pipeline: `pipeline/cfd_m1/`
- Data: `data/mt5_m1/{m1,ticks}/`, `data/hl_1m/`, `data/hl_m1_aux/`
- Results: `results/cfd_m1/cfd_m1_backtest_v1.md` — **descriptive only** (~3.5d overlap); no robust M1 edge on prop-firm demo proxy
