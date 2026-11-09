"""Minute-level gap / session-open backtests + descriptive stats. Paper only."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from common_m1 import (
    PAIRS, RESULTS, DATA_AUX, NOTIONAL, K_GAP, K_OPEN, T_MAX_GAP, T_MAX_OPEN,
    ROLL_MEDIAN, HL_HALF_SPREAD_FLOOR_BPS, LATENCY_SECONDS, capital_both_legs,
    hl_fee_docs_correct, HL_MAX_LEV_FALLBACK, pair_by_mt5, COMMISSION_RT_USD,
)
from load_m1 import (
    probe_time_offset, build_aligned, load_hl_half_spreads, load_ticks,
    load_funding, inventory_check, executable_mt5_price, mt5_commission_frac,
    round_trip_cost_frac, load_hl_1m, ticks_to_minute,
)

RESULTS.mkdir(parents=True, exist_ok=True)


def half_life_minutes(gap: pd.Series) -> float:
    """AR(1) half-life of gap in minutes. Returns nan if not mean-reverting."""
    x = gap.dropna().values
    if len(x) < 50:
        return float("nan")
    x0, x1 = x[:-1], x[1:]
    # demean
    x0m = x0 - x0.mean()
    x1m = x1 - x1.mean()
    den = (x0m ** 2).sum()
    if den <= 0:
        return float("nan")
    phi = float((x0m * x1m).sum() / den)
    if phi <= 0 or phi >= 1:
        return float("nan")
    return float(-np.log(2) / np.log(phi))


def freeze_split(aligned_by_pair: dict[str, pd.DataFrame]) -> dict:
    starts, ends = [], []
    for df in aligned_by_pair.values():
        if df is None or df.empty:
            continue
        starts.append(df.time.min())
        ends.append(df.time.max())
    if not starts:
        split = {"written_before_pnl": True, "mode": "no_data", "calendar_days": 0}
        (RESULTS / "sample_split.json").write_text(json.dumps(split, indent=2))
        return split
    g0, g1 = min(starts), max(ends)
    days = (g1 - g0).total_seconds() / 86400.0
    # prereg: <10 calendar days => descriptive only; still write 60/40 illustrative
    cut = g0 + (g1 - g0) * 0.60
    mode = "descriptive_illustrative_60_40" if days < 10 else "time_60_40"
    split = {
        "written_before_pnl": True,
        "global_start": str(g0),
        "global_end": str(g1),
        "calendar_days": round(days, 3),
        "mode": mode,
        "is_end": str(cut),
        "oos_start": str(cut),
        "note": "Descriptive only if calendar_days < 10 (prereg). Illustrative 60/40 still computed.",
    }
    (RESULTS / "sample_split.json").write_text(json.dumps(split, indent=2))
    return split


def descriptive_pair(df: pd.DataFrame) -> dict:
    g = df["gap_bps"]
    med = df["gap_med"] * 1e4
    dev = (df["gap"] - df["gap_med"]).abs()
    c = df["rt_cost"]
    return {
        "n_minutes": int(len(df)),
        "gap_mean_bps": float(g.mean()),
        "gap_median_bps": float(g.median()),
        "gap_std_bps": float(g.std()),
        "gap_p10_bps": float(g.quantile(0.10)),
        "gap_p90_bps": float(g.quantile(0.90)),
        "half_life_min": half_life_minutes(df["gap"]),
        "frac_abs_gap_gt_cost": float((g.abs() > df["rt_cost_bps"]).mean()),
        "frac_abs_dev_gt_cost": float((dev > c).mean()) if med.notna().any() else float("nan"),
        "rt_cost_bps_median": float(df["rt_cost_bps"].median()),
        "mt5_spread_bps_median": float((df["mt5_spread"] / df["mt5_mid"] * 1e4).median()),
        "hl_half_bps": float(df["hl_half_bps"].iloc[0]) if len(df) else float("nan"),
        "t_start": str(df.time.min()),
        "t_end": str(df.time.max()),
    }


def spreads_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["hour_utc"] = x["time"].dt.hour
    x["mt5_spread_bps"] = x["mt5_spread"] / x["mt5_mid"] * 1e4
    return x.groupby("hour_utc").agg(
        n=("mt5_spread_bps", "size"),
        mt5_spread_bps_med=("mt5_spread_bps", "median"),
        gap_bps_med=("gap_bps", "median"),
        gap_bps_std=("gap_bps", "std"),
        frac_abs_gap_gt_cost=("gap_bps", lambda s: float((s.abs() > x.loc[s.index, "rt_cost_bps"]).mean())),
    ).reset_index()


def simulate_gap_trades(df: pd.DataFrame, ticks: pd.DataFrame, p: dict,
                        k: float = K_GAP, t_max: int = T_MAX_GAP,
                        latency_s: float = 0.0) -> pd.DataFrame:
    """Next-minute execution; MT5 at tick bid/ask (+latency); HL at close ± half spread."""
    if df.empty or df["gap_med"].isna().all():
        return pd.DataFrame()
    hl_half = float(df["hl_half_bps"].iloc[0]) / 1e4
    hl_fee = hl_fee_docs_correct(p["hl_growth"], "taker")
    rows = []
    i = 0
    n = len(df)
    times = df["time"].values
    gaps = df["gap"].values
    meds = df["gap_med"].values
    costs = df["rt_cost"].values
    hl_mids = df["hl_mid"].values
    mt5_mids = df["mt5_mid"].values
    while i < n - 1:
        if np.isnan(meds[i]) or np.isnan(costs[i]):
            i += 1
            continue
        dev = gaps[i] - meds[i]
        if abs(dev) <= k * costs[i]:
            i += 1
            continue
        # signal at i, execute at i+1
        j = i + 1
        if j >= n:
            break
        # direction: if gap>med, HL rich → short HL / long MT5
        short_hl = dev > 0
        entry_ts = pd.Timestamp(times[j]).tz_localize("UTC") if pd.Timestamp(times[j]).tzinfo is None else pd.Timestamp(times[j]).tz_convert("UTC")
        # HL fill
        if short_hl:
            hl_entry = float(hl_mids[j]) - hl_half  # sell HL at mid - half
            mt5_side_entry = "buy"
        else:
            hl_entry = float(hl_mids[j]) + hl_half
            mt5_side_entry = "sell"
        mt5_entry = executable_mt5_price(ticks, entry_ts, mt5_side_entry, latency_s)
        if mt5_entry is None or not np.isfinite(hl_entry):
            i = j
            continue
        # hold until reversion or t_max
        exit_j = None
        for kidx in range(j, min(j + t_max, n)):
            if np.isnan(meds[kidx]):
                continue
            if abs(gaps[kidx] - meds[kidx]) <= 0.5 * costs[kidx]:
                exit_j = kidx
                break
        if exit_j is None:
            exit_j = min(j + t_max - 1, n - 1)
        exit_ts = pd.Timestamp(times[exit_j]).tz_localize("UTC") if pd.Timestamp(times[exit_j]).tzinfo is None else pd.Timestamp(times[exit_j]).tz_convert("UTC")
        if short_hl:
            hl_exit = float(hl_mids[exit_j]) + hl_half  # buy back
            mt5_side_exit = "sell"
        else:
            hl_exit = float(hl_mids[exit_j]) - hl_half
            mt5_side_exit = "buy"
        mt5_exit = executable_mt5_price(ticks, exit_ts, mt5_side_exit, latency_s)
        if mt5_exit is None:
            i = exit_j + 1
            continue
        # PnL in USD on $10k notional each leg (price return * N)
        if short_hl:
            hl_ret = (hl_entry - hl_exit) / hl_entry
            mt5_ret = (mt5_exit - mt5_entry) / mt5_entry
        else:
            hl_ret = (hl_exit - hl_entry) / hl_entry
            mt5_ret = (mt5_entry - mt5_exit) / mt5_entry
        gross = (hl_ret + mt5_ret) * NOTIONAL
        # fees: HL taker both fills; MT5 commission RT once (entry+exit covered by COMMISSION_RT)
        hl_fees = 2.0 * hl_fee * NOTIONAL
        mt5_comm = mt5_commission_frac(p["mt5"], float(mt5_mids[j])) * NOTIONAL
        # spreads already in executable prices / hl half — do not double-count
        net = gross - hl_fees - mt5_comm
        rows.append({
            "symbol": p["mt5"], "hl": p["hl"], "latency_s": latency_s,
            "entry_time": entry_ts, "exit_time": exit_ts,
            "hold_min": int((exit_j - j) + 1),
            "side": "short_hl_long_mt5" if short_hl else "long_hl_short_mt5",
            "entry_gap_bps": float(gaps[i] * 1e4),
            "entry_dev_bps": float(dev * 1e4),
            "rt_cost_bps": float(costs[i] * 1e4),
            "gross_usd": float(gross), "net_usd": float(net),
            "gross_bp": float(gross / NOTIONAL * 1e4),
            "net_bp": float(net / NOTIONAL * 1e4),
            "hl_fees_usd": float(hl_fees), "mt5_comm_usd": float(mt5_comm),
        })
        i = exit_j + 1
    return pd.DataFrame(rows)


def find_reopens(df: pd.DataFrame, gap_hours: float = 3.0) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    t = df["time"]
    dt = t.diff()
    mask = dt >= pd.Timedelta(hours=gap_hours)
    idx = np.where(mask.values)[0]
    rows = []
    for i in idx:
        prev = df.iloc[i - 1]
        cur = df.iloc[i]
        weekend = dt.iloc[i] >= pd.Timedelta(hours=24)
        rows.append({
            "reopen_time": cur["time"],
            "gap_hours": float(dt.iloc[i].total_seconds() / 3600.0),
            "weekend": bool(weekend),
            "gap_bps_reopen": float(cur["gap_bps"]),
            "gap_bps_preclose": float(prev["gap_bps"]),
            "gap_med_bps": float(cur["gap_med"] * 1e4) if pd.notna(cur["gap_med"]) else float("nan"),
            "rt_cost_bps": float(cur["rt_cost_bps"]),
        })
    return pd.DataFrame(rows)


def simulate_open_trades(df: pd.DataFrame, ticks: pd.DataFrame, p: dict,
                         reopens: pd.DataFrame, latency_s: float = 0.0) -> pd.DataFrame:
    if reopens.empty or df.empty:
        return pd.DataFrame()
    # reuse gap simulator but only allow entries at reopen minutes
    # Build a restricted signal mask
    reopen_times = set(pd.to_datetime(reopens["reopen_time"], utc=True))
    d = df.copy()
    # force non-reopen signals off by blanking med where not reopen... better: custom loop
    hl_half = float(d["hl_half_bps"].iloc[0]) / 1e4
    hl_fee = hl_fee_docs_correct(p["hl_growth"], "taker")
    rows = []
    time_to_i = {pd.Timestamp(t): i for i, t in enumerate(d["time"])}
    for _, r in reopens.iterrows():
        ts = pd.Timestamp(r["reopen_time"])
        if ts not in time_to_i:
            continue
        i = time_to_i[ts]
        if i >= len(d) - 1:
            continue
        med = d.iloc[i]["gap_med"]
        cost = d.iloc[i]["rt_cost"]
        gap = d.iloc[i]["gap"]
        if pd.isna(med) or pd.isna(cost):
            continue
        dev = gap - med
        if abs(dev) <= K_OPEN * cost:
            continue
        j = i + 1
        short_hl = dev > 0
        entry_ts = pd.Timestamp(d.iloc[j]["time"])
        if short_hl:
            hl_entry = float(d.iloc[j]["hl_mid"]) - hl_half
            mt5_side_entry = "buy"
        else:
            hl_entry = float(d.iloc[j]["hl_mid"]) + hl_half
            mt5_side_entry = "sell"
        mt5_entry = executable_mt5_price(ticks, entry_ts, mt5_side_entry, latency_s)
        if mt5_entry is None:
            continue
        exit_j = None
        for kidx in range(j, min(j + T_MAX_OPEN, len(d))):
            m = d.iloc[kidx]["gap_med"]
            c = d.iloc[kidx]["rt_cost"]
            g = d.iloc[kidx]["gap"]
            if pd.isna(m) or pd.isna(c):
                continue
            if abs(g - m) <= 0.5 * c:
                exit_j = kidx
                break
        if exit_j is None:
            exit_j = min(j + T_MAX_OPEN - 1, len(d) - 1)
        exit_ts = pd.Timestamp(d.iloc[exit_j]["time"])
        if short_hl:
            hl_exit = float(d.iloc[exit_j]["hl_mid"]) + hl_half
            mt5_side_exit = "sell"
        else:
            hl_exit = float(d.iloc[exit_j]["hl_mid"]) - hl_half
            mt5_side_exit = "buy"
        mt5_exit = executable_mt5_price(ticks, exit_ts, mt5_side_exit, latency_s)
        if mt5_exit is None:
            continue
        if short_hl:
            hl_ret = (hl_entry - hl_exit) / hl_entry
            mt5_ret = (mt5_exit - mt5_entry) / mt5_entry
        else:
            hl_ret = (hl_exit - hl_entry) / hl_entry
            mt5_ret = (mt5_entry - mt5_exit) / mt5_entry
        gross = (hl_ret + mt5_ret) * NOTIONAL
        hl_fees = 2.0 * hl_fee * NOTIONAL
        mt5_comm = mt5_commission_frac(p["mt5"], float(d.iloc[j]["mt5_mid"])) * NOTIONAL
        net = gross - hl_fees - mt5_comm
        rows.append({
            "symbol": p["mt5"], "hl": p["hl"], "latency_s": latency_s,
            "weekend": bool(r["weekend"]), "gap_hours": float(r["gap_hours"]),
            "entry_time": entry_ts, "exit_time": exit_ts,
            "hold_min": int(exit_j - j + 1),
            "side": "short_hl_long_mt5" if short_hl else "long_hl_short_mt5",
            "entry_gap_bps": float(gap * 1e4), "entry_dev_bps": float(dev * 1e4),
            "rt_cost_bps": float(cost * 1e4),
            "gross_usd": float(gross), "net_usd": float(net),
            "gross_bp": float(gross / NOTIONAL * 1e4), "net_bp": float(net / NOTIONAL * 1e4),
        })
    return pd.DataFrame(rows)


def summarize_trades(trades: pd.DataFrame, split: dict, label: str) -> dict:
    if trades is None or trades.empty:
        return {"label": label, "trades": 0, "gross_usd": 0.0, "net_usd": 0.0,
                "gross_bp": 0.0, "net_bp": 0.0, "is_net_usd": 0.0, "oos_net_usd": 0.0,
                "is_trades": 0, "oos_trades": 0}
    cut = pd.Timestamp(split["oos_start"]) if split.get("oos_start") else None
    def agg(t):
        if t.empty:
            return 0, 0.0, 0.0, 0.0, 0.0
        return (len(t), float(t.gross_usd.sum()), float(t.net_usd.sum()),
                float(t.gross_bp.sum()), float(t.net_bp.sum()))
    n, g, net, gbp, nbp = agg(trades)
    if cut is not None:
        is_ = trades[trades.entry_time < cut]
        oos = trades[trades.entry_time >= cut]
        is_n, _, is_net, _, is_nbp = agg(is_)
        oos_n, _, oos_net, _, oos_nbp = agg(oos)
    else:
        is_n = oos_n = 0
        is_net = oos_net = is_nbp = oos_nbp = 0.0
    return {
        "label": label, "trades": n, "gross_usd": g, "net_usd": net,
        "gross_bp": gbp, "net_bp": nbp,
        "is_trades": is_n, "oos_trades": oos_n,
        "is_net_usd": is_net, "oos_net_usd": oos_net,
        "is_net_bp": is_nbp, "oos_net_bp": oos_nbp,
    }


def make_plots(aligned: dict[str, pd.DataFrame], all_edge: pd.DataFrame):
    # 1) GOLD gap series
    for sym, title in [("XAUUSD", "GOLD"), ("US500.cash", "SP500")]:
        df = aligned.get(sym)
        if df is None or df.empty:
            continue
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(df["time"], df["gap_bps"], lw=0.7, color="steelblue", label="gap bps")
        if df["gap_med"].notna().any():
            ax.plot(df["time"], df["gap_med"] * 1e4, lw=0.8, color="orange", label="roll med 60")
        c = df["rt_cost_bps"]
        ax.fill_between(df["time"], -c, c, color="gray", alpha=0.25, label="± RT cost")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"{title} ({sym}) minute gap vs RT cost")
        ax.set_ylabel("bps")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        fig.savefig(RESULTS / f"gap_series_{sym.replace('.', '_')}.png", dpi=120)
        plt.close(fig)
    # 2) capturable edge distribution
    if all_edge is not None and not all_edge.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        for sym, g in all_edge.groupby("symbol"):
            ax.hist(g["edge_bps"], bins=40, alpha=0.45, label=sym)
        ax.set_xlabel("capturable edge bps = (|gap-med| - cost)_+")
        ax.set_ylabel("minutes")
        ax.set_title("Distribution of capturable edge (concurrent minutes)")
        ax.legend(fontsize=7, ncol=2)
        fig.tight_layout()
        fig.savefig(RESULTS / "capturable_edge_hist.png", dpi=120)
        plt.close(fig)


def run():
    inv = inventory_check()
    (RESULTS / "inventory.json").write_text(json.dumps(inv, indent=2))
    print("inventory", inv)

    probes = {
        "EURUSD": probe_time_offset("EURUSD", "xyz:EUR"),
        "XAUUSD": probe_time_offset("XAUUSD", "xyz:GOLD"),
        "US500.cash": probe_time_offset("US500.cash", "xyz:SP500"),
    }
    votes = [probes[k]["chosen_offset_hours"] for k in probes]
    chosen = int(max(set(votes), key=votes.count))
    offset_info = {"chosen_offset_hours": chosen, "votes": votes, "probes": probes}
    (RESULTS / "time_offset.json").write_text(json.dumps(offset_info, indent=2, default=str))
    print("time offset chosen", chosen, "hours; votes", votes)

    hl_spreads = load_hl_half_spreads()
    print("hl half spreads bps", hl_spreads)

    aligned = {}
    desc_rows = []
    hour_rows = []
    edge_parts = []
    reopen_parts = []

    for p in PAIRS:
        half = hl_spreads.get(p["hl"], HL_HALF_SPREAD_FLOOR_BPS)
        half = max(half, HL_HALF_SPREAD_FLOOR_BPS)
        df = build_aligned(p["mt5"], p["hl"], chosen, half)
        aligned[p["mt5"]] = df
        print(p["mt5"], "aligned", len(df))
        if df.empty:
            desc_rows.append({"mt5": p["mt5"], "hl": p["hl"], "n_minutes": 0})
            continue
        d = descriptive_pair(df)
        d.update({"mt5": p["mt5"], "hl": p["hl"], "asset": p["asset"], "hl_growth": p["hl_growth"]})
        desc_rows.append(d)
        hb = spreads_by_hour(df)
        hb["mt5"] = p["mt5"]
        hour_rows.append(hb)
        e = df.dropna(subset=["gap_med"]).copy()
        e["edge_bps"] = ((e["gap"] - e["gap_med"]).abs() - e["rt_cost"]).clip(lower=0) * 1e4
        e["symbol"] = p["mt5"]
        edge_parts.append(e[["symbol", "time", "edge_bps", "gap_bps", "rt_cost_bps"]])
        rp = find_reopens(df)
        if not rp.empty:
            rp["mt5"] = p["mt5"]
            reopen_parts.append(rp)

    # FREEZE SPLIT before PnL
    split = freeze_split(aligned)
    print("split", split)

    desc = pd.DataFrame(desc_rows)
    desc.to_csv(RESULTS / "passive_summary.csv", index=False)
    if hour_rows:
        pd.concat(hour_rows, ignore_index=True).to_csv(RESULTS / "spreads_by_hour.csv", index=False)
    all_edge = pd.concat(edge_parts, ignore_index=True) if edge_parts else pd.DataFrame()
    if not all_edge.empty:
        all_edge.to_csv(RESULTS / "capturable_edge_minutes.csv", index=False)
    reopens = pd.concat(reopen_parts, ignore_index=True) if reopen_parts else pd.DataFrame()
    if not reopens.empty:
        reopens.to_csv(RESULTS / "session_reopens.csv", index=False)

    make_plots(aligned, all_edge)

    # Strategy PnL AFTER split freeze
    trade_rows = []
    open_trade_rows = []
    summary_rows = []
    lat_rows = []

    for p in PAIRS:
        df = aligned.get(p["mt5"])
        if df is None or df.empty:
            summary_rows.append({"mt5": p["mt5"], "hl": p["hl"], "strategy": "gap", "trades": 0})
            continue
        # ticks with same offset
        start = df.time.min() - pd.Timedelta(days=1)
        end = df.time.max() + pd.Timedelta(hours=2)
        ticks = load_ticks(p["mt5"], start, end)
        ticks = ticks.copy()
        ticks["time"] = ticks["time"] - pd.Timedelta(hours=chosen)

        for lat in LATENCY_SECONDS:
            tr = simulate_gap_trades(df, ticks, p, latency_s=float(lat))
            if not tr.empty:
                tr["strategy"] = "gap"
                if lat == 0:
                    trade_rows.append(tr)
                sm = summarize_trades(tr, split, f"gap_{p['mt5']}_lat{lat}")
                sm.update({"mt5": p["mt5"], "hl": p["hl"], "strategy": "gap", "latency_s": lat,
                           "n_minutes": len(df),
                           "frac_abs_gap_gt_cost": float((df.gap_bps.abs() > df.rt_cost_bps).mean())})
                if lat == 0:
                    summary_rows.append(sm)
                else:
                    lat_rows.append(sm)

        rp = find_reopens(df)
        tr_o = simulate_open_trades(df, ticks, p, rp, latency_s=0.0)
        if not tr_o.empty:
            tr_o["strategy"] = "session_open"
            open_trade_rows.append(tr_o)
        sm_o = summarize_trades(tr_o, split, f"open_{p['mt5']}")
        sm_o.update({"mt5": p["mt5"], "hl": p["hl"], "strategy": "session_open", "latency_s": 0,
                     "n_reopens": int(len(rp)),
                     "n_weekend_reopens": int(rp["weekend"].sum()) if not rp.empty else 0})
        summary_rows.append(sm_o)

    trades = pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame()
    opens = pd.concat(open_trade_rows, ignore_index=True) if open_trade_rows else pd.DataFrame()
    if not trades.empty:
        trades.to_csv(RESULTS / "gap_trades.csv", index=False)
    if not opens.empty:
        opens.to_csv(RESULTS / "session_open_trades.csv", index=False)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(RESULTS / "strategy_summary.csv", index=False)
    if lat_rows:
        pd.DataFrame(lat_rows).to_csv(RESULTS / "latency_sensitivity.csv", index=False)

    # portfolio gap lat0
    gap_sum = summary[(summary.strategy == "gap") & (summary.get("latency_s", 0) == 0)] if "latency_s" in summary.columns else summary[summary.strategy == "gap"]
    port = {
        "split_mode": split.get("mode"),
        "calendar_days": split.get("calendar_days"),
        "gap_trades": int(gap_sum["trades"].sum()) if len(gap_sum) and "trades" in gap_sum else 0,
        "gap_net_usd": float(gap_sum["net_usd"].sum()) if len(gap_sum) and "net_usd" in gap_sum else 0.0,
        "gap_gross_usd": float(gap_sum["gross_usd"].sum()) if len(gap_sum) and "gross_usd" in gap_sum else 0.0,
        "gap_is_net_usd": float(gap_sum["is_net_usd"].sum()) if len(gap_sum) and "is_net_usd" in gap_sum else 0.0,
        "gap_oos_net_usd": float(gap_sum["oos_net_usd"].sum()) if len(gap_sum) and "oos_net_usd" in gap_sum else 0.0,
        "open_trades": int(summary.loc[summary.strategy == "session_open", "trades"].sum()) if len(summary) else 0,
    }
    (RESULTS / "portfolio_summary.json").write_text(json.dumps(port, indent=2))
    print("portfolio", port)
    print("DONE")
    return {"split": split, "offset": chosen, "desc": desc, "summary": summary, "port": port}


if __name__ == "__main__":
    run()
