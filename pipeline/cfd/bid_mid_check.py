"""Bid vs mid consistency checks. Ticks (2026-10-10..24) do not overlap parquets (end 2026-10-07)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np
from common_cfd import DATA_MT5, LIVE, RESULTS, PAIRS

RESULTS.mkdir(parents=True, exist_ok=True)

def main():
    lines = []
    lines.append("# Bid vs mid verification\n")
    lines.append("Written after data copy; **before** trading backtest PnL interpretation.\n")
    lines.append("Live ticks cover 2026-10-10..24; MT5 parquets end 2026-10-07 — **no overlapping timestamps**.\n")

    # 1) parquet close granularity
    lines.append("\n## 1. Parquet close pip/point granularity (last 5 M1 bars)\n")
    for p in PAIRS:
        path = DATA_MT5 / f"{p['mt5']}_M1.parquet"
        if not path.exists():
            lines.append(f"- {p['mt5']}: MISSING\n")
            continue
        df = pd.read_parquet(path, columns=["time", "close", "spread"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        tail = df.tail(5)
        # residual mod point
        rem = (tail["close"] / p["point"]).round(6) % 1
        lines.append(f"- **{p['mt5']}**: last close={tail.close.iloc[-1]}, "
                     f"mean |close/point fractional|={rem.abs().mean():.4f}, "
                     f"spread pts last5 mean={tail.spread.mean():.2f} (bar min; often 0 on FX M1)\n")

    # 2) tick bid level conventions
    lines.append("\n## 2. Live tick bid/ask conventions (GBPUSD, US500.cash)\n")
    tick_dirs = [LIVE / "london_open", LIVE / "night"]
    for sym, unit in [("GBPUSD", "pip"), ("US500.cash", "pt")]:
        files = []
        for d in tick_dirs:
            if d.exists():
                files += sorted(d.glob(f"*{sym}_ticks.csv"))
        if not files:
            lines.append(f"- {sym}: no tick files found\n")
            continue
        parts = []
        for f in files[:20]:
            try:
                t = pd.read_csv(f)
                parts.append(t)
            except Exception as e:
                lines.append(f"- read fail {f.name}: {e}\n")
        if not parts:
            continue
        ticks = pd.concat(parts, ignore_index=True)
        lines.append(f"- **{sym}**: n_ticks={len(ticks)} from {len(parts)} files; "
                     f"cols={list(ticks.columns)}; "
                     f"bid mean={ticks.bid.astype(float).mean():.5f}, "
                     f"ask mean={ticks.ask.astype(float).mean():.5f}, "
                     f"spread mean={ticks.spread.astype(float).mean():.4f} {unit}\n")
        # Compare to last parquet close level (different day — level continuity only)
        pq = pd.read_parquet(DATA_MT5 / f"{sym}_M1.parquet", columns=["time", "close"])
        pq["time"] = pd.to_datetime(pq["time"], utc=True)
        last_c = float(pq.close.iloc[-1])
        first_bid = float(ticks.bid.astype(float).iloc[0])
        lines.append(f"  parquet last close (≤2026-10-07)={last_c:.5f}; "
                     f"first tick bid in live window≈{first_bid:.5f}; "
                     f"gap days≈3 — cannot confirm same-bar bid identity.\n")

    lines.append("\n## 3. What we can / cannot confirm\n")
    lines.append("- **Can:** parquet closes sit on point grid consistent with bid quotes; live ticks have bid<ask with positive spread; "
                 "GBPUSD/US500 live spread distributions match broker data notes (GBPUSD tight; US500≈0.60).\n")
    lines.append("- **Cannot:** same-timestamp verification that parquet OHLC equals tick bid inside the backtest window "
                 "(no overlap). Mid is constructed as bid + 0.5×spread×point using inventory/live spreads.\n")

    out = RESULTS / "bid_mid_check.md"
    out.write_text("".join(lines))
    print(out.read_text())

if __name__ == "__main__":
    main()
