"""Load and align MT5 + HL series for the overlap window."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import numpy as np
from common_cfd import PAIRS, DATA_MT5, DATA_HL, LIVE, mt5_spread_pts, INV_SPREAD_PTS

def load_swaps() -> pd.DataFrame:
    path = LIVE / "swaps_snapshot_2026-10-27.csv"
    df = pd.read_csv(path)
    return df

def load_mt5_m1(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    path = DATA_MT5 / f"{symbol}_M1.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["time", "bid_close", "mid", "spread_pts_used", "open", "high", "low", "tick_volume"])
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df[(df.time >= start) & (df.time <= end)].copy()
    pts = mt5_spread_pts(symbol)
    # Prefer bar spread when > 0, else inventory/live override
    point = {p["mt5"]: p["point"] for p in PAIRS}[symbol]
    bar_spread = df["spread"].astype(float)
    use = np.where(bar_spread > 0, bar_spread, pts)
    df["bid_close"] = df["close"].astype(float)
    df["mid"] = df["bid_close"] + 0.5 * use * point
    df["spread_pts_used"] = use
    return df[["time", "bid_close", "mid", "spread_pts_used", "open", "high", "low", "tick_volume"]].reset_index(drop=True)

def load_mt5_h1(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    path = DATA_MT5 / f"{symbol}_H1.parquet"
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df[(df.time >= start) & (df.time <= end)].copy()
    pts = mt5_spread_pts(symbol)
    point = {p["mt5"]: p["point"] for p in PAIRS}[symbol]
    bar_spread = df["spread"].astype(float) if "spread" in df.columns else pd.Series(pts, index=df.index)
    use = np.where(bar_spread > 0, bar_spread, pts)
    df["bid_close"] = df["close"].astype(float)
    df["mid"] = df["bid_close"] + 0.5 * use * point
    return df[["time", "bid_close", "mid"]].reset_index(drop=True)

def load_hl_candles(coin: str, interval: str = "1m") -> pd.DataFrame:
    path = DATA_HL / f"candles_{coin.replace(':', '_')}_{interval}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["time", "close", "mid"])
    df = pd.read_parquet(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["mid"] = df["close"].astype(float)  # HL candle close ≈ tradeable mid proxy
    return df

def load_hl_funding(coin: str) -> pd.DataFrame:
    path = DATA_HL / f"funding_{coin.replace(':', '_')}.json"
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["rate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    return df[["time", "rate", "premium"]].sort_values("time").reset_index(drop=True)

def funding_start(coin: str) -> pd.Timestamp:
    df = load_hl_funding(coin)
    return df.time.iloc[0]

def align_m1(hl: str, mt5: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    a = load_hl_candles(hl, "1m")
    b = load_mt5_m1(mt5, start, end)
    if a.empty or b.empty:
        return pd.DataFrame()
    a = a[(a.time >= start) & (a.time <= end)][["time", "mid"]].rename(columns={"mid": "hl_mid"})
    b = b.rename(columns={"mid": "mt5_mid", "bid_close": "mt5_bid"})
    # HL candle open time vs MT5 bar time: both as minute labels; inner join
    m = pd.merge(a, b, on="time", how="inner")
    m["gap"] = (m.hl_mid - m.mt5_mid) / m.mt5_mid
    m["gap_bps"] = m.gap * 1e4
    return m

def align_h1(hl: str, mt5: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    a = load_hl_candles(hl, "1h")
    b = load_mt5_h1(mt5, start, end)
    if a.empty or b.empty:
        return pd.DataFrame()
    a = a[(a.time >= start) & (a.time <= end)][["time", "mid"]].rename(columns={"mid": "hl_mid"})
    b = b.rename(columns={"mid": "mt5_mid", "bid_close": "mt5_bid"})
    m = pd.merge(a, b, on="time", how="inner")
    m["gap"] = (m.hl_mid - m.mt5_mid) / m.mt5_mid
    m["gap_bps"] = m.gap * 1e4
    return m
