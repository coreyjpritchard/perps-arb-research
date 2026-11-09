"""Maintenance margin rates documented in preregistration_v2.md (fetched 2026-10-27)."""
HL_MMR = {
    "BTC": 0.0125, "ETH": 0.02, "SOL": 0.025, "XRP": 0.025,
    "DOGE": 0.05, "SUI": 0.05, "LINK": 0.05, "AVAX": 0.05, "HYPE": 0.05,
}
# Binance tier-1; for N above tier1_cap use next_mmr if set else max(tier1, 0.01)
BIN_MMR = {
    "BTC":  {"mmr": 0.0040, "cap": 300_000, "next_mmr": 0.0050},
    "ETH":  {"mmr": 0.0040, "cap": 300_000, "next_mmr": 0.0050},
    "SOL":  {"mmr": 0.0050, "cap": 50_000,  "next_mmr": 0.0065},
    "XRP":  {"mmr": 0.0050, "cap": 40_000,  "next_mmr": 0.0100},
    "DOGE": {"mmr": 0.0065, "cap": 80_000,  "next_mmr": 0.0100},
    "SUI":  {"mmr": 0.0100, "cap": 20_000,  "next_mmr": 0.0100},
    "LINK": {"mmr": 0.0050, "cap": 10_000,  "next_mmr": 0.0100},
    "AVAX": {"mmr": 0.0050, "cap": 25_000,  "next_mmr": 0.0100},
    "HYPE": {"mmr": 0.0100, "cap": 20_000,  "next_mmr": 0.0100},
}
BIN_LIQ_FEE = 0.00015  # 0.015% of notional

def bin_mmr(coin: str, notional: float) -> float:
    t = BIN_MMR[coin]
    if notional <= t["cap"]:
        return t["mmr"]
    return t.get("next_mmr", max(t["mmr"], 0.01))

def hl_mmr(coin: str, notional: float = 0.0) -> float:
    return HL_MMR[coin]
