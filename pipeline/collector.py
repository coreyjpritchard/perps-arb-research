"""One-shot snapshot collector (run hourly later, e.g. manually or by a scheduler you set up yourself; none is installed).
Captures for each coin: HL funding/premium/mark/oracle/OI (metaAndAssetCtxs), HL predictedFundings (HL + Binance + Bybit
predicted rates as HL reports them), Binance premiumIndex (last + next funding), Bybit tickers (funding, next time),
and top-of-book + $10k/$100k slippage on all three perp venues. Appends to ../data/collector/snapshots_YYYYMMDD.csv.
Usage: python collector.py
"""
import os, json, pandas as pd
from common import hl, get, COINS, BIN_F, BYB
from snapshots import book_hl, book_bin, book_byb, book_stats

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "collector")


def main():
    os.makedirs(OUT, exist_ok=True)
    ts = pd.Timestamp.now('UTC')
    meta, ctxs = hl({"type": "metaAndAssetCtxs"})
    hlctx = {u["name"]: x for u, x in zip(meta["universe"], ctxs)}
    pred = {}
    for coin, venues in hl({"type": "predictedFundings"}):
        for vname, v in venues:
            if v: pred[(coin, vname)] = (float(v["fundingRate"]), v.get("nextFundingTime"), v.get("fundingIntervalHours"))
    rows = []
    for c in COINS:
        s = c + "USDT"
        x = hlctx.get(c, {})
        bp = get(BIN_F + "/fapi/v1/premiumIndex", {"symbol": s})
        bt = get(BYB + "/v5/market/tickers", {"category": "linear", "symbol": s})["result"]["list"][0]
        base = {"ts": ts, "coin": c,
                "hl_funding": float(x.get("funding", "nan")), "hl_premium": float(x.get("premium") or "nan"),
                "hl_mark": float(x.get("markPx", "nan")), "hl_oracle": float(x.get("oraclePx", "nan")),
                "hl_oi": float(x.get("openInterest", "nan")), "hl_day_ntl_vlm": float(x.get("dayNtlVlm", "nan")),
                "bin_last_funding": float(bp["lastFundingRate"]), "bin_next_funding_time": bp["nextFundingTime"],
                "bin_mark": float(bp["markPrice"]), "bin_index": float(bp["indexPrice"]),
                "byb_funding": float(bt["fundingRate"]), "byb_next_funding_time": bt["nextFundingTime"],
                "byb_mark": float(bt["markPrice"]), "byb_index": float(bt["indexPrice"])}
        for (pc, vn), (r, nft, ih) in pred.items():
            if pc == c:
                base[f"pred_{vn}_rate"] = r; base[f"pred_{vn}_interval_h"] = ih; base[f"pred_{vn}_next"] = nft
        for venue, fn in [("hl", lambda: book_hl(c)), ("bin", lambda: book_bin(s)), ("byb", lambda: book_byb(s))]:
            try:
                bids, asks = fn(); st = book_stats(bids, asks)
                base[f"{venue}_bid"], base[f"{venue}_ask"] = bids[0][0], asks[0][0]
                for k, v in st.items(): base[f"{venue}_{k}"] = v
            except Exception as e:
                base[f"{venue}_error"] = str(e)[:200]
        rows.append(base)
    df = pd.DataFrame(rows)
    p = os.path.join(OUT, f"snapshots_{ts:%Y%m%d}.csv")
    df.to_csv(p, mode="a", header=not os.path.exists(p), index=False)
    print(f"wrote {len(df)} rows to {p}")
    print(df[["coin", "hl_funding", "bin_last_funding", "byb_funding"] + [c for c in df.columns if c.startswith("pred_") and c.endswith("_rate")]].to_string(index=False))


if __name__ == "__main__":
    main()
