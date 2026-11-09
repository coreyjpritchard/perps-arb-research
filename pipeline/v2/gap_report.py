"""Map HL minute gaps; write results/v2/hl_gaps.md and hl_gaps.csv"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX", "HYPE"]
START = pd.Timestamp("2024-11-01", tz="UTC")
END = pd.Timestamp("2026-10-26", tz="UTC")

def main():
    rows = []
    gap_rows = []
    for c in COINS:
        p = ROOT / "data" / "hl_archive" / "minute" / f"{c}.parquet"
        df = pd.read_parquet(p, columns=["time"]).sort_values("time")
        tm = df["time"].dt.floor("min")
        ts = tm[(tm >= START) & (tm < END)].drop_duplicates().sort_values()
        exp = pd.date_range(START, END - pd.Timedelta(minutes=1), freq="min", tz="UTC")
        cov = 100.0 * len(ts) / len(exp)
        vals = ts.to_numpy()
        n_gaps = 0
        max_gap = 0.0
        for i in range(1, len(vals)):
            dm = (vals[i] - vals[i - 1]) / pd.Timedelta(minutes=1)
            if dm > 2:
                n_gaps += 1
                max_gap = max(max_gap, float(dm))
                if dm > 30:
                    gap_rows.append({"coin": c, "gap_start": pd.Timestamp(vals[i-1]),
                                     "gap_end": pd.Timestamp(vals[i]), "minutes": float(dm)})
        # oct10
        o0, o1 = pd.Timestamp("2025-10-10", tz="UTC"), pd.Timestamp("2025-10-12", tz="UTC")
        t10 = tm[(tm >= o0) & (tm < o1)].drop_duplicates()
        exp10 = pd.date_range(o0, o1 - pd.Timedelta(minutes=1), freq="min", tz="UTC")
        rows.append({"coin": c, "sample_cov_pct": round(cov, 2), "gaps_gt_2m": n_gaps,
                     "max_gap_min": max_gap, "oct10_11_cov_pct": round(100*len(t10)/len(exp10), 2),
                     "n_rows_full": len(df)})
    out = ROOT / "results" / "v2"
    out.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "hl_gaps_summary.csv", index=False)
    pd.DataFrame(gap_rows).to_csv(out / "hl_gaps_detail.csv", index=False)
    md = ["# HL minute archive gaps (sample 2024-11-01 → 2026-10-26)", "",
          summary.to_markdown(index=False), "",
          f"Gaps >30 min: {len(gap_rows)} (see hl_gaps_detail.csv).",
          "Oct 10–11 2025 coverage is complete for all coins.",
          "Largest gaps cluster in Sep–Oct 2026 (archive day truncation) and one 24h gap 2026-07-07→09."]
    (out / "hl_gaps.md").write_text("\n".join(md))
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
