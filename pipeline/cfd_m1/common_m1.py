"""Shared constants for minute-level HL HIP-3 vs prop-firm demo MT5 CFD research. Paper only."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "cfd"))

from common_cfd import (  # noqa: E402
    PAIRS, HL_FEES, NOTIONAL, COMMISSION_RT_USD, LEVERAGE_MT5, HL_MAX_LEV_FALLBACK,
    hl_fee_docs_correct, capital_both_legs, mt5_spread_pts, INV_SPREAD_PTS,
    LIVE_SPREAD_OVERRIDE_PTS, pair_by_mt5,
)

DATA_MT5_M1 = ROOT / "data" / "mt5_m1" / "m1"
DATA_MT5_TICKS = ROOT / "data" / "mt5_m1" / "ticks"
DATA_HL_1M = ROOT / "data" / "hl_1m"
DATA_AUX = ROOT / "data" / "hl_m1_aux"
DATA_LIVE = ROOT / "data" / "mt5" / "live_costs"
RESULTS = ROOT / "results" / "cfd_m1"

# Pre-registered strategy params (frozen in preregistration_cfd_m1.md)
K_GAP = 2.0
K_OPEN = 2.0
T_MAX_GAP = 30  # minutes
T_MAX_OPEN = 60
ROLL_MEDIAN = 60
ROLL_MEDIAN_MIN = 30
HL_HALF_SPREAD_FLOOR_BPS = 1.0  # if l2 missing or thinner
LATENCY_SECONDS = (0, 1, 2, 5)
NOTIONAL = NOTIONAL  # $10k

__all__ = [
    "ROOT", "PAIRS", "HL_FEES", "NOTIONAL", "COMMISSION_RT_USD", "LEVERAGE_MT5",
    "HL_MAX_LEV_FALLBACK", "hl_fee_docs_correct", "capital_both_legs", "mt5_spread_pts",
    "INV_SPREAD_PTS", "LIVE_SPREAD_OVERRIDE_PTS", "pair_by_mt5",
    "DATA_MT5_M1", "DATA_MT5_TICKS", "DATA_HL_1M", "DATA_AUX", "DATA_LIVE", "RESULTS",
    "K_GAP", "K_OPEN", "T_MAX_GAP", "T_MAX_OPEN", "ROLL_MEDIAN", "ROLL_MEDIAN_MIN",
    "HL_HALF_SPREAD_FLOOR_BPS", "LATENCY_SECONDS",
]
