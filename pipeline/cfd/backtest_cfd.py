"""CFD vs HL HIP-3 backtests: (A) gap, (B) carry, (C) passive. Writes results/cfd/."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common_cfd import (
    PAIRS, RESULTS, DATA_HL, LIVE, NOTIONAL, HL_FEES, HL_MAX_LEV_FALLBACK,
    mt5_rt_cost_frac, capital_both_legs, hl_fee_docs_correct, MT5_END,
)
from load_data import (
    load_hl_funding, load_hl_candles, load_mt5_m1, load_mt5_h1, load_swaps,
    align_m1, align_h1, funding_start,
)

RESULTS.mkdir(parents=True, exist_ok=True)
MT5_END_TS = pd.Timestamp(MT5_END)


def freeze_split(coverage: pd.DataFrame) -> dict:
    """Write sample_split.json BEFORE computing strategy PnL."""
    # global overlap: min start across pairs with data to MT5 end
    starts = pd.to_datetime(coverage["overlap_start"], utc=True)
    ends = pd.to_datetime(coverage["overlap_end"], utc=True)
    global_start = starts.min()
    global_end = ends.max()
    days = (global_end - global_start).days
    if days >= 60:
        oos_start = global_start + pd.Timedelta(days=int(days * 0.8))
        mode = "time_80_20"
    else:
        oos_start = None
        mode = "full_only_short_sample"
    split = {
        "written_before_pnl": True,
        "global_start": str(global_start),
        "global_end": str(global_end),
        "calendar_days": int(days),
        "mode": mode,
        "oos_start": str(oos_start) if oos_start is not None else None,
        "note": "Per-pair samples start at each pair's overlap_start; portfolio metrics use available pairs each day.",
    }
    (RESULTS / "sample_split.json").write_text(json.dumps(split, indent=2))
    return split


def coverage_table() -> pd.DataFrame:
    rows = []
    for p in PAIRS:
        try:
            fs = funding_start(p["hl"])
        except Exception:
            fs = pd.NaT
        hl1h = load_hl_candles(p["hl"], "1h")
        hl1m = load_hl_candles(p["hl"], "1m")
        mt5_path = Path(__file__).resolve().parents[2] / "data" / "mt5" / f"{p['mt5']}_M1.parquet"
        if mt5_path.exists():
            m = pd.read_parquet(mt5_path, columns=["time"])
            m["time"] = pd.to_datetime(m["time"], utc=True)
            mt5_start, mt5_end = m.time.min(), m.time.max()
        else:
            mt5_start = mt5_end = pd.NaT
        candle_start = hl1h.time.min() if len(hl1h) else pd.NaT
        # Price-overlap start = HL 1h candle start (API ~5000 bars); funding may begin earlier (carry uses funding from funding_start).
        ov_start = candle_start if pd.notna(candle_start) else fs
        if pd.notna(fs) and pd.notna(ov_start):
            ov_start = max(ov_start, fs) if False else ov_start  # keep candle-limited for gap; carry loads funding independently
        ov_end = min([t for t in [mt5_end, MT5_END_TS] if pd.notna(t)], default=pd.NaT)
        rows.append({
            "hl": p["hl"], "mt5": p["mt5"], "asset": p["asset"], "hl_growth": p["hl_growth"],
            "funding_start": str(fs), "hl_1h_start": str(hl1h.time.min()) if len(hl1h) else None,
            "hl_1h_n": len(hl1h), "hl_1m_n": len(hl1m),
            "hl_1m_start": str(hl1m.time.min()) if len(hl1m) else None,
            "hl_1m_end": str(hl1m.time.max()) if len(hl1m) else None,
            "mt5_m1_start": str(mt5_start), "mt5_m1_end": str(mt5_end),
            "overlap_start": str(ov_start), "overlap_end": str(ov_end),
            "overlap_days": int((ov_end - ov_start).days) if pd.notna(ov_start) and pd.notna(ov_end) else 0,
        })
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "coverage.csv", index=False)
    return df


def swap_usd_per_day(symbol: str, side: str, price: float, notional: float, swaps: pd.DataFrame) -> float:
    """Daily swap in USD for a position of `notional` USD. side in {long, short}.

    Snapshot tick_value_acct appears to be in account currency (≈GBP on this demo), not USD.
    Use geometry: USD per point per lot = contract_size * point for USD-quoted symbols;
    for USDJPY, USD per point per lot = contract_size * point / price.
    """
    row = swaps[swaps.symbol == symbol]
    if row.empty:
        return np.nan
    r = row.iloc[0]
    pts = float(r["swap_long"] if side == "long" else r["swap_short"])
    point = float(r["point"])
    contract = float(r["contract_size"])
    if symbol == "USDJPY":
        usd_per_point_per_lot = contract * point / price  # JPY point → USD
        usd_per_lot_notional = contract
    else:
        usd_per_point_per_lot = contract * point
        usd_per_lot_notional = contract * price
    usd_per_lot_day = pts * usd_per_point_per_lot
    lots = notional / usd_per_lot_notional if usd_per_lot_notional > 0 else 0.0
    return usd_per_lot_day * lots


def is_triple_day(ts: pd.Timestamp, symbol: str, swaps: pd.DataFrame) -> bool:
    row = swaps[swaps.symbol == symbol].iloc[0]
    dayname = row["triple_swap_day"]
    # swap charged at end of broker day ~22:00 UTC; use London weekday of the bar date
    return ts.day_name() == dayname


# -------------------- (C) passive --------------------
def run_passive(split: dict) -> pd.DataFrame:
    rows = []
    for p in PAIRS:
        start = pd.Timestamp(coverage_row_start(p))
        end = MT5_END_TS
        # HL 1m only from ~2026-10-23; MT5 parquets end 2026-10-07 → no M1 overlap.
        # Use H1 as primary aligned grid (deviation from prereg M1; logged in results).
        m = align_h1(p["hl"], p["mt5"], start, end)
        tf = "1h"
        m1 = align_m1(p["hl"], p["mt5"], start, end)
        if len(m1) >= 100:
            m = m1
            tf = "1m"
        if m.empty:
            rows.append({"hl": p["hl"], "mt5": p["mt5"], "tf": tf, "n": 0})
            continue
        g = m.gap_bps
        # half-life from AR(1) on gap
        x = g.values
        if len(x) > 10:
            x0, x1 = x[:-1], x[1:]
            phi = np.corrcoef(x0, x1)[0, 1] if np.std(x0) > 0 and np.std(x1) > 0 else np.nan
            # gap_t = phi gap_{t-1}; half-life = -ln(2)/ln(|phi|)
            if pd.notna(phi) and abs(phi) < 1 and abs(phi) > 1e-6:
                hl_bars = -np.log(2) / np.log(abs(phi))
            else:
                hl_bars = np.nan
        else:
            phi = hl_bars = np.nan
        m["hour"] = m.time.dt.hour
        m["dow"] = m.time.dt.dayofweek
        by_hour = m.groupby("hour").gap_bps.agg(["mean", "median", "std", "count"])
        by_hour.to_csv(RESULTS / f"passive_gap_by_hour_{p['mt5']}.csv")
        rt = mt5_rt_cost_frac(p["mt5"], float(m.mt5_mid.median()))
        hl_fee = 2 * hl_fee_docs_correct(p["hl_growth"], "taker")  # entry+exit taker
        rt_all_bps = (rt + hl_fee) * 1e4
        rows.append({
            "hl": p["hl"], "mt5": p["mt5"], "tf": tf, "n": len(m),
            "gap_mean_bps": g.mean(), "gap_median_bps": g.median(),
            "gap_std_bps": g.std(), "gap_p90_abs_bps": g.abs().quantile(0.90),
            "gap_p99_abs_bps": g.abs().quantile(0.99),
            "frac_abs_gt_rt_cost": float((g.abs() > rt_all_bps).mean()),
            "rt_cost_bps_docs": rt_all_bps,
            "ar1_phi": phi, "half_life_bars": hl_bars,
            "weekend_share": float((m.dow >= 5).mean()),
        })
        # chart one example
        if p["mt5"] in ("US500.cash", "JP225.cash", "XAUUSD", "EURUSD"):
            fig, ax = plt.subplots(figsize=(10, 3.5))
            ax.plot(m.time, m.gap_bps, lw=0.4, alpha=0.8)
            ax.axhline(0, color="k", lw=0.5)
            ax.set_title(f"Gap bps {p['hl']} vs {p['mt5']} ({tf})")
            ax.set_ylabel("bps")
            fig.tight_layout()
            fig.savefig(RESULTS / f"gap_series_{p['mt5']}.png", dpi=120)
            plt.close(fig)
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "passive_gap_summary.csv", index=False)
    return df


def coverage_row_start(p) -> str:
    cov = pd.read_csv(RESULTS / "coverage.csv")
    r = cov[cov.hl == p["hl"]].iloc[0]
    return r["overlap_start"]


# -------------------- (A) gap convergence --------------------
def backtest_gap_pair(p, theta_bps, t_max, fee_sched: str, start, end) -> dict:
    m = align_m1(p["hl"], p["mt5"], start, end)
    if len(m) < 100:
        m = align_h1(p["hl"], p["mt5"], start, end)
        bar_minutes = 60
    else:
        bar_minutes = 1
    # note: typically H1 due to M1 non-overlap
    if m.empty:
        return {"hl": p["hl"], "mt5": p["mt5"], "n_trades": 0, "net_pnl": 0.0}
    # costs
    px = float(m.mt5_mid.median())
    mt5_rt = mt5_rt_cost_frac(p["mt5"], px)
    if fee_sched == "docs":
        hl_f = hl_fee_docs_correct(p["hl_growth"], "taker")
    else:
        hl_f = HL_FEES[fee_sched]["taker"]
    hl_rt = 2 * hl_f  # entry+exit
    # leg risk: median |1-bar return|
    rets = m.hl_mid.pct_change().abs()
    leg_risk = float(rets.median()) if len(rets) else 0.0
    entry_cost = mt5_rt / 2 + hl_f + leg_risk  # one-way approx; charge full at entry+exit
    rt_cost = mt5_rt + hl_rt + 2 * leg_risk
    thr = theta_bps / 1e4 + rt_cost
    exit_thr = (theta_bps / 2) / 1e4

    trades = []
    pos = 0  # +1 short HL / long MT5 (HL rich), -1 opposite
    entry_i = None
    entry_gap = None
    pending = 0  # signal queued for next-bar fill (no same-bar look-ahead)
    max_bars = max(1, t_max // bar_minutes)
    g = m.gap.values
    for i in range(len(m)):
        # fill pending entry at this bar's gap (next bar after signal)
        if pos == 0 and pending != 0:
            pos = pending
            entry_i = i
            entry_gap = g[i]
            pending = 0
        if pos == 0:
            if g[i] > thr:
                pending = 1
            elif g[i] < -thr:
                pending = -1
        else:
            held = i - entry_i
            # exit signal also next-bar: check prior bar for converge, fill now — use current bar for simplicity but require held>=1
            converge = (pos == 1 and g[i] <= exit_thr) or (pos == -1 and g[i] >= -exit_thr)
            if (converge and held >= 1) or held >= max_bars or i == len(m) - 1:
                pnl_frac = pos * (entry_gap - g[i]) - rt_cost
                trades.append({
                    "entry_time": str(m.time.iloc[entry_i]), "exit_time": str(m.time.iloc[i]),
                    "side": pos, "entry_gap_bps": entry_gap * 1e4, "exit_gap_bps": g[i] * 1e4,
                    "hold_bars": held, "pnl_frac_notional": pnl_frac,
                    "pnl_usd": pnl_frac * NOTIONAL,
                })
                pos = 0; entry_i = None
    tdf = pd.DataFrame(trades)
    cap = capital_both_legs(p["hl"], p["asset"], NOTIONAL, HL_MAX_LEV_FALLBACK[p["hl"]])
    if tdf.empty:
        return {"hl": p["hl"], "mt5": p["mt5"], "fee_sched": fee_sched, "theta_bps": theta_bps,
                "t_max": t_max, "n_trades": 0, "net_pnl": 0.0, "capital": cap,
                "ann_on_capital": 0.0, "hit_rate": np.nan, "avg_hold_bars": np.nan,
                "bar_minutes": bar_minutes, "n_bars": len(m)}
    days = max(1, (m.time.iloc[-1] - m.time.iloc[0]).days)
    net = tdf.pnl_usd.sum()
    ann = (net / cap) * (365 / days)
    return {
        "hl": p["hl"], "mt5": p["mt5"], "fee_sched": fee_sched, "theta_bps": theta_bps,
        "t_max": t_max, "n_trades": len(tdf), "net_pnl": net, "capital": cap,
        "ann_on_capital": ann,
        "hit_rate": float((tdf.pnl_usd > 0).mean()),
        "avg_hold_bars": float(tdf.hold_bars.mean()),
        "bar_minutes": bar_minutes, "n_bars": len(m),
        "rt_cost_bps": rt_cost * 1e4,
        "sum_pnl_frac": float(tdf.pnl_frac_notional.sum()),
    }


def run_gap(split: dict) -> pd.DataFrame:
    # IS grid if OOS exists
    oos_start = pd.Timestamp(split["oos_start"]) if split["oos_start"] else None
    thetas = [10, 20, 40, 80]
    tmaxs = [30, 120]
    grid = []
    for p in PAIRS:
        start = pd.Timestamp(coverage_row_start(p))
        end = MT5_END_TS
        is_end = oos_start if oos_start is not None else end
        for th in thetas:
            for tm in tmaxs:
                for sched in ("docs", "growth", "standard"):
                    r = backtest_gap_pair(p, th, tm, sched, start, is_end)
                    r["period"] = "IS" if oos_start is not None else "FULL"
                    grid.append(r)
    gdf = pd.DataFrame(grid)
    gdf.to_csv(RESULTS / "gap_IS_grid.csv", index=False)
    # pick theta, tmax by IS portfolio Sharpe proxy = mean ann across pairs for docs
    docs = gdf[gdf.fee_sched == "docs"]
    best = None
    best_score = -1e9
    for (th, tm), sub in docs.groupby(["theta_bps", "t_max"]):
        # portfolio: equal capital, sum pnl / sum capital
        score = sub["ann_on_capital"].mean()
        if score > best_score:
            best_score = score
            best = (th, tm)
    chosen = {"theta_bps": best[0], "t_max": best[1], "IS_mean_ann": best_score}
    (RESULTS / "gap_chosen.json").write_text(json.dumps(chosen, indent=2))
    # Final run FULL + OOS
    finals = []
    for p in PAIRS:
        start = pd.Timestamp(coverage_row_start(p))
        periods = [("FULL", start, MT5_END_TS)]
        if oos_start is not None:
            periods = [("IS", start, oos_start), ("OOS", oos_start, MT5_END_TS), ("FULL", start, MT5_END_TS)]
        for pname, a, b in periods:
            for sched in ("docs", "growth", "standard"):
                r = backtest_gap_pair(p, chosen["theta_bps"], chosen["t_max"], sched, a, b)
                r["period"] = pname
                finals.append(r)
    fdf = pd.DataFrame(finals)
    fdf.to_csv(RESULTS / "gap_results.csv", index=False)
    return fdf


# -------------------- (B) carry --------------------
def run_carry(split: dict) -> pd.DataFrame:
    swaps = load_swaps()
    oos_start = pd.Timestamp(split["oos_start"]) if split["oos_start"] else None
    rows = []
    equity_curves = {}
    for p in PAIRS:
        start = pd.Timestamp(coverage_row_start(p))
        end = MT5_END_TS
        fund = load_hl_funding(p["hl"])
        fund = fund[(fund.time >= start) & (fund.time <= end)].copy()
        h1 = align_h1(p["hl"], p["mt5"], start, end)
        if fund.empty or h1.empty:
            rows.append({"hl": p["hl"], "mt5": p["mt5"], "n": 0})
            continue
        # Direction: choose the side that earns funding - pays less swap
        # Evaluate both directions' expected carry using mean funding and snapshot swap
        px = float(h1.mt5_mid.median())
        # HL: short receives +rate when rate>0
        mean_f = fund.rate.mean()  # per hour
        # For always-on: each funding print
        # Build hourly timeline from funding
        f = fund.set_index("time").sort_index()
        # Map price for swap calc: asof merge H1
        h1s = h1.set_index("time").sort_index()
        # Daily swap: apply once per calendar day at 21:00 UTC approx when both open
        # Simpler: accrue swap each day as swap_usd_per_day * triple_mult

        for sched in ("docs", "growth", "standard"):
            if sched == "docs":
                hl_f = hl_fee_docs_correct(p["hl_growth"], "taker")
            else:
                hl_f = HL_FEES[sched]["taker"]
            # try both directions; pick better IS / full expected
            for direction in ("short_hl_long_mt5", "long_hl_short_mt5"):
                # funding cashflows
                if direction == "short_hl_long_mt5":
                    fund_pnl = f["rate"] * NOTIONAL  # short receives +rate
                    mt5_side = "long"
                else:
                    fund_pnl = -f["rate"] * NOTIONAL
                    mt5_side = "short"
                # daily swaps
                days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
                swap_pnls = []
                for d in days:
                    # only charge if MT5 would be open that weekday (Mon-Fri)
                    if d.dayofweek >= 5:
                        continue
                    mult = 3.0 if is_triple_day(d, p["mt5"], swaps) else 1.0
                    s = swap_usd_per_day(p["mt5"], mt5_side, px, NOTIONAL, swaps)
                    if np.isnan(s):
                        s = 0.0
                    swap_pnls.append({"time": d + pd.Timedelta(hours=21), "swap_usd": -s * mult})  # pay swap (negative of broker swap if swap negative means pay)
                    # Note: broker swap_long negative means long pays. Our swap_usd_per_day already signed.
                    # Paying means cashflow = swap_usd (already negative if paying). So use +swap_usd as cashflow.
                # Fix: swap_usd_per_day returns pts*tick_val*lots which is negative if paying.
                # Cashflow to us = that number. So store as swap_usd without extra minus.
                # Recalc:
                swap_pnls = []
                for d in days:
                    if d.dayofweek >= 5:
                        continue
                    mult = 3.0 if is_triple_day(d, p["mt5"], swaps) else 1.0
                    s = swap_usd_per_day(p["mt5"], mt5_side, px, NOTIONAL, swaps)
                    if np.isnan(s):
                        s = 0.0
                    swap_pnls.append({"time": d + pd.Timedelta(hours=21), "swap_usd": s * mult})
                sdf = pd.DataFrame(swap_pnls)
                # Entry/exit fees once for always-on
                fee_usd = 2 * (hl_f + mt5_rt_cost_frac(p["mt5"], px) / 2) * NOTIONAL
                # Basis: mark H1 gap change over sample (enter first, exit last)
                basis = 0.0
                if len(h1) >= 2:
                    # short HL long MT5: pnl frac = -(hl_ret) + mt5_ret = -Δhl/hl + Δmt5/mt5 ≈ -(gap_end - gap_start) if levels similar
                    if direction == "short_hl_long_mt5":
                        basis = - (h1.hl_mid.iloc[-1] / h1.hl_mid.iloc[0] - 1) + (h1.mt5_mid.iloc[-1] / h1.mt5_mid.iloc[0] - 1)
                    else:
                        basis = (h1.hl_mid.iloc[-1] / h1.hl_mid.iloc[0] - 1) - (h1.mt5_mid.iloc[-1] / h1.mt5_mid.iloc[0] - 1)
                    basis *= NOTIONAL
                fund_total = float(fund_pnl.sum())
                swap_total = float(sdf.swap_usd.sum()) if len(sdf) else 0.0
                net = fund_total + swap_total + basis - fee_usd
                cap = capital_both_legs(p["hl"], p["asset"], NOTIONAL, HL_MAX_LEV_FALLBACK[p["hl"]])
                days_n = max(1, (end - start).days)
                ann = (net / cap) * (365 / days_n)
                # period splits
                def period_net(a, b):
                    fp = float(fund_pnl[(fund_pnl.index >= a) & (fund_pnl.index <= b)].sum())
                    sp = float(sdf[(sdf.time >= a) & (sdf.time <= b)].swap_usd.sum()) if len(sdf) else 0.0
                    # proportional basis/fees rough: fees once if period includes start
                    return fp + sp

                rec = {
                    "hl": p["hl"], "mt5": p["mt5"], "direction": direction, "fee_sched": sched,
                    "period": "FULL", "funding_usd": fund_total, "swap_usd": swap_total,
                    "basis_usd": basis, "fees_usd": -fee_usd, "net_usd": net,
                    "capital": cap, "ann_on_capital": ann, "days": days_n,
                    "mean_funding_ann": mean_f * 24 * 365,
                    "n_funding": len(f),
                    "swaps_source": "swaps_snapshot_2026-10-27.csv (constant assumed)",
                }
                rows.append(rec)
                if oos_start is not None:
                    for pname, a, b in [("IS", start, oos_start), ("OOS", oos_start, end)]:
                        nnet = period_net(a, b)
                        # allocate fees to IS only
                        fees = -fee_usd if pname == "IS" else 0.0
                        # basis to full only roughly skip
                        ddays = max(1, (b - a).days)
                        rows.append({
                            "hl": p["hl"], "mt5": p["mt5"], "direction": direction, "fee_sched": sched,
                            "period": pname, "funding_usd": np.nan, "swap_usd": np.nan,
                            "basis_usd": 0.0, "fees_usd": fees, "net_usd": nnet + fees,
                            "capital": cap,
                            "ann_on_capital": ((nnet + fees) / cap) * (365 / ddays),
                            "days": ddays, "mean_funding_ann": mean_f * 24 * 365,
                            "n_funding": len(f),
                            "swaps_source": "swaps_snapshot_2026-10-27.csv (constant assumed)",
                        })
                if sched == "docs" and direction == "short_hl_long_mt5":
                    # equity curve from cumulative funding+swap
                    eq = fund_pnl.cumsum().rename("cum_funding")
                    equity_curves[p["mt5"]] = eq

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "carry_results.csv", index=False)
    # pick best direction per pair on IS docs (or FULL if no OOS) — no full-sample look-ahead
    if not df.empty:
        pick_period = "IS" if (df.period == "IS").any() else "FULL"
        sub = df[(df.fee_sched == "docs") & (df.period == pick_period)]
        best = sub.sort_values("ann_on_capital", ascending=False).groupby("mt5").head(1)
        best.to_csv(RESULTS / f"carry_best_direction.csv", index=False)
        # also save FULL metrics for those IS-chosen directions
        keys = set(zip(best.mt5, best.direction))
        full = df[(df.fee_sched == "docs") & (df.period == "FULL")]
        full = full[full.apply(lambda r: (r.mt5, r.direction) in keys, axis=1)]
        full.to_csv(RESULTS / "carry_best_direction_FULL_metrics.csv", index=False)
        print("carry direction pick period:", pick_period, flush=True)
        # chart
        if equity_curves:
            fig, ax = plt.subplots(figsize=(10, 4))
            for k, s in equity_curves.items():
                ax.plot(s.index, s.values, label=k, lw=1)
            ax.legend(fontsize=7, ncol=2)
            ax.set_title("Cumulative HL funding $ (short HL) — docs fee path excludes fees in curve")
            ax.set_ylabel("USD on $10k notional")
            fig.tight_layout()
            fig.savefig(RESULTS / "carry_cum_funding.png", dpi=120)
            plt.close(fig)
    return df


def portfolio_summary(gap_df, carry_df, split):
    lines = []
    # Gap portfolio docs
    for period in gap_df.period.unique():
        sub = gap_df[(gap_df.fee_sched == "docs") & (gap_df.period == period)]
        if sub.empty:
            continue
        cap = sub.capital.sum()
        net = sub.net_pnl.sum()
        days = max(1, (pd.Timestamp(split["global_end"]) - pd.Timestamp(split["global_start"])).days)
        if period == "OOS" and split["oos_start"]:
            days = max(1, (pd.Timestamp(split["global_end"]) - pd.Timestamp(split["oos_start"])).days)
        elif period == "IS" and split["oos_start"]:
            days = max(1, (pd.Timestamp(split["oos_start"]) - pd.Timestamp(split["global_start"])).days)
        ann = (net / cap) * (365 / days) if cap else 0
        lines.append({"strategy": "A_gap", "period": period, "net_usd": net, "capital": cap, "ann_on_capital": ann,
                      "n_trades": int(sub.n_trades.sum()), "pairs": len(sub)})
    # Carry: best direction per pair docs
    if not carry_df.empty:
        best = pd.read_csv(RESULTS / "carry_best_direction.csv")
        for period in ["FULL", "IS", "OOS"]:
            sub = carry_df[(carry_df.fee_sched == "docs") & (carry_df.period == period)]
            if sub.empty:
                continue
            # filter to best directions
            keys = set(zip(best.mt5, best.direction))
            sub = sub[sub.apply(lambda r: (r.mt5, r.direction) in keys, axis=1)]
            cap = sub.capital.sum()
            net = sub.net_usd.sum()
            days = int(sub.days.mean()) if len(sub) else 1
            ann = (net / cap) * (365 / max(1, days)) if cap else 0
            lines.append({"strategy": "B_carry", "period": period, "net_usd": net, "capital": cap,
                          "ann_on_capital": ann, "n_trades": len(sub), "pairs": len(sub)})
    pdf = pd.DataFrame(lines)
    pdf.to_csv(RESULTS / "portfolio_summary.csv", index=False)
    return pdf


def main():
    print("coverage...", flush=True)
    cov = coverage_table()
    print(cov[["hl", "mt5", "overlap_start", "overlap_end", "overlap_days", "hl_1m_n"]].to_string(), flush=True)
    split = freeze_split(cov)
    print("split", split, flush=True)
    print("passive...", flush=True)
    pas = run_passive(split)
    print(pas.to_string(), flush=True)
    print("gap...", flush=True)
    gap = run_gap(split)
    print("carry...", flush=True)
    carry = run_carry(split)
    print("portfolio...", flush=True)
    port = portfolio_summary(gap, carry, split)
    print(port.to_string(), flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
