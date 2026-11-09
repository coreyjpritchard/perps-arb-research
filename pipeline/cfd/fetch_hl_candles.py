"""Fetch HL HIP-3 candles. Walk backward in ~5000-candle windows (API truncates)."""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "hl_hip3"
OUT.mkdir(parents=True, exist_ok=True)
HL = "https://api.hyperliquid.xyz/info"
PAIRS = ["xyz:EUR", "xyz:GBP", "xyz:JPY", "xyz:GOLD", "xyz:JP225", "xyz:SP500", "xyz:XYZ100"]
S = requests.Session()
S.headers["User-Agent"] = "perps-arb-research/0.1"
STEP = {"1m": 60_000, "1h": 3_600_000, "1d": 86_400_000}


def hl(body, sleep=0.35):
    for attempt in range(6):
        r = S.post(HL, json=body, timeout=60)
        if r.status_code in (429, 418) or r.status_code >= 500:
            time.sleep(2 ** attempt + 1)
            continue
        r.raise_for_status()
        time.sleep(sleep)
        return r.json()
    raise RuntimeError(body)


def fetch_candles_back(coin: str, interval: str, earliest_ms: int, end_ms: int) -> pd.DataFrame:
    """Page backward: each call returns up to ~5000 candles ending near end_ms."""
    rows = []
    cursor_end = end_ms
    seen = set()
    for _ in range(200):
        d = hl({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval,
            "startTime": earliest_ms, "endTime": cursor_end
        }})
        if not d:
            break
        new = 0
        for x in d:
            if x["t"] not in seen:
                seen.add(x["t"])
                rows.append(x)
                new += 1
        first_t = min(x["t"] for x in d)
        print(f"  {coin} {interval} chunk n={len(d)} new={new} first={pd.Timestamp(first_t, unit='ms', tz='UTC')} total={len(rows)}", flush=True)
        if first_t <= earliest_ms or new == 0:
            break
        # move end to just before first candle of this chunk
        cursor_end = first_t - 1
        if cursor_end <= earliest_ms:
            break
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates("t")
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    for c in ["o", "h", "l", "c"]:
        df[c] = df[c].astype(float)
    df["volume"] = df["v"].astype(float)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})
    return df[["time", "open", "high", "low", "close", "volume"]].sort_values("time").reset_index(drop=True)


def main():
    end = int(pd.Timestamp("2026-10-27", tz="UTC").timestamp() * 1000)
    earliest = int(pd.Timestamp("2025-10-01", tz="UTC").timestamp() * 1000)
    summary = []
    for coin in PAIRS:
        for interval in ("1h", "1m"):
            # 1m: only need what overlaps MT5 — but MT5 ends 2026-10-07, so try from Sep 2026
            e0 = earliest if interval == "1h" else int(pd.Timestamp("2026-09-01", tz="UTC").timestamp() * 1000)
            df = fetch_candles_back(coin, interval, e0, end)
            path = OUT / f"candles_{coin.replace(':', '_')}_{interval}.parquet"
            if len(df):
                df.to_parquet(path, index=False)
            summary.append({
                "coin": coin, "interval": interval, "n": len(df),
                "start": str(df.time.iloc[0]) if len(df) else None,
                "end": str(df.time.iloc[-1]) if len(df) else None,
            })
            print(coin, interval, "FINAL", len(df),
                  df.time.iloc[0] if len(df) else None,
                  df.time.iloc[-1] if len(df) else None, flush=True)
    pd.DataFrame(summary).to_csv(OUT / "candle_coverage.csv", index=False)
    print("wrote", OUT / "candle_coverage.csv")


if __name__ == "__main__":
    main()
