"""Order-book / funding snapshot helpers for HL, Binance USDT-M, Bybit linear, Binance spot (public endpoints)."""
from common import hl, get, BIN_F, BIN_S, BYB


def book_hl(coin):
    lv = hl({"type": "l2Book", "coin": coin}, sleep=0.2)["levels"]
    return ([(float(x["px"]), float(x["sz"])) for x in lv[0]], [(float(x["px"]), float(x["sz"])) for x in lv[1]])


def book_bin(sym, spot=False):
    d = get((BIN_S + "/api/v3/depth") if spot else (BIN_F + "/fapi/v1/depth"), {"symbol": sym, "limit": 500 if spot else 1000}, sleep=0.2)
    return ([(float(p), float(q)) for p, q in d["bids"]], [(float(p), float(q)) for p, q in d["asks"]])


def book_byb(sym):
    d = get(BYB + "/v5/market/orderbook", {"category": "linear", "symbol": sym, "limit": 500}, sleep=0.2)["result"]
    return ([(float(p), float(q)) for p, q in d["b"]], [(float(p), float(q)) for p, q in d["a"]])


def impact(levels, mid, usd):
    """VWAP cost vs mid (fraction) for a market order of `usd` notional walking `levels`. None if book too thin."""
    rem, cost_px_qty, qty = usd, 0.0, 0.0
    for px, sz in levels:
        take = min(rem, px * sz)
        q = take / px; cost_px_qty += px * q; qty += q; rem -= take
        if rem <= 1e-9: break
    if rem > 1e-6: return None
    vwap = cost_px_qty / qty
    return abs(vwap - mid) / mid


def book_stats(bids, asks, sizes=(10_000, 100_000)):
    mid = (bids[0][0] + asks[0][0]) / 2
    out = {"mid": mid, "spread_bps": (asks[0][0] - bids[0][0]) / mid * 1e4}
    for s in sizes:
        b, a = impact(bids, mid, s), impact(asks, mid, s)
        out[f"slip_{s//1000}k_bps"] = None if (a is None or b is None) else (a + b) / 2 * 1e4
    out["depth_10bps_usd"] = sum(p * q for p, q in bids if p >= mid * 0.999) + sum(p * q for p, q in asks if p <= mid * 1.001)
    return out
