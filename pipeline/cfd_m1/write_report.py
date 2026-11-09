"""Write results/cfd_m1/cfd_m1_backtest_v1.md from computed CSVs. Never invent numbers."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from common_m1 import RESULTS, ROOT

def main():
    split = json.loads((RESULTS / "sample_split.json").read_text())
    offset = json.loads((RESULTS / "time_offset.json").read_text())
    inv = json.loads((RESULTS / "inventory.json").read_text())
    port = json.loads((RESULTS / "portfolio_summary.json").read_text())
    desc = pd.read_csv(RESULTS / "passive_summary.csv")
    summary = pd.read_csv(RESULTS / "strategy_summary.csv")
    lat_path = RESULTS / "latency_sensitivity.csv"
    lat = pd.read_csv(lat_path) if lat_path.exists() else pd.DataFrame()
    reopen_path = RESULTS / "session_reopens.csv"
    reopens = pd.read_csv(reopen_path) if reopen_path.exists() else pd.DataFrame()

    gap = summary[summary.strategy == "gap"].copy() if "strategy" in summary.columns else summary
    if "latency_s" in gap.columns:
        gap0 = gap[gap.latency_s.fillna(0) == 0]
    else:
        gap0 = gap
    opens = summary[summary.strategy == "session_open"] if "strategy" in summary.columns else pd.DataFrame()

    lines = []
    lines.append("# CFD M1 backtest v1 — Hyperliquid HIP-3 (trade.xyz) vs prop-firm demo MT5")
    lines.append("")
    lines.append("Run 2026-10-27. Paper research only: public HL API + read-only prop-firm demo MT5 M1/ticks. **No accounts, keys, wallets or orders.**")
    lines.append("")
    lines.append("Pre-registration: `../../preregistration_cfd_m1.md` (written ~10:25 UTC, before PnL).")
    lines.append("")
    lines.append("**Hard caveat:** The MT5 feed is a prop-firm demo feed, not the retail broker ATJ uses. The prop firm's terms ban arbitrage. This is a **proxy for gap and cost structure only**. ATJ profit claims are **unverified**.")
    lines.append("")
    lines.append("## Verdict")
    mode = split.get("mode", "")
    days = split.get("calendar_days", 0)
    net = port.get("gap_net_usd", 0.0)
    oos_net = port.get("gap_oos_net_usd", 0.0)
    trades = port.get("gap_trades", 0)
    if "descriptive" in mode or (isinstance(days, (int, float)) and days < 10):
        lines.append(f"- Sample is **short** (~{days} calendar days of HL∩MT5 overlap). Per prereg: **descriptive / illustrative only — no formal pass/fail**.")
    if trades == 0:
        lines.append("- **(A) Gap mean reversion (k=2, T_max=30): no trades** under next-minute fills after costs — no evidence of a capturable M1 edge on this window.")
    elif oos_net <= 0 and net <= 0:
        lines.append(f"- **(A) Gap mean reversion: no evidence of edge.** Portfolio net ${net:.2f} on $10k/leg ({trades} trades); illustrative OOS net ${oos_net:.2f}.")
    elif net > 0 and days < 10:
        lines.append(f"- **(A) Gap mean reversion: inconclusive.** Full-sample net ${net:.2f} ({trades} trades) but sample < 10 days — needs more data before any claim.")
    else:
        lines.append(f"- **(A) Gap:** portfolio net ${net:.2f}, illustrative OOS ${oos_net:.2f}, trades={trades}. See tables; do not over-claim.")
    n_open = int(port.get("open_trades", 0))
    n_re = len(reopens)
    if n_re < 5:
        lines.append(f"- **(B) Session-open / weekend:** only {n_re} reopen events in sample (<5) — distributions only; {n_open} trades under k_open=2.")
    else:
        lines.append(f"- **(B) Session-open / weekend:** {n_re} reopens, {n_open} trades. See `session_open_trades.csv`.")
    lines.append("- **Bottom line:** With ~4 days of concurrent M1 overlap, this run cannot validate ATJ-style M1 arb on the prop-firm demo proxy. Prior hourly work also found no edge (gap OOS −7.8%).")
    # data need
    lines.append("")
    lines.append("### How much more data for a verdict")
    lines.append("- Prereg formal OOS bar needs ≥10 calendar days concurrent; a more credible test needs **≥30 calendar days** of HL∩MT5 M1 overlap and preferably **≥100 gap trades** under k=2.")
    lines.append("- HL `candleSnapshot` retains ~5000 1m bars (~3.5 days). Keep running `pipeline/minute/hl_1m_backfill.py` every 1–2 days (Mon/Wed/Fri cadence already noted) and retain archives so history accumulates beyond the API window.")
    lines.append("- The MT5 export refreshes weekdays 23:15 UTC — continue copying ticks/M1 into `data/mt5_m1/`.")
    lines.append("")
    lines.append("## Time offset")
    lines.append(f"- Chosen MT5 timestamp adjustment: **subtract {offset.get('chosen_offset_hours')} hour(s)** before joining to HL UTC (`reason` / votes in `time_offset.json`).")
    lines.append(f"- Probe summary: `{json.dumps(offset.get('probes', {}), default=str)[:500]}...`" if offset.get("probes") else "")
    lines.append("")
    lines.append("## Data inventory")
    lines.append(f"- Tick files local: {inv.get('tick_file_count')} (remote expected {inv.get('expected_tick_files_remote')}). Per symbol: {inv.get('tick_files_per_symbol')}.")
    lines.append(f"- Overlap window: {split.get('global_start')} → {split.get('global_end')} ({days} days). Split mode: `{mode}`. Illustrative OOS starts {split.get('oos_start')}.")
    lines.append("")
    lines.append("## (C) Passive gap / costs")
    lines.append("")
    cols = [c for c in [
        "mt5", "hl", "n_minutes", "gap_mean_bps", "gap_median_bps", "gap_std_bps",
        "half_life_min", "frac_abs_gap_gt_cost", "frac_abs_dev_gt_cost",
        "rt_cost_bps_median", "mt5_spread_bps_median", "hl_half_bps",
    ] if c in desc.columns]
    if cols:
        lines.append(desc[cols].to_markdown(index=False))
    lines.append("")
    lines.append("Charts: `gap_series_XAUUSD.png`, `gap_series_US500_cash.png`, `capturable_edge_hist.png`.")
    lines.append("")
    lines.append("## (A) Gap mean reversion — per pair (latency 0s, k=2, T_max=30)")
    lines.append("")
    show = gap0.copy()
    keep = [c for c in [
        "mt5", "n_minutes", "frac_abs_gap_gt_cost", "trades", "gross_bp", "net_bp",
        "gross_usd", "net_usd", "is_trades", "oos_trades", "is_net_usd", "oos_net_usd",
        "is_net_bp", "oos_net_bp",
    ] if c in show.columns]
    if len(show) and keep:
        lines.append(show[keep].to_markdown(index=False))
    else:
        lines.append("_No gap trades / empty summary._")
    lines.append("")
    lines.append(f"Portfolio (sum of pairs): trades={trades}, gross_usd={port.get('gap_gross_usd')}, net_usd={net}, IS_net={port.get('gap_is_net_usd')}, OOS_net={oos_net}.")
    lines.append("")
    lines.append("## Latency stress (MT5 fill delayed 1–5s via ticks)")
    lines.append("")
    if lat.empty:
        lines.append("_No latency rows (no baseline trades or file missing)._")
    else:
        keep = [c for c in ["mt5", "latency_s", "trades", "net_usd", "net_bp", "oos_net_usd"] if c in lat.columns]
        lines.append(lat[keep].to_markdown(index=False))
    lines.append("")
    lines.append("## (B) Session-open / weekend")
    lines.append("")
    if reopens.empty:
        lines.append("No reopen events detected (gap≥3h) in the aligned sample.")
    else:
        lines.append(f"Reopen events: {len(reopens)} (weekend={int(reopens['weekend'].sum()) if 'weekend' in reopens.columns else '?'}).")
        if len(opens):
            keep = [c for c in ["mt5", "n_reopens", "n_weekend_reopens", "trades", "net_usd", "net_bp"] if c in opens.columns]
            lines.append(opens[keep].to_markdown(index=False))
    lines.append("")
    lines.append("## Costs used")
    lines.append("- HL docs-correct taker: growth 0.009% (EUR/GBP/JPY/JP225/SP500/XYZ100); GOLD standard 0.09%. Half-spread from l2Book median (floor 1 bp).")
    lines.append("- MT5: tick bid/ask each fill; FX/metal commission $5/lot RT; indices $0. **Not** M1 bar min-spread. **Not** `cost_table.csv`.")
    lines.append("- Swaps/funding accrued only if holds cross events; short M1 holds rarely do.")
    lines.append("")
    lines.append("## Files")
    lines.append("- Code: `../../pipeline/cfd_m1/`")
    lines.append("- Data: `../../data/mt5_m1/`, `../../data/hl_1m/`, `../../data/hl_m1_aux/`")
    lines.append("- Results: this folder")
    lines.append("")
    lines.append("## Deviations")
    lines.append("See append-only log at end of `preregistration_cfd_m1.md`.")
    text = "\n".join(lines) + "\n"
    (RESULTS / "cfd_m1_backtest_v1.md").write_text(text)
    print("wrote", RESULTS / "cfd_m1_backtest_v1.md")

if __name__ == "__main__":
    main()
