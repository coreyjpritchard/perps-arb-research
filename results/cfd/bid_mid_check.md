# Bid vs mid verification
Written after data copy; **before** trading backtest PnL interpretation.
Live ticks cover 2026-10-10..24; MT5 parquets end 2026-10-07 — **no overlapping timestamps**.

## 1. Parquet close pip/point granularity (last 5 M1 bars)
- **EURUSD**: last close=1.11867, mean |close/point fractional|=0.0000, spread pts last5 mean=0.00 (bar min; often 0 on FX M1)
- **GBPUSD**: last close=1.32302, mean |close/point fractional|=0.0000, spread pts last5 mean=12.00 (bar min; often 0 on FX M1)
- **USDJPY**: last close=158.285, mean |close/point fractional|=0.0000, spread pts last5 mean=2.00 (bar min; often 0 on FX M1)
- XAUUSD: MISSING
- **JP225.cash**: last close=68789.5, mean |close/point fractional|=0.0000, spread pts last5 mean=1000.00 (bar min; often 0 on FX M1)
- **US500.cash**: last close=7767.45, mean |close/point fractional|=0.0000, spread pts last5 mean=60.00 (bar min; often 0 on FX M1)
- **US100.cash**: last close=31007.13, mean |close/point fractional|=0.0000, spread pts last5 mean=157.00 (bar min; often 0 on FX M1)

## 2. Live tick bid/ask conventions (GBPUSD, US500.cash)
- **GBPUSD**: n_ticks=23028 from 6 files; cols=['tick_time_utc', 'tick_time_london', 'symbol', 'bid', 'ask', 'spread', 'spread_unit']; bid mean=1.32466, ask mean=1.32470, spread mean=0.3998 pip
  parquet last close (≤2026-10-07)=1.32302; first tick bid in live window≈1.32535; gap days≈3 — cannot confirm same-bar bid identity.
- **US500.cash**: n_ticks=594 from 2 files; cols=['tick_time_utc', 'tick_time_london', 'symbol', 'bid', 'ask', 'spread', 'spread_unit']; bid mean=7822.12034, ask mean=7822.73125, spread mean=0.6109 pt
  parquet last close (≤2026-10-07)=7767.45000; first tick bid in live window≈7822.83000; gap days≈3 — cannot confirm same-bar bid identity.

## 3. What we can / cannot confirm
- **Can:** parquet closes sit on point grid consistent with bid quotes; live ticks have bid<ask with positive spread; GBPUSD/US500 live spread distributions match broker data notes (GBPUSD tight; US500≈0.60).
- **Cannot:** same-timestamp verification that parquet OHLC equals tick bid inside the backtest window (no overlap). Mid is constructed as bid + 0.5×spread×point using inventory/live spreads.
