"""Pull historical funding + 4h prices for HL, Binance USDT-M, Bybit linear, Binance spot.
Usage: python fetch_history.py [START_ISO] [END_ISO]
Writes parquet files to ../data/.
"""
import sys, os, pandas as pd
from common import hl, get, COINS, BIN_F, BIN_S, BYB

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA, exist_ok=True)
START = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2024-10-20", tz="UTC")
END = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-10-26", tz="UTC")
ms = lambda t: int(t.timestamp() * 1000)


def hl_funding(coin):
    out, t = [], ms(START)
    while t < ms(END):
        d = hl({"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": ms(END)})
        if not d: break
        out += d
        nt = d[-1]["time"] + 1
        if nt <= t or len(d) < 2: break
        t = nt
    df = pd.DataFrame(out).drop_duplicates("time")
    df["time"] = pd.to_datetime(df.time, unit="ms", utc=True)
    df["rate"] = df.fundingRate.astype(float); df["premium"] = df.premium.astype(float)
    return df[["time", "rate", "premium"]]


def hl_candles(coin, interval="4h"):
    d = hl({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                                                "startTime": ms(START), "endTime": ms(END)}})
    df = pd.DataFrame(d)
    df["close_time"] = pd.to_datetime(df["T"] + 1, unit="ms", utc=True)
    df["close"] = df.c.astype(float); df["volume"] = df.v.astype(float)
    return df[["close_time", "close", "volume"]]


def bin_funding(sym):
    out, t = [], ms(START)
    while t < ms(END):
        d = get(BIN_F + "/fapi/v1/fundingRate", {"symbol": sym, "startTime": t, "endTime": ms(END), "limit": 1000})
        if not d: break
        out += d; t = d[-1]["fundingTime"] + 1
        if len(d) < 1000: break
    df = pd.DataFrame(out).drop_duplicates("fundingTime")
    df["time"] = pd.to_datetime(df.fundingTime, unit="ms", utc=True); df["rate"] = df.fundingRate.astype(float)
    return df[["time", "rate"]]


def bin_klines(sym, spot=False, interval="4h"):
    base, path = (BIN_S, "/api/v3/klines") if spot else (BIN_F, "/fapi/v1/klines")
    out, t = [], ms(START)
    while t < ms(END):
        d = get(base + path, {"symbol": sym, "interval": interval, "startTime": t, "endTime": ms(END), "limit": 1000})
        if not d: break
        out += d; t = d[-1][6] + 1
        if len(d) < 1000: break
    df = pd.DataFrame(out).iloc[:, [6, 4, 7]]; df.columns = ["ct", "close", "qvol"]
    df["close_time"] = pd.to_datetime(df.ct + 1, unit="ms", utc=True)
    df["close"] = df.close.astype(float); df["volume"] = df.qvol.astype(float)
    return df[["close_time", "close", "volume"]].drop_duplicates("close_time")


def byb_funding(sym):
    out, end = [], ms(END)
    while end > ms(START):
        d = get(BYB + "/v5/market/funding/history", {"category": "linear", "symbol": sym,
                                                      "startTime": ms(START), "endTime": end, "limit": 200})["result"]["list"]
        if not d: break
        out += d
        mn = min(int(x["fundingRateTimestamp"]) for x in d)
        if mn >= end or len(d) < 200: break
        end = mn - 1
    df = pd.DataFrame(out)
    df["time"] = pd.to_datetime(df.fundingRateTimestamp.astype("int64"), unit="ms", utc=True)
    df["rate"] = df.fundingRate.astype(float)
    return df[["time", "rate"]].drop_duplicates("time").sort_values("time")


def byb_klines(sym, interval="240"):
    out, end = [], ms(END)
    while end > ms(START):
        d = get(BYB + "/v5/market/kline", {"category": "linear", "symbol": sym, "interval": interval,
                                            "start": ms(START), "end": end, "limit": 1000})["result"]["list"]
        if not d: break
        out += d
        mn = min(int(x[0]) for x in d)
        if mn >= end or len(d) < 1000: break
        end = mn - 1
    df = pd.DataFrame(out, columns=["t", "o", "h", "l", "c", "v", "turnover"])
    df["close_time"] = pd.to_datetime(df.t.astype("int64") + 4 * 3600 * 1000, unit="ms", utc=True)
    df["close"] = df.c.astype(float); df["volume"] = df.turnover.astype(float)
    return df[["close_time", "close", "volume"]].drop_duplicates("close_time").sort_values("close_time")


def save(df, name):
    p = os.path.join(DATA, name + ".parquet"); df.reset_index(drop=True).to_parquet(p)
    first = df.iloc[0, 0] if len(df) else None; last = df.iloc[-1, 0] if len(df) else None
    print(f"{name:28s} rows={len(df):6d} {first} -> {last}", flush=True)


if __name__ == "__main__":
    for c in COINS:
        sym = c + "USDT"
        for name, fn in [(f"hl_funding_{c}", lambda: hl_funding(c)), (f"hl_px4h_{c}", lambda: hl_candles(c)),
                         (f"bin_funding_{c}", lambda: bin_funding(sym)), (f"bin_px4h_{c}", lambda: bin_klines(sym)),
                         (f"binspot_px4h_{c}", lambda: bin_klines(sym, spot=True)),
                         (f"byb_funding_{c}", lambda: byb_funding(sym)), (f"byb_px4h_{c}", lambda: byb_klines(sym))]:
            try:
                save(fn(), name)
            except Exception as e:
                print(f"{name}: ERROR {e}", flush=True)
