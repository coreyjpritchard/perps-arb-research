"""Download Binance 1m markPriceKlines and spot klines from data.binance.vision."""
from __future__ import annotations
import io, sys, zipfile, time
from pathlib import Path
import urllib.request
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_MARK = ROOT / "data" / "binance_1m" / "mark"
OUT_SPOT = ROOT / "data" / "binance_1m" / "spot"
RAW = ROOT / "data" / "binance_1m" / "raw"
for d in (OUT_MARK, OUT_SPOT, RAW):
    d.mkdir(parents=True, exist_ok=True)

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX", "HYPE"]
MONTHS = [f"{y}-{m:02d}" for y, m in
          [(2024, m) for m in range(11, 13)] +
          [(2025, m) for m in range(1, 13)] +
          [(2026, m) for m in range(1, 11)]]


def fetch_zip(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except Exception as e:
        print(f"  FAIL {url}: {e}", flush=True)
        return None


def parse_klines(blob: bytes) -> pd.DataFrame:
    frames = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            with zf.open(name) as f:
                peek = f.read(32).decode("utf-8", errors="ignore")
                f.seek(0)
                if peek.startswith("open_time"):
                    df = pd.read_csv(f)
                else:
                    df = pd.read_csv(f, header=None)
                    cols = ["open_time", "open", "high", "low", "close", "volume",
                            "close_time", "quote_volume", "count", "taker_buy_volume",
                            "taker_buy_quote_volume", "ignore"]
                    df.columns = cols[: df.shape[1]]
                frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    unit = "us" if ot.median() > 1e14 else "ms"
    df["time"] = pd.to_datetime(ot, unit=unit, utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[["time", "open", "high", "low", "close"]].dropna()
    df = df[(df.time >= "2024-10-01") & (df.time < "2026-11-01")]
    return df.sort_values("time")


def month_urls(kind: str, coin: str, ym: str) -> list[str]:
    sym = f"{coin}USDT"
    if kind == "mark":
        monthly = f"https://data.binance.vision/data/futures/um/monthly/markPriceKlines/{sym}/1m/{sym}-1m-{ym}.zip"
        daily_base = f"https://data.binance.vision/data/futures/um/daily/markPriceKlines/{sym}/1m/"
    else:
        monthly = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/1m/{sym}-1m-{ym}.zip"
        daily_base = f"https://data.binance.vision/data/spot/daily/klines/{sym}/1m/"
    if ym != "2026-10":
        return [monthly]
    return [f"{daily_base}{sym}-1m-{ym}-{d:02d}.zip" for d in range(1, 27)]


def load_coin(kind: str, coin: str) -> pd.DataFrame:
    out_dir = OUT_MARK if kind == "mark" else OUT_SPOT
    parts = []
    for ym in MONTHS:
        if coin == "HYPE" and ym < "2025-05":
            continue
        for url in month_urls(kind, coin, ym):
            cache = RAW / f"{kind}_{coin}_{Path(url).name}"
            if cache.exists() and cache.stat().st_size > 100:
                blob = cache.read_bytes()
            else:
                print(f"fetch {kind} {coin} {Path(url).name}", flush=True)
                blob = fetch_zip(url)
                if blob is None:
                    continue
                cache.write_bytes(blob)
                time.sleep(0.1)
            try:
                df = parse_klines(blob)
            except Exception as e:
                print(f"  parse fail {cache.name}: {e}", flush=True)
                continue
            if len(df):
                parts.append(df)
    if not parts:
        print(f"NO DATA {kind} {coin}", flush=True)
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    path = out_dir / f"{coin}.parquet"
    df.to_parquet(path, index=False)
    print(f"Wrote {path} rows={len(df)} {df.time.iloc[0]} .. {df.time.iloc[-1]}", flush=True)
    return df


def main():
    kinds = sys.argv[1:] or ["mark", "spot"]
    for kind in kinds:
        for coin in COINS:
            load_coin(kind, coin)


if __name__ == "__main__":
    main()
