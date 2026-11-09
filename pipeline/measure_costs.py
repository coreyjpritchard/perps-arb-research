"""Measure slippage ($10k/$100k per leg) from >=3 live book snapshots and leg-risk penalty (median |1m return|, HL 1m candles).
Writes ../data/cost_params.csv and prints a markdown table. Run BEFORE the backtest (pre-registered)."""
import time, os, pandas as pd, numpy as np
from common import COINS, hl
from snapshots import book_hl, book_bin, book_byb, book_stats

rows = []
for snap in range(3):
    ts = pd.Timestamp.now('UTC')
    for c in COINS:
        s = c + "USDT"
        for venue, fn in [("HL", lambda: book_hl(c)), ("BIN", lambda: book_bin(s)), ("BYB", lambda: book_byb(s)),
                          ("BINSPOT", lambda: book_bin(s, spot=True))]:
            try:
                st = book_stats(*fn()); st.update(coin=c, venue=venue, snap=snap, ts=ts); rows.append(st)
            except Exception as e:
                print("ERR", c, venue, e)
    if snap < 2: time.sleep(120)
df = pd.DataFrame(rows)
agg = df.groupby(["coin", "venue"])[["spread_bps", "slip_10k_bps", "slip_100k_bps", "depth_10bps_usd"]].mean()

legs = {}
now = int(time.time() * 1000)
for c in COINS:
    d = hl({"type": "candleSnapshot", "req": {"coin": c, "interval": "1m", "startTime": now - 3 * 86400_000, "endTime": now}})
    cl = pd.Series([float(x["c"]) for x in d])
    legs[c] = float(cl.pct_change().abs().median() * 1e4)
agg = agg.reset_index()
agg["leg_risk_bps"] = agg.coin.map(legs)
out = os.path.join(os.path.dirname(__file__), "..", "data")
df.to_csv(os.path.join(out, "book_snapshots_raw.csv"), index=False)
agg.to_csv(os.path.join(out, "cost_params.csv"), index=False)
print(f"Snapshots: {df.ts.min()} .. {df.ts.max()} (3 snapshots, 2 min apart); leg risk from HL 1m candles, last 3 days")
print(agg.round(2).to_string(index=False))
