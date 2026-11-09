"""Background l2Book snapshots for HIP-3 coins. Public API, read-only. Paper research."""
from __future__ import annotations
import os
import json, time, urllib.request, pathlib, csv, sys
from datetime import datetime, timezone

URL = "https://api.hyperliquid.xyz/info"
COINS = ["xyz:EUR","xyz:GBP","xyz:JPY","xyz:GOLD","xyz:JP225","xyz:SP500","xyz:XYZ100"]
OUT = pathlib.Path(os.environ.get("PERPS_DATA", pathlib.Path(__file__).resolve().parents[2] / "data")) / "hl_m1_aux/l2book"
OUT.mkdir(parents=True, exist_ok=True)
CSV = OUT / "l2_snapshots.csv"
INTERVAL_S = 60  # one snapshot set per minute
DURATION_S = int(sys.argv[1]) if len(sys.argv) > 1 else 3 * 3600  # default 3h
NOTIONAL = 10_000.0

def post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def book_stats(coin: str):
    data = post({"type":"l2Book","coin":coin})
    levels = data.get("levels") or []
    if len(levels) < 2:
        return None
    bids, asks = levels[0], levels[1]
    if not bids or not asks:
        return None
    best_bid = float(bids[0]["px"]); best_ask = float(asks[0]["px"])
    mid = 0.5 * (best_bid + best_ask)
    half_spread_bps = (best_ask - best_bid) / mid * 1e4 / 2.0
    # depth to NOTIONAL on each side (approx size*px)
    def depth_usd(side):
        acc = 0.0
        for lvl in side:
            px = float(lvl["px"]); sz = float(lvl["sz"])
            acc += px * sz
            if acc >= NOTIONAL:
                return acc
        return acc
    return {
        "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
        "half_spread_bps": half_spread_bps,
        "bid_depth_usd": depth_usd(bids), "ask_depth_usd": depth_usd(asks),
        "n_bid_levels": len(bids), "n_ask_levels": len(asks),
    }

fields = ["ts_utc","coin","best_bid","best_ask","mid","half_spread_bps","bid_depth_usd","ask_depth_usd","n_bid_levels","n_ask_levels","error"]
new = not CSV.exists()
t_end = time.time() + DURATION_S
n = 0
with CSV.open("a", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    if new:
        w.writeheader()
    while time.time() < t_end:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for coin in COINS:
            row = {"ts_utc": ts, "coin": coin, "error": ""}
            try:
                st = book_stats(coin)
                if st is None:
                    row["error"] = "empty_book"
                else:
                    row.update(st)
            except Exception as e:
                row["error"] = str(e)[:120]
            w.writerow(row)
            f.flush()
            time.sleep(0.25)
        n += 1
        # sleep remainder of minute
        time.sleep(max(0.0, INTERVAL_S - 0.25*len(COINS)))
print(f"collected {n} rounds -> {CSV}", flush=True)
