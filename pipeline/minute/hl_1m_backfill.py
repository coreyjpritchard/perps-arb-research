"""Backfill Hyperliquid HIP-3 1-minute candles (public API, read-only).
HL candleSnapshot keeps only the most recent ~5000 candles (~83h), so run at least every 3 days.
Appends and de-duplicates into data/hl_1m/<coin>.parquet."""
import os
import time, json, urllib.request, pathlib, sys
import pandas as pd
URL = "https://api.hyperliquid.xyz/info"
COINS = ["xyz:EUR", "xyz:GBP", "xyz:JPY", "xyz:GOLD", "xyz:JP225", "xyz:SP500", "xyz:XYZ100"]
OUT = pathlib.Path(os.environ.get("PERPS_DATA", pathlib.Path(__file__).resolve().parents[2] / "data")) / "hl_1m"
def post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)
now = int(time.time() * 1000)
summary = []
for coin in COINS:
    try:
        rows = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m", "startTime": now - 5100 * 60_000, "endTime": now}})
    except Exception as e:
        summary.append(f"{coin}: ERROR {e}"); continue
    if not rows:
        summary.append(f"{coin}: no rows"); continue
    df = pd.DataFrame(rows).rename(columns={"t": "open_ms", "T": "close_ms", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trades"})
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
    df = df[["time", "open", "high", "low", "close", "volume", "trades"]]
    f = OUT / f"{coin.replace(':', '_')}.parquet"
    if f.exists():
        df = pd.concat([pd.read_parquet(f), df])
    df = df.drop_duplicates("time", keep="last").sort_values("time")
    # drop the still-forming last minute
    df = df[df["time"] < pd.Timestamp(now - 60_000, unit="ms", tz="UTC")]
    df.to_parquet(f, index=False)
    gaps = (df["time"].diff() > pd.Timedelta("1min")).sum()
    summary.append(f"{coin}: {len(df)} rows {df['time'].min()} -> {df['time'].max()} gaps>1m={gaps}")
    time.sleep(0.5)
print("\n".join(summary))
