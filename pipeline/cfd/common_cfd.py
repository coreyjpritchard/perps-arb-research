"""Shared constants for HL HIP-3 vs prop-firm demo MT5 CFD research. Paper only."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_MT5 = ROOT / "data" / "mt5"
DATA_HL = ROOT / "data" / "hl_hip3"
RESULTS = ROOT / "results" / "cfd"
LIVE = DATA_MT5 / "live_costs"
INV = DATA_MT5 / "inventory"

# HL coin -> MT5 symbol
PAIRS = [
    {"hl": "xyz:EUR", "mt5": "EURUSD", "asset": "fx", "hl_growth": True, "point": 1e-5, "digits": 5, "contract_size": 100_000.0, "pip_size": 1e-4},
    {"hl": "xyz:GBP", "mt5": "GBPUSD", "asset": "fx", "hl_growth": True, "point": 1e-5, "digits": 5, "contract_size": 100_000.0, "pip_size": 1e-4},
    {"hl": "xyz:JPY", "mt5": "USDJPY", "asset": "fx", "hl_growth": True, "point": 1e-3, "digits": 3, "contract_size": 100_000.0, "pip_size": 1e-2},
    {"hl": "xyz:GOLD", "mt5": "XAUUSD", "asset": "metal", "hl_growth": False, "point": 1e-2, "digits": 2, "contract_size": 100.0, "pip_size": 1e-2},
    {"hl": "xyz:JP225", "mt5": "JP225.cash", "asset": "index", "hl_growth": True, "point": 1e-2, "digits": 2, "contract_size": 10.0, "pip_size": 1.0},
    {"hl": "xyz:SP500", "mt5": "US500.cash", "asset": "index", "hl_growth": True, "point": 1e-2, "digits": 2, "contract_size": 1.0, "pip_size": 1.0},
    {"hl": "xyz:XYZ100", "mt5": "US100.cash", "asset": "index", "hl_growth": True, "point": 1e-2, "digits": 2, "contract_size": 1.0, "pip_size": 1.0},
]

# INVENTORY liquid 90d mean spreads (points) — prefer over bad snapshot ticks
INV_SPREAD_PTS = {
    "EURUSD": 0.1,
    "GBPUSD": 2.0,
    "USDJPY": 3.1,
    "XAUUSD": 40.5,
    "JP225.cash": 1000.0,  # inventory mean blank; swaps_snapshot spread_pts_now=1000 (=10.0 index pts)
    "US500.cash": 60.0,
    "US100.cash": 146.3,
    "US30.cash": 210.0,
}
# Measured live preferred overrides (all-in notes from broker data notes)
LIVE_SPREAD_OVERRIDE_PTS = {
    # GBPUSD all-in ~0.8 pip at London midday = 8 points (point=1e-5, pip=10 points)
    # But broker data notes say median 0.3 pip London open; all-in 0.8 pip including commission.
    # For spread-only charge we use 0.3 pip = 3 points as live midday-ish; commission separate.
    "GBPUSD": 3.0,  # ~0.3 pip live median London open; commission added separately
    "US500.cash": 60.0,  # fixed 0.60 pt = 60 points
}

# Commission USD per lot round-trip
COMMISSION_RT_USD = {"fx": 5.0, "metal": 5.0, "index": 0.0}

# HL fees tier 0
HL_FEES = {
    "growth": {"taker": 0.000090, "maker": 0.000030},   # 0.0090% / 0.0030%
    "standard": {"taker": 0.00090, "maker": 0.00030},  # 0.090% / 0.030%
}

NOTIONAL = 10_000.0
# prop-firm-style leverage assumptions (conservative research defaults; state in results)
LEVERAGE_MT5 = {"fx": 100.0, "metal": 100.0, "index": 100.0}
# HL max lev from meta used at runtime; fallback:
HL_MAX_LEV_FALLBACK = {"xyz:EUR": 50, "xyz:GBP": 50, "xyz:JPY": 50, "xyz:GOLD": 25,
                       "xyz:JP225": 20, "xyz:SP500": 50, "xyz:XYZ100": 30}

MT5_END = "2026-10-07 23:59:59+00:00"
HL_INFO = "https://api.hyperliquid.xyz/info"


def pair_by_mt5(sym: str):
    for p in PAIRS:
        if p["mt5"] == sym:
            return p
    return None


def hl_fee_docs_correct(hl_growth: bool, side: str = "taker") -> float:
    sched = "growth" if hl_growth else "standard"
    return HL_FEES[sched][side]


def mt5_spread_pts(symbol: str) -> float:
    if symbol in LIVE_SPREAD_OVERRIDE_PTS:
        return LIVE_SPREAD_OVERRIDE_PTS[symbol]
    return INV_SPREAD_PTS[symbol]


def mt5_mid_from_bid(bid: float, symbol: str) -> float:
    p = pair_by_mt5(symbol)
    pts = mt5_spread_pts(symbol)
    return bid + 0.5 * pts * p["point"]


def mt5_rt_cost_frac(symbol: str, price: float) -> float:
    """Round-trip MT5 cost as fraction of notional: one spread + commission."""
    p = pair_by_mt5(symbol)
    spread_price = mt5_spread_pts(symbol) * p["point"]
    spread_frac = spread_price / price
    # commission: $5/lot RT for fx/metal. Lots for notional N: N / (contract_size * price) for FX?
    # Standard: 1 lot FX = 100_000 units base; notional USD ≈ contract_size * price for XXXUSD,
    # for USDJPY notional USD ≈ contract_size (quote is JPY) — use N-based: commission_per_usd = 5 / (contract_size * price) * price... 
    # For EURUSD: 1 lot controls 100k EUR ≈ 100k*price USD. commission $5 RT / (100k*price) fraction.
    # For USDJPY: 1 lot = 100k USD, commission $5 / 100k.
    # For XAUUSD: 1 lot = 100 oz * price USD.
    # For indices contract_size 1 or 10: PnL per point * contract; treat notional ≈ price * contract_size for 1 lot.
    if p["asset"] == "fx" and symbol == "USDJPY":
        usd_per_lot = p["contract_size"]  # 100k USD
    else:
        usd_per_lot = p["contract_size"] * price
    comm_frac = COMMISSION_RT_USD[p["asset"]] / usd_per_lot if usd_per_lot > 0 else 0.0
    return spread_frac + comm_frac


def capital_both_legs(hl: str, asset: str, notional: float = NOTIONAL, hl_max_lev: float | None = None) -> float:
    mt5_lev = LEVERAGE_MT5[asset]
    hl_lev = hl_max_lev or HL_MAX_LEV_FALLBACK.get(hl, 20)
    return notional / mt5_lev + notional / hl_lev
