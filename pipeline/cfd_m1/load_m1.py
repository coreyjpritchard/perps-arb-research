"""Load MT5 M1/ticks + HL 1m, verify time offset, build aligned minute frames."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from common_m1 import (
    PAIRS, DATA_MT5_M1, DATA_MT5_TICKS, DATA_HL_1M, DATA_AUX, DATA_LIVE, RESULTS,
    HL_HALF_SPREAD_FLOOR_BPS, pair_by_mt5, mt5_spread_pts, hl_fee_docs_correct,
    COMMISSION_RT_USD, NOTIONAL,
)


def load_swaps() -> pd.DataFrame:
    path = DATA_LIVE / "swaps_snapshot_2026-10-27.csv"
    return pd.read_csv(path)


def load_hl_1m(coin: str) -> pd.DataFrame:
    path = DATA_HL_1M / f"{coin.replace(':', '_')}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["time", "hl_close", "hl_volume", "hl_trades"])
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.rename(columns={"close": "hl_close", "volume": "hl_volume", "trades": "hl_trades"})
    return df[["time", "hl_close", "hl_volume", "hl_trades"]].sort_values("time").reset_index(drop=True)


def load_mt5_m1_bars(symbol: str) -> pd.DataFrame:
    path = DATA_MT5_M1 / f"{symbol}_M1.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.sort_values("time").reset_index(drop=True)


def list_tick_files(symbol: str) -> list[Path]:
    return sorted(DATA_MT5_TICKS.glob(f"{symbol}_*.parquet"))


def load_ticks(symbol: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    files = list_tick_files(symbol)
    if not files:
        return pd.DataFrame(columns=["time", "bid", "ask", "spread"])
    parts = []
    for f in files:
        # filename SYMBOL_YYYY-MM-DD.parquet — quick date filter
        day = f.stem.split("_")[-1]
        try:
            d = pd.Timestamp(day, tz="UTC")
        except Exception:
            d = None
        if start is not None and d is not None and d.normalize() + pd.Timedelta(days=1) < start.normalize():
            continue
        if end is not None and d is not None and d.normalize() > end.normalize():
            continue
        t = pd.read_parquet(f, columns=["time", "bid", "ask", "spread"])
        t["time"] = pd.to_datetime(t["time"], utc=True)
        parts.append(t)
    if not parts:
        return pd.DataFrame(columns=["time", "bid", "ask", "spread"])
    df = pd.concat(parts, ignore_index=True).sort_values("time")
    if start is not None:
        df = df[df.time >= start]
    if end is not None:
        df = df[df.time <= end]
    return df.reset_index(drop=True)


def ticks_to_minute(ticks: pd.DataFrame) -> pd.DataFrame:
    """Last tick per UTC minute → bid/ask/mid/spread; also mean spread in minute."""
    if ticks.empty:
        return pd.DataFrame(columns=[
            "time", "mt5_bid", "mt5_ask", "mt5_mid", "mt5_spread", "mt5_spread_mean", "n_ticks"
        ])
    t = ticks.copy()
    t["minute"] = t["time"].dt.floor("min")
    # last tick in minute for executable mid proxy
    last = t.groupby("minute", sort=True).tail(1)
    agg = t.groupby("minute").agg(
        mt5_spread_mean=("spread", "mean"),
        n_ticks=("bid", "size"),
        mt5_spread_max=("spread", "max"),
    )
    out = last.set_index("minute")[["bid", "ask", "spread"]].rename(
        columns={"bid": "mt5_bid", "ask": "mt5_ask", "spread": "mt5_spread"}
    )
    out = out.join(agg)
    out["mt5_mid"] = 0.5 * (out["mt5_bid"] + out["mt5_ask"])
    out = out.reset_index().rename(columns={"minute": "time"})
    return out


def load_hl_half_spreads() -> dict[str, float]:
    """Median half-spread (bps) per coin from l2 snapshots; floor applied by caller."""
    path = DATA_AUX / "l2book" / "l2_snapshots.csv"
    out = {}
    if not path.exists():
        return out
    df = pd.read_csv(path)
    df = df[df["error"].fillna("").astype(str) == ""]
    if df.empty or "half_spread_bps" not in df.columns:
        return out
    for coin, g in df.groupby("coin"):
        vals = pd.to_numeric(g["half_spread_bps"], errors="coerce").dropna()
        if len(vals):
            out[str(coin)] = float(vals.median())
    return out


def load_funding(coin: str) -> pd.DataFrame:
    path = DATA_AUX / f"funding_{coin.replace(':', '_')}.json"
    if not path.exists():
        # fallback to hourly hip3 folder
        path = ROOT_HL_HIP3() / f"funding_{coin.replace(':', '_')}.json"
    if not path.exists():
        return pd.DataFrame(columns=["time", "rate", "premium"])
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["rate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    return df[["time", "rate", "premium"]].sort_values("time").reset_index(drop=True)


def ROOT_HL_HIP3() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "hl_hip3"


def mt5_commission_frac(symbol: str, price: float) -> float:
    p = pair_by_mt5(symbol)
    if p["asset"] == "fx" and symbol == "USDJPY":
        usd_per_lot = p["contract_size"]
    else:
        usd_per_lot = p["contract_size"] * price
    return COMMISSION_RT_USD[p["asset"]] / usd_per_lot if usd_per_lot > 0 else 0.0


def round_trip_cost_frac(symbol: str, hl: str, hl_growth: bool, price_mt5: float,
                         mt5_spread_price: float, hl_half_spread_bps: float) -> float:
    """RT cost as fraction of notional: MT5 spread RT + commission RT + HL fees taker×2 + HL half-spread×2."""
    mt5_spread_frac = mt5_spread_price / price_mt5 if price_mt5 > 0 else 0.0
    # one RT = pay spread on entry and exit ≈ 2 * one-way spread; mt5_spread_price is ask-bid once
    mt5_rt_spread = 2.0 * mt5_spread_frac
    mt5_comm = mt5_commission_frac(symbol, price_mt5)  # already RT
    hl_fee = 2.0 * hl_fee_docs_correct(hl_growth, "taker")  # entry+exit taker
    hl_spr = 2.0 * (hl_half_spread_bps / 1e4)
    return mt5_rt_spread + mt5_comm + hl_fee + hl_spr


def probe_time_offset(symbol: str = "EURUSD", hl: str = "xyz:EUR") -> dict:
    """Compare gap std under offset hours {0,+2,+3}; pick lowest |median gap| then lowest std.
    Uses M1 bid mid vs HL close on overlapping labeled minutes after shifting MT5 timestamps BACK by offset
    (if MT5 server=UTC+2 labeled as UTC, true UTC = labeled - 2h).
    """
    mt5 = load_mt5_m1_bars(symbol)
    hl_df = load_hl_1m(hl)
    if mt5.empty or hl_df.empty:
        return {"chosen_offset_hours": 0, "reason": "missing_data", "candidates": []}
    p = pair_by_mt5(symbol)
    pts = mt5_spread_pts(symbol)
    mt5 = mt5.copy()
    mt5["mt5_mid"] = mt5["close"].astype(float) + 0.5 * pts * p["point"]
    candidates = []
    for off in (0, 2, 3):
        m = mt5[["time", "mt5_mid"]].copy()
        m["time"] = m["time"] - pd.Timedelta(hours=off)
        a = hl_df[["time", "hl_close"]].rename(columns={"hl_close": "hl_mid"})
        j = pd.merge(a, m, on="time", how="inner")
        if len(j) < 100:
            candidates.append({"offset_h": off, "n": len(j), "median_gap_bps": None, "std_gap_bps": None})
            continue
        gap = (j.hl_mid - j.mt5_mid) / j.mt5_mid * 1e4
        candidates.append({
            "offset_h": off, "n": int(len(j)),
            "median_gap_bps": float(gap.median()),
            "mean_gap_bps": float(gap.mean()),
            "std_gap_bps": float(gap.std()),
            "mae_gap_bps": float(gap.abs().mean()),
        })
    valid = [c for c in candidates if c["median_gap_bps"] is not None]
    if not valid:
        chosen = 0
        reason = "no_overlap"
    else:
        # prefer smallest MAE, then smallest |median|
        valid.sort(key=lambda c: (c["mae_gap_bps"], abs(c["median_gap_bps"])))
        chosen = valid[0]["offset_h"]
        reason = "min_mae_then_abs_median"
    # also check tick vs bar consistency at chosen offset
    return {"chosen_offset_hours": chosen, "reason": reason, "candidates": candidates}


def build_aligned(symbol: str, hl: str, offset_hours: int, hl_half_bps: float) -> pd.DataFrame:
    """Aligned concurrent minutes with tick-based MT5 mid/spread and HL close."""
    p = pair_by_mt5(symbol)
    hl_df = load_hl_1m(hl)
    if hl_df.empty:
        return pd.DataFrame()
    # load ticks covering HL window ± 1 day for offset
    start = hl_df.time.min() - pd.Timedelta(days=1)
    end = hl_df.time.max() + pd.Timedelta(days=1)
    ticks = load_ticks(symbol, start, end)
    if ticks.empty:
        return pd.DataFrame()
    # apply offset: if MT5 clock is ahead of UTC by offset_hours, subtract
    ticks = ticks.copy()
    ticks["time"] = ticks["time"] - pd.Timedelta(hours=offset_hours)
    minute = ticks_to_minute(ticks)
    a = hl_df.rename(columns={"hl_close": "hl_mid"})
    j = pd.merge(a, minute, on="time", how="inner")
    if j.empty:
        return pd.DataFrame()
    j = j.sort_values("time").reset_index(drop=True)
    j["gap"] = (j["hl_mid"] - j["mt5_mid"]) / j["mt5_mid"]
    j["gap_bps"] = j["gap"] * 1e4
    # rolling median of gap (prior 60 concurrent minutes — use shift so no lookahead)
    j["gap_med"] = j["gap"].rolling(60, min_periods=30).median().shift(1)
    j["hl_half_bps"] = float(hl_half_bps)
    j["rt_cost"] = [
        round_trip_cost_frac(symbol, hl, p["hl_growth"], float(mid), float(sp), float(hl_half_bps))
        for mid, sp in zip(j["mt5_mid"], j["mt5_spread"])
    ]
    j["rt_cost_bps"] = j["rt_cost"] * 1e4
    j["symbol"] = symbol
    j["hl"] = hl
    return j


def executable_mt5_price(ticks: pd.DataFrame, ts: pd.Timestamp, side: str, latency_s: float = 0.0) -> float | None:
    """side: 'buy' -> ask, 'sell' -> bid. Fill at first tick at/after ts+latency."""
    if ticks.empty:
        return None
    t0 = pd.Timestamp(ts)
    if t0.tzinfo is None:
        t0 = t0.tz_localize("UTC")
    else:
        t0 = t0.tz_convert("UTC")
    t0 = t0 + pd.Timedelta(seconds=latency_s)
    # ticks.time is already offset-adjusted by caller
    sub = ticks[ticks.time >= t0]
    if sub.empty:
        return None
    row = sub.iloc[0]
    return float(row["ask"] if side == "buy" else row["bid"])


def inventory_check() -> dict:
    m1_syms = sorted(p.stem.replace("_M1", "") for p in DATA_MT5_M1.glob("*_M1.parquet"))
    tick_files = list(DATA_MT5_TICKS.glob("*.parquet"))
    by_sym = {}
    for f in tick_files:
        sym = f.name.rsplit("_", 1)[0]
        by_sym.setdefault(sym, []).append(f.name)
    return {
        "m1_symbols": m1_syms,
        "tick_file_count": len(tick_files),
        "tick_files_per_symbol": {k: len(v) for k, v in sorted(by_sym.items())},
        "expected_tick_files_remote": 140,
    }
