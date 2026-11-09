# Pre-registration: perp funding carry backtest v2 (1-minute, liquidation-aware)

Written: 2026-10-27 10:16 UTC, **before** any v2 backtest code was run or any v2 result was seen.
Paper research only: no accounts, keys, orders, wallets.

Data-availability probes done before this document (not results): HL minute archive present for 8 coins + HYPE under `data/hl_archive/minute/`; coverage ~95% over the sample with 100% coverage on 2025-10-10..11; Binance `data.binance.vision` monthly markPriceKlines and spot 1m zips return HTTP 200 (Oct 2026 monthly not yet published — daily zips used for that month); HL `/info` meta returns live margin tables; Binance `/fapi/v1/leverageBracket` returns 401 without a key (tier-1 MMR taken from documented sources below).

v1 context (frozen, not re-tuned): `preregistration.md`, `results/carry_backtest_v1.md`. v1 always-on HL-short / Binance-perp-long at 2x printed +3.42% OOS on 8h bars but a post-hoc 1m mark check estimated ~−19% of capital on 10 Oct 2025.

## 1. Universe
Same 8 coins as v1 on HL perps and Binance USDT-M + spot:
**BTC, ETH, SOL, XRP, DOGE, SUI, LINK, AVAX.**

**Add-on (reported separately, not in the 8-coin portfolio pass/fail):** **HYPE**, from the later of (HL archive start 2024-12-05, Binance USDT-M onboard 2025-05-30 10:30 UTC) to sample end. Binance spot HYPE used when available; if spot archive missing for a month, that month's HYPE sleeve is flat and reported.

## 2. Sample and split
- Full sample: **2024-11-01 00:00 UTC → 2026-10-26 00:00 UTC** (aligned with v1; HL minute archive ends 2026-10-26 04:04 UTC — last incomplete day truncated at last common minute across legs).
- In-sample (IS): 2024-11-01 → 2026-07-26 00:00 UTC.
- Out-of-sample (OOS): **2026-07-26 → 2026-10-26**. Held out. Touched once after IS summaries are frozen.
- Resolution: **1-minute**. Decision / accounting / liquidation check every minute.

## 3. Strategies (only these)
Equal notional **N = $10,000 per leg** at entry (base). Sensitivity: N = $100,000 (slippage + MMR tier note).

**(c) Always-on HL perp short / Binance USDT-M perp long.** Enter at first minute both legs have valid marks; stay on except after liquidation / ADL / forced flat windows (see §6–7).

**(ref) Always-on HL perp short / Binance spot long.** Spot long has **no liquidation**. Margin risk is on the HL short only. Capital = spot notional N + HL margin N/L.

Leverage per **perp** leg L ∈ **{1.0, 1.5, 2.0}**. Isolated margin assumed (matches v1 "margin posted separately"; no cross-venue or cross-asset netting). Initial margin per perp leg = N/L. Portfolio = equal capital across the 8 sleeves.

Timed / threshold strategies (v1 a,b) are **out of scope** for v2.

## 4. Prices, funding, gaps
- **HL mark:** `mark_px` from `data/hl_archive/minute/<COIN>.parquet`, floored to minute. Mid used only for exit fills when mark missing.
- **Binance perp mark:** 1m markPriceKlines from `data.binance.vision` (`futures/um/.../markPriceKlines/<SYM>/1m/`). Within each minute, liquidation uses the **adverse extreme**: long → `low`; short → `high`. PnL/MTM uses close.
- **Binance spot:** 1m spot klines (`spot/.../klines/<SYM>/1m/`). MTM on close; no liquidation.
- **Funding:**
  - HL: hourly settlement. Rate taken from the archive `funding` field at the settlement minute (HH:00), else from `data/hl_funding_*.parquet` if the minute row is gapped. Short receives +rate × N.
  - Binance: settlement events from existing `data/bin_funding_*.parquet` (handles 8h/4h/1h). Long pays rate × N.
- **Gaps:** If either leg's mark is missing for a minute, forward-fill mark at most **2 minutes**; beyond that the sleeve is **flat** (both legs closed at last valid mid/mark with costs) until both series resume, then re-enter on the next minute (no 24h wait for gap flats). Gap map reported before results. Oct 10–11 2025 HL coverage is complete (verified in the probe); gaps of 6–24h cluster mainly in Sep–Oct 2026 and some evenings ending at 00:00 UTC.

## 5. Costs (reuse v1, fixed)
Fees (taker both sides, base tier, no discounts) — same as v1 Appendix A:
| Venue | Taker |
|---|---|
| HL perp | 0.045% |
| Binance USDT-M | 0.050% |
| Binance spot | 0.100% |

Slippage and leg-risk from `data/cost_params.csv` (v1 live books 2026-10-26): slip_10k_bps per fill for base N=$10k; slip_100k_bps for N=$100k; leg_risk_bps once per entry and once per exit (sequential fill delay). Charged on every open, close, liquidation close of the surviving leg, and re-entry.

Idle capital earns **0%** in the base case. Sensitivity: idle USDC earns **4.0% annualised** (stated cash proxy; not a measured on-venue rate).

## 6. Liquidation model (checked every minute)
### 6.1 Maintenance margin rates (documented now)

**Hyperliquid** (live `meta` 2026-10-27; formula: MMR = 0.5 / maxLeverage at the tier for that notional; docs: hyperliquid.gitbook.io/hyperliquid-docs/trading/margin-tiers and /trading/liquidations). At N ≤ $100k all coins are in tier 1:

| coin | maxLev (tier1) | MMR |
|---|---|---|
| BTC | 40 | 1.25% |
| ETH | 25 | 2.00% |
| SOL | 20 | 2.50% |
| XRP | 20 | 2.50% |
| DOGE, SUI, LINK, AVAX, HYPE | 10 | 5.00% |

Liquidation when account equity (isolated) < maintenance margin. Book liquidation first; if equity < (2/3)×MM, backstop → isolated margin transferred to liquidator (user keeps 0 on that leg). **Model rule (conservative, fixed now):** on any HL liquidation trigger, the short leg's remaining isolated margin is **wiped to 0** (treat as backstop). Partial-liquidation / 30s cooldown ignored at N=$10k (partial threshold is $100k notional).

**Binance USDT-M** (tier-1 MMR as of 2026-10-27 from bykaranteli.com/leverage daily recorder + Binance BTC announcement confirming BTC 0.40%; Binance `/fapi/v1/leverageBracket` was 401 without a key — noted). At N=$10k all in tier 1. Maintenance amount ≈ 0 at tier 1 for these sizes.

| coin | tier1 MMR | tier1 notional cap (approx) |
|---|---|---|
| BTC | 0.40% | 300k |
| ETH | 0.40% | 300k |
| SOL | 0.50% | 50k |
| XRP | 0.50% | 40k |
| DOGE | 0.65% | 80k |
| SUI | 1.00% | 20k |
| LINK | 0.50% | 10k |
| AVAX | 0.50% | 25k |
| HYPE | 1.00% | 20k |

For N=$100k sensitivity: if N exceeds tier1 cap, use the next published tier MMR from the same source where available (SOL 0.65% in 50–400k); if the next tier is unknown, use **max(tier1 MMR, 1.0%)** and flag the coin. Liquidation clearance fee on Binance: **0.015% of notional** (standard; charged on liquidated notional) in addition to wiping remaining equity below MM — model: **remaining isolated margin after adverse mark move is lost**, plus 0.015%×N fee from sleeve capital.

### 6.2 Trigger
Isolated equity for a perp leg:
- Long: `equity = margin + N * (mark/entry − 1)` (mark = minute low for Binance check; HL mark_px)
- Short: `equity = margin + N * (1 − mark/entry)` (mark = minute high for Binance; HL mark_px)
- `MM = MMR * N_mark` with `N_mark = N * mark/entry` (mark-to-market notional). Equivalent check: liquidate if `equity < MMR * N_mark`.

Margin is topped up only by the rebalancing rule (§7), not continuously.

### 6.3 On liquidation
1. Realise loss on liquidated leg = that leg's remaining margin (→ 0) + any venue fee above.
2. **Close the other leg at the next minute's mark/mid** with taker fee + slippage + leg-risk.
3. Sleeve goes **flat for 24 hours**, then re-enters at the first valid minute after that (both legs, with entry costs), unless sample end.
4. Count +1 liquidation event.

## 7. Collateral rebalancing (fixed in advance)
Each minute while in position, compute each perp leg's **margin ratio** `MR = equity / N_mark`.

- **Trigger:** if either leg has `MR < 1.5 × MMR` (i.e. within 50% of the maintenance cushion above MM), **and** the other venue/leg has surplus equity above `initial_margin + 0.5×(initial_margin − MM_value)` transferable, initiate a rebalance.
- For (ref) spot/HL: only HL is checked; surplus comes from unused spot-side cash buffer. Spot side holds coin (no spare USDT beyond what's needed); **model:** a cash buffer equal to HL initial margin is reserved on the Binance side at entry as transfer fuel (included in sleeve capital: capital_ref = N + N/L + N/L = N + 2N/L). Wait — that would change capital vs v1. **Simpler fixed rule:** sleeve capital for (ref) = N + N/L (spot + HL margin), same as v1. Transfers to HL pull from an implicit external cash pocket that is **part of allocated capital only up to one extra N/L reserved at portfolio level for rebalancing fuel across sleeves** — too messy.

**Cleaner rule fixed now:**
- Per sleeve, capital = two initial margins for (c) (= 2N/L), or N + N/L for (ref).
- Rebalance moves collateral **between the two legs of the same sleeve** only.
- For (c): if leg A is below trigger and leg B has equity > initial_margin_B + transfer_amount needed, transfer.
- For (ref): spot leg has no MMR; "surplus" on spot side is defined as unrealised spot PnL cashable only by selling spot — **we do not sell spot to top up HL**. Rebalancing for (ref) only moves **pre-allocated unused margin** if we intentionally started HL with margin > N/L. **Fixed:** (ref) posts HL margin = N/L still, but an additional **standby cash** of `0.25 × N/L` sits on HL's side of the sleeve capital from t0 (capital_ref = N + 1.25×N/L). That standby can be added to the isolated HL margin when MR triggers, with the same delay/cost as a cross-venue transfer (standby is modelled as held on Binance earning 0 until transferred). This keeps (ref) liquidation-aware on HL without inventing spot sales.

**Transfer mechanics (both strategies):**
- Delay: **45 minutes** from trigger to credit (midpoint of 30–60; sources: Binance USDC Arbitrum withdraw ~1–5 min + HL bridge deposit <1–2 min typical, but CEX internal + manual/ops buffer → 45 min conservative; HL withdraw to Arbitrum ~3–5 min + Binance deposit).
- Cost per transfer: **$5 flat** (≈ $1 Binance USDC-Arb withdraw + $1 HL withdraw fee + ~$1–3 gas/ops round-up; sources: HL docs withdraw $1 USDC; Binance USDC-Arb withdraw commonly ~1 USDC; gas cents). Charged to sleeve PnL when transfer **credits**.
- Max one in-flight transfer per sleeve. If liquidation hits before credit, transfer is cancelled (cost not charged) and liquidation proceeds.
- Transfer size: amount needed to restore the weak leg to **MR = 1/L** (full initial), capped by surplus on the donor leg minus donor's own initial floor.

## 8. ADL stress scenario (10 Oct 2025)
HL ran cross-margin ADL on 10 Oct 2025 (~$2.1bn notionals, ~12 minutes; cited in v1 from arXiv 2512.01112). Per-coin ADL timestamps/prices are **not** in our public archive.

**Fixed assumption:** for every sleeve still long-the-hedge (HL short open) on 2025-10-10, force-close the **HL short via ADL** at **2025-10-10 21:15 UTC** (inside the widely reported crash window) at that minute's HL `mark_px`. Unrealised HL PnL at that mark is realised; **no** remaining HL margin is clawed beyond marking to market (ADL closes the profitable short — we keep the marked equity, lose future funding). Then close the Binance leg at the **next** minute with normal exit costs. Sleeve flat 24h, then re-enter per §6.3.

This is a **stress scenario reported separately** from the base path. Base path = liquidations + rebalancing only, no ADL. Pass/fail uses the **worse** of {base, base+ADL} on the 10 Oct criteria.

## 9. Returns and metrics
- Sleeve capital as in §3/§7. Portfolio = equal capital weight on 8 coins (HYPE add-on separate).
- Annualised net return = (total net PnL / capital) / years × 1 (simple). Also report mean daily PnL/capital × 365.
- Sharpe = mean/std of **daily** net PnL/capital × √365 (rf not subtracted).
- Max drawdown of cumulative return on capital over the stated window.
- Counts: liquidations, rebalances credited, ADL events, gap-flats, re-entries.
- 10 Oct 2025 (00:00–24:00 UTC and crash window 12:00–12:00 next day): per-coin and portfolio PnL, whether liquidated, margin-ratio path.

## 10. Pass / fail (decided now)
On the **8-coin portfolio**, strategy (c), each leverage judged separately; (ref) reported but not pass/fail.

**PASS** only if all hold:
1. OOS net annualised on total capital **> 4.5%**, AND
2. Max drawdown over **FULL** sample **< 10%**, AND
3. Survives 10 Oct 2025 without wiping **> 1 year of carry** — i.e. that day's portfolio net PnL > −(FULL-sample net annualised return × capital), using the worse of base vs ADL stress for that day.

Else **FAIL**. Marginal commentary allowed but does not pass.

## 11. Outputs
- Code: `pipeline/v2/`
- Results: `results/v2/` including `carry_backtest_v2.md`, summary CSVs, 2–3 PNGs (equity by leverage with 10 Oct marked; margin-ratio paths on 10 Oct).
- This file's deviations log will be appended after the run for any unavoidable changes.

## 12. Explicit non-goals
No live trading, no API keys used for orders, no Bybit required (Binance + HL only). No retuning of v1 thresholds. No inventing missing prices — gap rules above.

## Deviations log
Appended 2026-10-27 after the run :

1. **Binance funding timestamps floored to the minute.** Many `bin_funding_*.parquet` rows carry sub-second offsets (e.g. `08:00:00.003Z`). Reindexing onto a 1-minute grid without flooring dropped ~45% of Binance settlements (BTC sum 0.063 vs 0.101). Fixed before final results; this was a bug, not a model choice.
2. **Rebalance transfer size uses MTM equity vs target MR = 1/L**, capped by donor wallet. An earlier draft used `im − wallet_margin`, which ignores unrealised PnL and never restores MR. Matches prereg §7 intent; logged because the first coded version was wrong.
3. **Gap-flat re-entry wait.** An intermediate engine build applied the 24h post-liquidation flat window to archive gap-flats. Corrected to prereg §4 (re-enter as soon as both series resume). Final results use the corrected rule.
4. **Hold-through-gaps sensitivity** (unlimited mark ffill; no gap-flat exits) was added for interpretation. **Pass/fail uses only the preregistered gap-flat path.** Hold approximates “venues were live; archive rows are missing.”
5. **HYPE add-on skipped:** `data/bin_funding_HYPE.parquet` missing at run time.
6. **No change to MMR tables, transfer delay ($5 / 45 min), ADL time (2025-10-10 21:15 UTC), fees, slippage, universe, or pass/fail hurdles.**
7. **Structural note (not a deviation):** at 1x, donor surplus above the IM floor is ≈ 0 for an isolated long whose wallet equals IM, so the preregistered rebalance rule cannot move collateral to the HL short during one-way rallies. The six 1x hold HL liquidations (Nov–Dec 2024 alt pumps, mark/entry ≈ 1.9) are expected under that rule.
