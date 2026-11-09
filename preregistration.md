# Pre-registration: perp funding carry backtest v1

Written: 2026-10-26 17:40 UTC, **before** any backtest code was run or any backtest result was seen.
Paper research only: no accounts, keys, orders.

Only data-availability probes were done before writing this (HL fundingHistory reaches back to May 2023;
HL candleSnapshot returns only the latest ~5000 candles per interval, so 4h candles reach back to roughly mid-2024;
Binance fapi, Binance spot, Bybit v5, OKX and data.binance.vision all answered HTTP 200 from the research machine).

## 1. Universe
8 majors listed on all of Hyperliquid (HL) perps, Binance USDT-M perps and Bybit linear USDT perps:
**BTC, ETH, SOL, XRP, DOGE, SUI, LINK, AVAX.**
Excluded: HYPE (Binance USDT-M only listed 2025, not in full sample), BNB (thin on HL), memecoins / new listings.

## 2. Sample and split
- Full sample: **2024-11-01 00:00 UTC → 2026-10-26 00:00 UTC** (~24 months), limited by HL 4h candle history
  (needed for mark-to-market). If any series starts later, that coin's sample starts later and this is reported.
- In-sample (IS): 2024-11-01 → 2026-07-26 00:00 UTC.
- Out-of-sample (OOS): **2026-07-26 → 2026-10-26** (last 3 months). Held out. Only touched once, after IS choices are frozen.
- 7-day trailing-window warm-up is taken from data before the sample start where available.

## 3. Time grid and funding alignment
- Decision/accounting grid: every 8h at 00:00, 08:00, 16:00 UTC (Binance/Bybit settlement times for 8h symbols).
- Funding for a position held over (t-8h, t]: HL = sum of the 8 hourly HL settlements in that window;
  Binance/Bybit = sum of all settlement events with timestamp in (t-8h, t] (handles 4h/1h per-symbol intervals or interval changes).
- Sign convention (all venues): positive rate ⇒ longs pay shorts. Short receives +rate × notional, long pays it.
- Prices: perp close at grid time t (candle closing at t) from HL 4h candles, Binance USDT-M 4h klines, Bybit linear 4h klines,
  Binance spot 4h klines. Missing price at a grid point ⇒ forward-fill at most 1 bar, otherwise the period is flagged as a gap
  and the sleeve is flat through it.
- Signal at t uses only funding settled at or before t; the position is held over (t, t+8h]. No look-ahead.

## 4. Strategies
Equal notional N per leg, delta-neutral by notional at entry. Trailing signal window W = 7 days (21 periods), **not tuned**.
Annualisation of 8h funding: ×(3×365).

(a) **Cross-venue funding spread.** Independent sleeve for every coin × venue pair (HL–Binance, HL–Bybit, Binance–Bybit) = 24 sleeves.
  Trailing spread s = annualised 7d mean of (f_A − f_B). If flat and s > θ: short A perp, long B perp; if s < −θ: the reverse.
  Exit when the trailing spread *in the held direction* falls below θ/2.
(b) **Cash-and-carry.** Per coin: short HL perp, long Binance spot (spot proxy). Enter when 7d trailing HL funding (annualised) > θ,
  exit when < θ/2. Only the positive-funding direction (no shorting spot).
(c) **Naive baseline.** Per coin: short HL perp, long Binance perp, always on from first to last grid point (one entry, one exit).
  Also reported, as a reference only: always-on cash-and-carry (short HL perp, long Binance spot).

θ selection (the only tuned parameter): grid θ ∈ {5%, 10%, 15%, 20%, 30%} annualised, chosen **separately for (a) and (b)**, one θ
for all coins, by **IS portfolio Sharpe** at base costs. That θ is then frozen and applied OOS. All IS grid results are reported.

## 5. Capital, returns
- Margin on each leg posted separately (no cross-venue netting). Base case **2x leverage per perp leg** ⇒ capital per perp leg = N/2.
  (a), (c): capital per sleeve = N (two perp legs). (b): spot leg fully funded N + HL perp margin N/2 = 1.5N.
- Capital is allocated to every sleeve for the whole sample (idle capital earns 0% in the headline; T-bill yield on idle cash is
  *not* added, the hurdle below accounts for it). Portfolio = equal capital per sleeve.
- Reported: return on allocated capital (headline) and return while deployed.
- Sensitivity: 1x and 3x leverage per leg.
- Annualised return = mean daily PnL / capital × 365 (simple, non-compounded). Sharpe = mean/std of daily PnL × √365, rf not subtracted
  (comparison to the hurdle is done on the return).

## 6. Costs (fixed before the run)
Fees, base tier, taker on both legs for entry and exit (conservative; maker sensitivity reported):
| Venue | Taker | Maker | Source |
|---|---|---|---|
| Hyperliquid perps (tier 0) | 0.045% | 0.015% | hyperliquid.gitbook.io/hyperliquid-docs/trading/fees (checked 2026-10-26) |
| Binance USDT-M (Regular) | 0.050% | 0.020% | binance.com/en/support/faq/detail/360033544231, fee schedule (checked 2026-10-26) |
| Bybit linear (VIP 0 / Non-VIP) | 0.055% | 0.020% | bybit.com/en/help-center/article/Trading-Fee-Structure (checked 2026-10-26) |
| Binance spot (Regular) | 0.100% | 0.100% | binance.com/en/fee/schedule (checked 2026-10-26) |
No BNB/HYPE-staking/referral discounts assumed.

Slippage: from current order-book snapshots (HL l2Book, Binance fapi/api depth, Bybit v5 orderbook), VWAP cost vs mid for a market
order of **$10k (base)** and **$100k (stress)** per leg, average of buy and sell side, averaged over ≥3 snapshots a few minutes apart.
Applied per fill (entry and exit). Values recorded in Appendix A before the backtest runs.

Leg risk: legs are assumed filled sequentially with a ~1 minute delay. Penalty per entry and per exit = median absolute 1-minute
return of the coin (from recent HL 1m candles), charged once per round of fills (entry, exit). Values in Appendix A.

Basis drift / rebalancing: captured explicitly by marking both legs to market at every grid point (PnL = long-leg return −
short-leg return, on notional N), so entry/exit basis is in the PnL, not an assumption. No intra-trade rebalancing to restore
delta (drift from unequal notional after big moves is ignored; reported as caveat). Exit basis is whatever the prices are at exit.

Cost sensitivity: 0x, 0.5x, 1x, 1.5x, 2x the base cost bundle; maker-fee variant; $100k slippage variant.

## 7. Metrics
Annualised net return on capital, Sharpe (daily), max drawdown (of cumulative return on capital), turnover (notional traded per
year / capital), number of trades, hit rate (share of closed trades with positive net PnL), average holding period, worst 3
funding-flip episodes (worst 7-day rolling net PnL while in a position), gross funding vs cost breakdown.

## 8. Pass / fail (decided now)
Hurdle: risk-free ≈ 4.5% (USD T-bills / GBP cash ~4-5%).
- **Real edge**: OOS portfolio net annualised return on capital > 4.5% **and** OOS Sharpe > 1.5 **and** OOS max DD < 5%,
  **and** IS net annualised > 4.5%, **and** still > 0% at 1.5x costs OOS.
- **Marginal**: OOS net > 0 but fails at least one of the above.
- **No edge**: OOS net ≤ 0.
Judged separately for (a) and (b); (c) is a reference.

## 9. Venue substitution rule
If Binance or Bybit endpoints are blocked, use data.binance.vision archives for Binance and OKX public API as a substitute for
Bybit, and say so. (At writing, all endpoints answered 200.)

## Appendix A — measured cost parameters (recorded 2026-10-26 ~17:50 UTC, before the backtest was run)
Book snapshots: 3 snapshots 2026-10-26 17:38–17:43 UTC, 2 min apart (data/book_snapshots_raw.csv). Slippage = VWAP vs mid,
average of buy and sell side, includes half-spread; charged per fill per leg. Leg-risk = median |1-minute return| of the coin over the
last 3 days of HL 1m candles, charged once per entry and once per exit.
Rule fixed now: where the HL l2Book (only 20 visible levels/side) cannot fill $100k, the $100k figure is set to 2x the worst other
venue's $100k figure for that coin (marked *).
Caveat: single 5-minute window on one weekday evening; real costs vary with time of day and volatility (hence the cost-multiplier sensitivity).

| coin | venue | spread bps | slip $10k bps/fill | slip $100k bps/fill | depth ±10bps $ | leg-risk bps |
|---|---|---|---|---|---|---|
| AVAX | BIN | 1.11 | 1.31 | 4.76 | 259,821 | 4.13 |
| AVAX | BINSPOT | 1.11 | 2.00 | 8.86 | 120,735 | 4.13 |
| AVAX | BYB | 1.11 | 1.69 | 7.11 | 157,765 | 4.13 |
| AVAX | HL | 1.82 | 1.61 | 17.72* | 91,180 | 4.13 |
| BTC | BIN | 0.01 | 0.01 | 0.04 | 56,632,551 | 1.74 |
| BTC | BINSPOT | 0.00 | 0.00 | 0.09 | 12,969,075 | 1.74 |
| BTC | BYB | 0.01 | 0.14 | 0.28 | 52,039,323 | 1.74 |
| BTC | HL | 0.37 | 0.28 | 0.34 | 11,384,133 | 1.74 |
| DOGE | BIN | 1.29 | 0.64 | 1.43 | 1,476,656 | 3.44 |
| DOGE | BINSPOT | 1.29 | 0.98 | 3.71 | 450,324 | 3.44 |
| DOGE | BYB | 1.29 | 0.64 | 1.92 | 956,992 | 3.44 |
| DOGE | HL | 0.86 | 0.93 | 2.42 | 312,447 | 3.44 |
| ETH | BIN | 0.04 | 0.02 | 0.02 | 25,896,862 | 2.96 |
| ETH | BINSPOT | 0.04 | 0.02 | 0.40 | 5,256,853 | 2.96 |
| ETH | BYB | 0.04 | 0.17 | 0.42 | 26,483,259 | 2.96 |
| ETH | HL | 0.43 | 0.22 | 0.42 | 27,763,702 | 2.96 |
| LINK | BIN | 0.87 | 0.89 | 3.32 | 390,566 | 3.53 |
| LINK | BINSPOT | 0.87 | 1.48 | 6.79 | 185,730 | 3.53 |
| LINK | BYB | 0.87 | 1.09 | 3.54 | 385,240 | 3.53 |
| LINK | HL | 0.87 | 1.91 | 5.23 | 338,588 | 3.53 |
| SOL | BIN | 0.99 | 0.49 | 0.64 | 6,089,572 | 2.97 |
| SOL | BINSPOT | 0.99 | 0.58 | 1.41 | 2,888,971 | 2.97 |
| SOL | BYB | 0.99 | 0.56 | 1.29 | 3,329,538 | 2.97 |
| SOL | HL | 0.99 | 0.61 | 0.84 | 6,130,898 | 2.97 |
| SUI | BIN | 1.09 | 0.79 | 3.26 | 525,997 | 5.16 |
| SUI | BINSPOT | 1.09 | 1.62 | 5.36 | 219,561 | 5.16 |
| SUI | BYB | 1.09 | 1.26 | 4.35 | 332,832 | 5.16 |
| SUI | HL | 0.65 | 1.47 | 10.72* | 89,692 | 5.16 |
| XRP | BIN | 0.77 | 0.58 | 1.22 | 2,492,965 | 3.14 |
| XRP | BINSPOT | 0.77 | 0.39 | 1.39 | 1,168,745 | 3.14 |
| XRP | BYB | 0.77 | 0.39 | 1.01 | 2,399,078 | 3.14 |
| XRP | HL | 0.77 | 0.67 | 1.77 | 2,453,025 | 3.14 |

## Deviations log
1. **Bug fixes after the first full run (2026-10-26 ~17:58 UTC; the first run's IS and OOS summary was printed and seen).** (i) The turnover counter
   always recorded 0, a bookkeeping bug. (ii) The cost of a decision taken at grid time t was booked in the row for period (t−8h, t], so the entry cost at the
   sample start fell outside the IS window. Costs are now booked in the period (t, t+8h]. Neither fix changed the selected θ ((a) 15%, (b) 10%), and no parameter was retuned.
   The OOS numbers moved by less than 0.01 pp. (c) IS fell from 5.44% to 5.36% because its entry cost is now counted.
2. **Post-hoc stress analyses added after seeing results, not used for pass/fail:** (i) 1-minute mark-price check of the 10–11 Oct 2025 crash
   (Binance `/fapi/v1/markPriceKlines`, Bybit `/v5/market/mark-price-kline`) and a rough liquidation-loss estimate for 2x perp legs. (ii) Maximum price
   run-up / drawdown within trades on 8h closes. Both only add risk information and can only make the results look worse.
3. The $100k HL slippage fill-in rule (Appendix A) was fixed after the book snapshots but before any backtest run.
4. The last 8h bucket (2026-10-26 00:00 UTC) has 7 of 8 HL hourly prints (the fetch end boundary excluded the 00:00 print). Left as is; the effect is negligible.
