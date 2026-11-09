# Funding-carry backtest v1 — Hyperliquid vs Binance / Bybit

Run 2026-10-26 ~18:00 UTC. Paper research only: public endpoints, no accounts, no orders.
Pre-registration: `../preregistration.md` (written before the run; deviations logged at its end).
Code: `../pipeline/` (`fetch_history.py`, `measure_costs.py`, `backtest.py`, `collector.py`). Raw outputs: `bt_*.csv` in this folder.

## Verdict
- **(a) Cross-venue funding spread (threshold-timed): no edge.** In-sample it made +0.74%/yr on allocated capital. Out-of-sample it made **−0.20%/yr**,
  with Sharpe −2.17 and all 8 closed trades losing money. In the OOS quarter the spread rarely got above the 15% entry threshold, and when it did, the trade costs
  (about 0.29–0.36% of notional per round trip) were larger than the funding it collected.
- **(b) Cash-and-carry (short HL perp / long Binance spot, timed): marginal.** OOS it made **+3.13%/yr** on capital (Sharpe 7.75, max DD −0.10%). That is below the
  pre-registered 4.5% hurdle, so it fails. IS it made +4.77%/yr, which clears the hurdle only barely. It stays positive OOS at 2x costs (+1.43%), but it does not beat cash.
- **Reference strategies (not used for pass/fail):** being always on beat both timed strategies. HL-short / Binance-perp-long made +5.36% IS and +3.42% OOS. HL-short / Binance-spot-long
  made +5.86% IS and +5.45% OOS. The Sharpe ratios are very high, but they leave out the real risk. Holding the always-on perp/perp hedge at 2x per leg, with no fast collateral top-ups,
  would have had its long legs liquidated on 10 Oct 2025 in 5 of the 8 coins. **Rough estimate: −19% of portfolio capital in one day**, which is about 3.5 years of carry (see the stress section).
  At 1x leverage, which survives that day, the return halves to +2.68% IS / +1.71% OOS, below cash.
- **Bottom line:** the HL funding premium is real and has lasted (see the regime notes). Harvested passively it is roughly a ~5%/yr-on-capital trade. That is about cash plus 0–1%,
  before venue and counterparty risk. **Timing the spread with thresholds destroyed value instead of adding it.** I don't think this is a tradeable edge for a small book at base-tier fees.

## Data
- Universe: BTC, ETH, SOL, XRP, DOGE, SUI, LINK, AVAX. Full sample 2024-11-01 → 2026-10-26 (UTC). IS ends 2026-07-26, OOS = 2026-07-26 → 2026-10-26.
- HL fundingHistory (hourly; 17,664 rows/coin from 2024-10-20), HL candleSnapshot 4h; Binance `/fapi/v1/fundingRate`, `/fapi/v1/klines` 4h, spot `/api/v3/klines` 4h;
  Bybit `/v5/market/funding/history`, `/v5/market/kline` 4h. 4,417 4h bars and 2,209 8h funding prints per coin/venue. All complete for the sample.
- **No venue substitutions.** Binance (fapi + spot), Bybit, HL, OKX and data.binance.vision all returned HTTP 200 from the research machine, so OKX and archives were not needed.
- Gaps: none found inside the sample. The only incomplete bucket is the last one (2026-10-26 00:00). It has 7 of 8 HL hourly prints because the 00:00 print was after the fetch end, so the
  last 8h period slightly understates HL funding.
- Prices are 4h closes sampled on the 8h grid. Intrabar wicks are **not** in the PnL (see the stress section).

### Check of the prior note's claim (last 30 days to 2026-10-26, mean funding annualised)
| coin | HL_30d | BIN_30d | BYB_30d | HL_full | BIN_full | BYB_full |
|---|---|---|---|---|---|---|
| BTC | 8.26% | 3.79% | 3.83% | 10.10% | 5.09% | 5.05% |
| ETH | 8.12% | 3.85% | 3.67% | 9.60% | 4.70% | 5.25% |
| SOL | 6.81% | 3.13% | 2.35% | 5.90% | 1.05% | 2.73% |
| XRP | 9.00% | 3.21% | 3.07% | 7.98% | 3.06% | 4.43% |
| DOGE | 9.66% | 4.51% | 2.91% | 10.75% | 4.88% | 5.64% |
| SUI | 9.16% | 4.62% | 4.73% | 8.12% | 3.74% | 6.26% |
| LINK | 7.81% | 3.62% | 3.85% | 13.21% | 6.01% | 5.72% |
| AVAX | 4.87% | 3.22% | 3.32% | 7.50% | 1.68% | 3.38% |

Confirmed: BTC HL 8.26%/yr vs Binance 3.79% and Bybit 3.83%. Note that HL's neutral rate is 0.00125%/h (10.95%/yr), the interest component when the premium is about 0.
Binance's 8h baseline is the same 0.01% = 10.95%/yr, so neither venue is above its neutral rate. Binance and Bybit just print further below it.

## Cost assumptions (fixed in advance, Appendix A of the pre-registration)
- Fees, base tier, taker on every fill: HL perp 0.045%, Binance USDT-M 0.050%, Bybit linear 0.055%, Binance spot 0.100%. No discounts.
  Sources: HL docs trading/fees; Binance futures fee FAQ and fee schedule; Bybit Trading-Fee-Structure help page (all checked 2026-10-26).
- Slippage per fill from 3 live book snapshots (2026-10-26 17:38–17:43 UTC), VWAP vs mid at $10k/leg (base) and $100k/leg (stress).
  At $10k: 0.01–0.3 bp for BTC/ETH, 0.4–2 bp for alts. At $100k: up to ~9 bp for AVAX spot. HL AVAX and SUI books (20 visible levels) can't fill $100k,
  so per the pre-registered rule they were set to 2x the worst other venue.
- Leg risk: median |1-minute return| over 3 days of HL 1m candles. That is 1.7 bp (BTC) to 5.2 bp (SUI), charged per entry and per exit.
- Round trip, all-in, at $10k: about 0.23% of notional (BTC HL/BIN) to about 0.36% (SUI HL/BYB) for perp/perp, and about 0.33% (BTC) to 0.46% (SUI) for HL perp / Binance spot.
- Capital: margin posted on each venue separately. 2x per perp leg: perp/perp capital = N, carry capital = 1.5N (spot fully funded). Idle capital earns 0%.

## Results — portfolio (8 coins, equal capital per sleeve, base costs, 2x/leg)
| strategy | period | net ann. on capital | Sharpe | max DD | time in pos | net ann. while deployed | turnover x/yr | trades closed | hit rate | avg hold d |
|---|---|---|---|---|---|---|---|---|---|---|
| (a) cross-venue spread, θ=15% | IS | 0.74% | 2.26 | -0.37% | 11% | 7.00% | 11.4 | 118 | 54% | 14 |
| (a) cross-venue spread, θ=15% | OOS | -0.20% | -2.17 | -0.05% | 2% | -8.82% | 5.3 | 8 | 0% | 6 |
| (b) cash-and-carry, θ=10% | IS | 4.77% | 7.76 | -0.19% | 54% | 8.79% | 11.2 | 56 | 70% | 45 |
| (b) cash-and-carry, θ=10% | OOS | 3.13% | 7.75 | -0.10% | 68% | 4.62% | 17.2 | 15 | 87% | 47 |
| (c) always-on HL short / Binance perp long | IS | 5.36% | 7.25 | -0.43% | 100% | 5.36% | 1.2 | 0 | n/a | n/a |
| (c) always-on HL short / Binance perp long | OOS | 3.42% | 5.31 | -0.14% | 100% | 3.43% | 7.9 | 8 | 100% | 724 |
| ref: always-on HL short / Binance spot long | IS | 5.86% | 8.84 | -0.29% | 100% | 5.86% | 0.8 | 0 | n/a | n/a |
| ref: always-on HL short / Binance spot long | OOS | 5.45% | 11.59 | -0.12% | 100% | 5.47% | 5.3 | 8 | 100% | 724 |

"Net ann. on capital" counts the full allocated capital, including idle time. Sharpe uses daily PnL × √365. For (c), the trades are counted at the final exit, so the OOS cost line includes the one-time exit.

### Cost breakdown (annualised, % of capital)
| strategy | period | gross funding | basis/price drift | fees | slippage | leg risk | net | costs as % of gross funding |
|---|---|---|---|---|---|---|---|---|
| (a) cross-venue spread, θ=15% | IS | 1.58% | 0.02% | -0.56% | -0.10% | -0.20% | 0.74% | 55% |
| (a) cross-venue spread, θ=15% | OOS | 0.16% | 0.06% | -0.26% | -0.06% | -0.10% | -0.20% | 267% |
| (b) cash-and-carry, θ=10% | IS | 5.73% | 0.14% | -0.81% | -0.11% | -0.20% | 4.77% | 19% |
| (b) cash-and-carry, θ=10% | OOS | 4.61% | 0.22% | -1.25% | -0.16% | -0.29% | 3.13% | 37% |
| (c) always-on HL short / Binance perp long | IS | 5.55% | -0.12% | -0.05% | -0.01% | -0.02% | 5.36% | 2% |
| (c) always-on HL short / Binance perp long | OOS | 4.10% | -0.11% | -0.38% | -0.06% | -0.13% | 3.42% | 14% |
| ref: always-on HL short / Binance spot long | IS | 6.10% | -0.16% | -0.06% | -0.01% | -0.01% | 5.86% | 1% |
| ref: always-on HL short / Binance spot long | OOS | 6.06% | -0.09% | -0.38% | -0.05% | -0.09% | 5.45% | 9% |

For the timed strategies, fees, slippage and leg risk eat **55%** of gross funding in (a) IS and **267%** in (a) OOS. For (b) they eat 19% IS and 37% OOS.
Basis and price drift between the legs was small and slightly positive on average (+0.0–0.2%/yr).

### θ grid (IS only; θ picked by IS Sharpe, then frozen)
(a):
| θ | IS net | IS Sharpe | IS max DD | time in pos | trades |
|---|---|---|---|---|---|
| 5% | 0.85% | 1.87 | -0.88% | 47% | 427 |
| 10% | 0.83% | 2.15 | -0.54% | 19% | 206 |
| 15% | 0.74% | 2.26 | -0.37% | 11% | 118 |
| 20% | 0.61% | 2.11 | -0.34% | 7% | 74 |
| 30% | 0.22% | 1.11 | -0.32% | 3% | 37 |

(b):
| θ | IS net | IS Sharpe | IS max DD | time in pos | trades |
|---|---|---|---|---|---|
| 5% | 4.83% | 7.53 | -0.39% | 71% | 85 |
| 10% | 4.77% | 7.76 | -0.19% | 54% | 56 |
| 15% | 3.83% | 6.83 | -0.10% | 32% | 36 |
| 20% | 2.80% | 5.36 | -0.09% | 17% | 30 |
| 30% | 2.12% | 4.51 | -0.14% | 10% | 20 |


### Per coin / per leg pair
(a) cross-venue spread, θ=15%:
| coin | legs (short/long) | IS net | IS Sharpe | IS gross funding | IS costs | IS time in pos | OOS net | OOS Sharpe | OOS gross funding | OOS costs | OOS time in pos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | HL/BIN | 0.94% | 1.82 | 1.61% | -0.80% | 12% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| BTC | HL/BYB | 0.80% | 1.50 | 1.45% | -0.70% | 12% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| BTC | BIN/BYB | 0.00% | n/a | 0.00% | 0.00% | 0% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| ETH | HL/BIN | 1.63% | 2.71 | 1.92% | -0.29% | 10% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| ETH | HL/BYB | 0.64% | 1.20 | 1.24% | -0.62% | 9% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| ETH | BIN/BYB | 0.01% | 0.03 | 0.20% | -0.16% | 2% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| SOL | HL/BIN | 1.95% | 2.96 | 2.38% | -0.47% | 12% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| SOL | HL/BYB | 0.80% | 1.22 | 1.81% | -1.14% | 13% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| SOL | BIN/BYB | -0.09% | -0.41 | 0.21% | -0.34% | 2% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| XRP | HL/BIN | 2.49% | 2.74 | 3.47% | -1.28% | 22% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| XRP | HL/BYB | 1.14% | 1.23 | 2.53% | -1.48% | 19% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| XRP | BIN/BYB | -0.29% | -0.66 | 0.39% | -0.51% | 4% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| DOGE | HL/BIN | 2.87% | 3.22 | 3.60% | -1.01% | 15% | -1.74% | -2.98 | 0.24% | -2.30% | 9% |
| DOGE | HL/BYB | 1.27% | 1.38 | 2.36% | -0.87% | 12% | -0.62% | -1.04 | 0.99% | -2.38% | 15% |
| DOGE | BIN/BYB | -0.24% | -0.50 | 0.36% | -0.35% | 4% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| SUI | HL/BIN | 0.17% | 0.20 | 1.96% | -2.15% | 15% | -0.53% | -1.18 | 0.53% | -1.34% | 8% |
| SUI | HL/BYB | -0.52% | -0.72 | 0.98% | -1.65% | 11% | -0.99% | -1.64 | 0.38% | -1.42% | 7% |
| SUI | BIN/BYB | 0.22% | 0.44 | 0.85% | -0.61% | 7% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| LINK | HL/BIN | 1.64% | 1.47 | 2.78% | -1.10% | 17% | -0.67% | -1.02 | 0.64% | -1.26% | 8% |
| LINK | HL/BYB | 0.94% | 0.88 | 1.88% | -0.76% | 11% | -0.34% | -0.60 | 0.97% | -1.31% | 8% |
| LINK | BIN/BYB | -0.55% | -0.99 | 0.10% | -0.37% | 2% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| AVAX | HL/BIN | 1.67% | 1.76 | 3.26% | -1.91% | 21% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| AVAX | HL/BYB | 1.34% | 0.98 | 2.72% | -1.61% | 19% | 0.00% | n/a | 0.00% | 0.00% | 0% |
| AVAX | BIN/BYB | -1.11% | -1.68 | -0.12% | -0.61% | 2% | 0.00% | n/a | 0.00% | 0.00% | 0% |

(b) cash-and-carry, θ=10%:
| coin | legs (short/long) | IS net | IS Sharpe | IS gross funding | IS costs | IS time in pos | OOS net | OOS Sharpe | OOS gross funding | OOS costs | OOS time in pos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | HL/BINSPOT | 5.49% | 8.24 | 5.96% | -0.57% | 61% | 3.46% | 7.92 | 4.56% | -1.31% | 82% |
| ETH | HL/BINSPOT | 4.30% | 5.51 | 5.35% | -1.29% | 54% | 2.40% | 4.67 | 3.71% | -1.40% | 62% |
| SOL | HL/BINSPOT | 3.50% | 4.51 | 4.39% | -1.15% | 39% | 0.78% | 1.24 | 2.28% | -1.97% | 47% |
| XRP | HL/BINSPOT | 5.27% | 6.06 | 5.94% | -0.72% | 54% | 2.94% | 3.33 | 5.02% | -1.98% | 69% |
| DOGE | HL/BINSPOT | 4.89% | 5.18 | 6.17% | -1.38% | 49% | 5.36% | 7.91 | 6.54% | -1.05% | 78% |
| SUI | HL/BINSPOT | 3.27% | 3.65 | 4.43% | -1.49% | 39% | 4.46% | 4.21 | 6.06% | -1.81% | 74% |
| LINK | HL/BINSPOT | 7.51% | 6.05 | 8.43% | -0.91% | 88% | 5.31% | 5.88 | 6.68% | -1.70% | 95% |
| AVAX | HL/BINSPOT | 3.89% | 3.61 | 5.20% | -1.37% | 49% | 0.30% | 0.37 | 2.00% | -2.35% | 35% |

(c) always-on HL short / Binance perp long:
| coin | legs (short/long) | IS net | IS Sharpe | IS gross funding | IS costs | IS time in pos | OOS net | OOS Sharpe | OOS gross funding | OOS costs | OOS time in pos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | HL/BIN | 5.28% | 6.19 | 5.36% | -0.07% | 100% | 2.32% | 4.07 | 2.65% | -0.46% | 100% |
| ETH | HL/BIN | 4.87% | 5.14 | 5.03% | -0.07% | 100% | 3.41% | 5.58 | 3.99% | -0.50% | 100% |
| SOL | HL/BIN | 4.95% | 4.51 | 5.06% | -0.08% | 100% | 2.88% | 3.79 | 3.42% | -0.54% | 100% |
| XRP | HL/BIN | 4.57% | 3.86 | 4.84% | -0.08% | 100% | 4.76% | 5.07 | 5.46% | -0.55% | 100% |
| DOGE | HL/BIN | 5.68% | 4.62 | 5.98% | -0.08% | 100% | 4.34% | 4.52 | 5.12% | -0.58% | 100% |
| SUI | HL/BIN | 3.88% | 2.77 | 4.12% | -0.10% | 100% | 5.30% | 3.67 | 6.14% | -0.67% | 100% |
| LINK | HL/BIN | 7.31% | 4.92 | 7.55% | -0.09% | 100% | 3.97% | 3.36 | 4.87% | -0.63% | 100% |
| AVAX | HL/BIN | 6.28% | 4.44 | 6.50% | -0.10% | 100% | 0.38% | 0.36 | 1.17% | -0.66% | 100% |

ref: always-on HL short / Binance spot long:
| coin | legs (short/long) | IS net | IS Sharpe | IS gross funding | IS costs | IS time in pos | OOS net | OOS Sharpe | OOS gross funding | OOS costs | OOS time in pos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | HL/BINSPOT | 6.85% | 10.76 | 6.90% | -0.06% | 100% | 5.24% | 12.78 | 5.61% | -0.44% | 100% |
| ETH | HL/BINSPOT | 6.34% | 8.84 | 6.49% | -0.07% | 100% | 5.25% | 12.82 | 5.78% | -0.47% | 100% |
| SOL | HL/BINSPOT | 3.62% | 3.97 | 3.82% | -0.07% | 100% | 4.26% | 7.89 | 4.77% | -0.49% | 100% |
| XRP | HL/BINSPOT | 4.94% | 5.19 | 5.18% | -0.07% | 100% | 5.61% | 8.21 | 6.28% | -0.49% | 100% |
| DOGE | HL/BINSPOT | 6.78% | 7.10 | 7.10% | -0.08% | 100% | 7.01% | 11.20 | 7.62% | -0.52% | 100% |
| SUI | HL/BINSPOT | 4.84% | 4.59 | 5.12% | -0.09% | 100% | 6.74% | 6.77 | 7.43% | -0.60% | 100% |
| LINK | HL/BINSPOT | 8.80% | 6.92 | 9.05% | -0.08% | 100% | 6.34% | 7.67 | 7.13% | -0.57% | 100% |
| AVAX | HL/BINSPOT | 4.74% | 3.78 | 5.17% | -0.09% | 100% | 3.14% | 4.15 | 3.84% | -0.59% | 100% |

Binance–Bybit sleeves in (a) lost money IS in 5 of 8 coins (16 trades over the full sample, 31% hit rate). There is no usable spread between the two CEXs. The only positive spread is HL vs the CEXs.

## Sensitivity (θ frozen)
| strategy | variant | IS net | IS Sharpe | OOS net | OOS Sharpe |
|---|---|---|---|---|---|
| (a) cross-venue spread, θ=15% | cost x0 | 1.60% | 5.14 | 0.21% | 3.79 |
| (a) cross-venue spread, θ=15% | cost x0.5 | 1.17% | 3.73 | 0.00% | 0.08 |
| (a) cross-venue spread, θ=15% | cost x1 (base) | 0.74% | 2.26 | -0.20% | -2.17 |
| (a) cross-venue spread, θ=15% | cost x1.5 | 0.30% | 0.87 | -0.41% | -3.05 |
| (a) cross-venue spread, θ=15% | cost x2 | -0.13% | -0.34 | -0.62% | -3.46 |
| (a) cross-venue spread, θ=15% | maker fees, no slip | 1.20% | 3.82 | 0.02% | 0.30 |
| (a) cross-venue spread, θ=15% | $100k slippage | 0.36% | 1.03 | -0.35% | -2.75 |
| (a) cross-venue spread, θ=15% | 1x leverage | 0.37% | 2.26 | -0.10% | -2.17 |
| (a) cross-venue spread, θ=15% | 3x leverage | 1.11% | 2.26 | -0.31% | -2.17 |
| (b) cash-and-carry, θ=10% | cost x0 | 5.87% | 10.08 | 4.82% | 13.92 |
| (b) cash-and-carry, θ=10% | cost x0.5 | 5.32% | 8.97 | 3.98% | 11.19 |
| (b) cash-and-carry, θ=10% | cost x1 (base) | 4.77% | 7.76 | 3.13% | 7.75 |
| (b) cash-and-carry, θ=10% | cost x1.5 | 4.21% | 6.53 | 2.28% | 4.75 |
| (b) cash-and-carry, θ=10% | cost x2 | 3.66% | 5.35 | 1.43% | 2.50 |
| (b) cash-and-carry, θ=10% | maker fees, no slip | 5.04% | 8.36 | 3.54% | 9.44 |
| (b) cash-and-carry, θ=10% | $100k slippage | 4.38% | 6.89 | 2.53% | 5.60 |
| (b) cash-and-carry, θ=10% | 1x leverage | 3.57% | 7.76 | 2.35% | 7.75 |
| (b) cash-and-carry, θ=10% | 3x leverage | 5.36% | 7.76 | 3.52% | 7.75 |
| (c) always-on HL short / Binance perp long | cost x0 | 5.44% | 7.41 | 3.99% | 6.83 |
| (c) always-on HL short / Binance perp long | cost x0.5 | 5.40% | 7.35 | 3.71% | 6.20 |
| (c) always-on HL short / Binance perp long | cost x1 (base) | 5.36% | 7.25 | 3.42% | 5.31 |
| (c) always-on HL short / Binance perp long | cost x1.5 | 5.31% | 7.11 | 3.13% | 4.37 |
| (c) always-on HL short / Binance perp long | cost x2 | 5.27% | 6.94 | 2.85% | 3.52 |
| (c) always-on HL short / Binance perp long | maker fees, no slip | 5.40% | 7.36 | 3.72% | 6.24 |
| (c) always-on HL short / Binance perp long | $100k slippage | 5.33% | 7.15 | 3.21% | 4.63 |
| (c) always-on HL short / Binance perp long | 1x leverage | 2.68% | 7.25 | 1.71% | 5.31 |
| (c) always-on HL short / Binance perp long | 3x leverage | 8.03% | 7.25 | 5.13% | 5.31 |

Leverage only rescales capital: 3x per leg raises the always-on perp/perp result to +8.03% IS / +5.13% OOS, but it makes the liquidation problem below worse.

## Funding regime: does the HL premium persist?
Mean across the 8 coins, annualised:
| quarter | HL | Binance | Bybit | HL−Binance | HL−Bybit |
|---|---|---|---|---|---|
| 2024Q4 | 34.05% | 14.78% | 20.61% | 19.28% | 13.44% |
| 2025Q1 | 6.59% | 2.16% | 4.64% | 4.42% | 1.94% |
| 2025Q2 | 6.23% | 2.88% | 3.58% | 3.35% | 2.64% |
| 2025Q3 | 15.45% | 6.89% | 7.86% | 8.56% | 7.59% |
| 2025Q4 | 5.18% | 1.48% | 0.29% | 3.69% | 4.89% |
| 2026Q1 | 1.38% | -0.68% | 1.00% | 2.06% | 0.37% |
| 2026Q2 | 3.45% | 1.17% | 1.92% | 2.27% | 1.52% |
| 2026Q3 | 9.39% | 5.14% | 4.20% | 4.25% | 5.19% |
| 2026Q4 | 7.44% | 3.45% | 3.12% | 3.98% | 4.32% |

- The HL−CEX spread has been **positive in every quarter** on the 8-coin average. It shrank from about 19%/yr in 2024Q4 (a bull, high-funding regime) to 2–9%/yr since 2025Q1 (8.6% in 2025Q3).
  2026Q1–Q2 was the weakest stretch: about 2.1–2.3% vs Binance and 0.4–1.5% vs Bybit, with SOL and XRP negative in 2026Q1. It recovered to about 4–5% in OOS 2026Q3–Q4.
- Funding levels on all venues track the market regime, and the spread tracks the levels. A high-funding bull market widens it; chop compresses it.
- Chart `funding_spread.png` shows the 30-day rolling spreads per coin. They go negative for weeks at a time (e.g. Apr 2025, Feb–May 2026), which is when the
  always-on version bleeds.

### Worst 7-day funding-flip / basis episodes (net on sleeve capital, while in position)
(a): 
| coin | legs | 7d window ending (UTC) | 7d net on sleeve capital |
|---|---|---|---|
| AVAX | BIN/BYB | 2025-10-17 08:00 | -1.05% |
| DOGE | HL/BYB | 2025-10-16 16:00 | -0.98% |
| AVAX | HL/BYB | 2025-10-18 00:00 | -0.93% |

(b):
| coin | legs | 7d window ending (UTC) | 7d net on sleeve capital |
|---|---|---|---|
| AVAX | HL/BINSPOT | 2025-10-18 00:00 | -0.46% |
| XRP | HL/BINSPOT | 2025-10-18 00:00 | -0.28% |
| LINK | HL/BINSPOT | 2025-04-18 16:00 | -0.26% |

(c):
| coin | legs | 7d window ending (UTC) | 7d net on sleeve capital |
|---|---|---|---|
| XRP | HL/BIN | 2025-04-07 08:00 | -0.66% |
| SUI | HL/BIN | 2024-11-07 16:00 | -0.51% |
| DOGE | HL/BIN | 2025-10-17 08:00 | -0.50% |

These are on 8h closes. They are small because the 8h grid smooths over the crash (next section).

## Stress: 10–11 Oct 2025 crash and liquidation (post-hoc, logged as a deviation, not used for pass/fail)
Worst 1-minute **mark-price** lows (the price used for liquidation) on 10 Oct 2025 12:00 → 11 Oct 12:00 UTC (`oct10_2025_wick_check.txt`):
BTC −16.2%, ETH −21.1%, SOL −34.9%, XRP −57.7%, DOGE −64.6%, SUI −83.3%, LINK −63.8%, AVAX −69.9% (Binance mark). Bybit mark lows were −12% to −83%.
- At 2x per leg, a long perp leg is liquidated at roughly −49%. So the always-on HL-short / Binance-long hedge would have lost the long leg in **XRP, DOGE, SUI, LINK, AVAX**.
  Rough estimate per sleeve: lose the long leg's margin (−50% of sleeve capital) plus the short leg's gain to the price 24h later (+12% to +23%). That is −27% to −38% per sleeve,
  and **about −19% of portfolio capital**. Assumptions: no collateral top-up during the minutes-long wick, liquidation fees and HL ADL ignored.
  The backtest's 8h-close PnL shows none of this.
- At 3x, SOL is liquidated too. At 1x no leg is liquidated (SUI's −83% mark low is above the ~−99% threshold), but returns halve (see sensitivity).
- Strategy (a) had only AVAX HL-short / Binance-long and AVAX HL-short / Bybit-long open that day, so it would have had the same AVAX problem.
- Cash-and-carry (b) can't be liquidated on the spot leg. The HL short leg is at risk on rallies instead. Measured on 8h closes, the HL price rose up to +550% (XRP),
  +189% (DOGE) and +166% (LINK) inside single long-held (b) trades from Nov 2024. Without regular collateral transfers from Binance to HL, the short leg would have been liquidated.
  The backtest assumes costless 8h resizing at constant notional and costless collateral rebalancing. Neither is free in practice.
- HL ran cross-margin **auto-deleveraging (ADL)** for the first time on 10 Oct 2025 (widely reported; about $2.1bn of positions closed in ~12 minutes per arXiv 2512.01112).
  A profitable hedge leg can be force-closed, which leaves the other leg naked.

## Caveats
- Venue and counterparty risk: three separate venues, and HL is an on-chain venue with a USDC bridge. Exchange failure, withdrawal halts or bridge risk are not priced. A 3–5%/yr carry
  doesn't pay for much tail risk.
- Costs come from a single 5-minute snapshot window on one weekday evening. Real spreads widen in volatility, exactly when you might need to exit.
- Constant-notional accounting with costless 8h resizing; collateral transfer costs and delays between venues are not modelled; fixed hedge ratio; no funding-rate caps or tiered margin modelled.
- Spot proxy is Binance spot. Only one spot venue was tested.
- Idle capital earns 0% in the headline numbers. Adding T-bill yield on idle cash would raise (a)/(b), but it is not an edge.
- 24-month sample; the OOS is a single quarter (about 270 8h periods), so the OOS Sharpe values are noisy.
- Base-tier fees. A VIP or maker-only execution desk would see better numbers ("maker fees, no slip" lifts (b) OOS to +3.54%, still below the hurdle).

## Charts
- `cum_net_pnl.png`: cumulative net return on capital, all four strategies, IS/OOS split marked.
- `funding_spread.png`: 30-day rolling HL−Binance and HL−Bybit funding spread per coin.

## What I'd test next (needs a new pre-registration)
1. Always-on HL-short carry with explicit collateral rebalancing rules and costs, at 1–1.5x. Model liquidation on 1-minute mark prices, including 10 Oct 2025 and ADL.
2. Exit/enter on a slow spread (30–60 day), not a 7-day threshold, with maker-only execution on HL (post-only, 0.015%).
3. Run the collector hourly for a few weeks to check whether the snapshot costs hold over time, and how predicted funding compares with realised.
4. Add HYPE and other HL-native names where the HL premium may be larger (shorter history), and OKX as a 4th venue.
5. Put the carry next to the yield actually available on idle USDC/USDT (on-venue or T-bills), since the decision is carry vs cash.
