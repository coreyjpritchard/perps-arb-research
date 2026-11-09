"""Orchestrate carry backtest v2 with per-key disk cache for resume."""
from __future__ import annotations
import json, sys, time, pickle
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import load_aligned, simulate_clean, portfolio, START, SPLIT, END, N_BASE
from gap_report import main as gap_main

RES = ROOT / "results" / "v2"
CACHE = RES / "cache"
RES.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX"]
LEVS = [1.0, 1.5, 2.0]
CACHE_VER = "v2fix2"  # bump when engine accounting changes


def cache_path(label, strat, lev, adl, coin):
    return CACHE / f"{CACHE_VER}_{label}_{strat}_{lev}_{adl}_{coin}.pkl"


def run_sleeve(coin, frame, lev, strat, adl, label):
    cp = cache_path(label, strat, lev, adl, coin)
    if cp.exists():
        with open(cp, "rb") as f:
            return pickle.load(f)
    r = simulate_clean(coin, frame, lev, strat, n=N_BASE, adl=adl)
    # drop bulky path for cache of non-oct keys? keep for c/flat/noadl
    with open(cp, "wb") as f:
        pickle.dump(r, f, protocol=pickle.HIGHEST_PROTOCOL)
    return r


def ensure_data():
    for c in COINS + ["HYPE"]:
        mp = ROOT / "data" / "binance_1m" / "mark" / f"{c}.parquet"
        if not mp.exists():
            raise SystemExit(f"missing mark data for {c}: {mp}")
        if c != "HYPE" and not (ROOT / "data" / "binance_1m" / "spot" / f"{c}.parquet").exists():
            raise SystemExit(f"missing spot for {c}")


def run_block(label, frames, strat, levs, adl_flags, rows, port_eq, oct_paths):
    for lev in levs:
        for adl in adl_flags:
            key = (label, strat, lev, adl)
            t0 = time.time()
            print(f"simulate {key}", flush=True)
            sleeves = []
            for c in COINS:
                r = run_sleeve(c, frames[c], lev, strat, adl, label)
                sleeves.append(r)
                rows.append({
                    "gap_mode": label, "strategy": strat, "leverage": lev, "adl": adl, "coin": c,
                    "capital": r["capital"],
                    "IS_ann": r["IS"]["ann"], "IS_sharpe": r["IS"]["sharpe"], "IS_maxdd": r["IS"]["maxdd"],
                    "OOS_ann": r["OOS"]["ann"], "OOS_sharpe": r["OOS"]["sharpe"], "OOS_maxdd": r["OOS"]["maxdd"],
                    "FULL_ann": r["FULL"]["ann"], "FULL_sharpe": r["FULL"]["sharpe"], "FULL_maxdd": r["FULL"]["maxdd"],
                    "oct10_pnl": r["oct10_pnl_frac"],
                    "n_liq": r["n_liq"], "n_rebal": r["n_rebal"], "n_adl": r["n_adl"],
                    "n_gapflat": r["n_gapflat"], "n_entry": r["n_entry"],
                })
                if label == "flat" and (not adl) and strat == "c":
                    oct_paths[(c, lev)] = r["oct10_path"]
                if label == "hold" and (not adl) and strat == "c":
                    oct_paths[(f"hold_{c}", lev)] = r["oct10_path"]
            p = portfolio(sleeves)
            port_eq[key] = p
            rows.append({
                "gap_mode": label, "strategy": strat, "leverage": lev, "adl": adl, "coin": "PORTFOLIO",
                "capital": p["capital"],
                "IS_ann": p["IS"]["ann"], "IS_sharpe": p["IS"]["sharpe"], "IS_maxdd": p["IS"]["maxdd"],
                "OOS_ann": p["OOS"]["ann"], "OOS_sharpe": p["OOS"]["sharpe"], "OOS_maxdd": p["OOS"]["maxdd"],
                "FULL_ann": p["FULL"]["ann"], "FULL_sharpe": p["FULL"]["sharpe"], "FULL_maxdd": p["FULL"]["maxdd"],
                "oct10_pnl": p["oct10_pnl_frac"],
                "n_liq": p["n_liq"], "n_rebal": p["n_rebal"], "n_adl": p["n_adl"],
                "n_gapflat": sum(s["n_gapflat"] for s in sleeves),
                "n_entry": sum(s["n_entry"] for s in sleeves),
            })
            print(f"  done in {time.time()-t0:.1f}s PORT FULL_ann={p['FULL']['ann']:.4f} OOS={p['OOS']['ann']:.4f} "
                  f"maxdd={p['FULL']['maxdd']:.4f} liq={p['n_liq']} rebal={p['n_rebal']} oct10={p['oct10_pnl_frac']:.4f}",
                  flush=True)


def run():
    print("=== gap report ===", flush=True)
    gap_main()
    ensure_data()

    print("=== align ===", flush=True)
    aligned_c_flat, aligned_ref_flat, aligned_c_hold = {}, {}, {}
    for c in COINS:
        print(f"align {c}", flush=True)
        aligned_c_flat[c] = load_aligned(c, False, "flat")
        aligned_ref_flat[c] = load_aligned(c, True, "flat")
        aligned_c_hold[c] = load_aligned(c, False, "hold")

    rows = []
    port_eq = {}
    oct_paths = {}

    run_block("flat", aligned_c_flat, "c", LEVS, (False, True), rows, port_eq, oct_paths)
    run_block("flat", aligned_ref_flat, "ref", LEVS, (False,), rows, port_eq, oct_paths)
    run_block("hold", aligned_c_hold, "c", LEVS, (False, True), rows, port_eq, oct_paths)

    hype_mark = ROOT / "data" / "binance_1m" / "mark" / "HYPE.parquet"
    if hype_mark.exists():
        try:
            for mode in ("flat", "hold"):
                hdf = load_aligned("HYPE", False, mode)
                if hdf is not None and hdf["valid"].any():
                    for lev in LEVS:
                        r = simulate_clean("HYPE", hdf, lev, "c", n=N_BASE, adl=False)
                        rows.append({
                            "gap_mode": mode, "strategy": "c_hype", "leverage": lev, "adl": False, "coin": "HYPE",
                            "capital": r["capital"],
                            "IS_ann": r["IS"]["ann"], "IS_sharpe": r["IS"]["sharpe"], "IS_maxdd": r["IS"]["maxdd"],
                            "OOS_ann": r["OOS"]["ann"], "OOS_sharpe": r["OOS"]["sharpe"], "OOS_maxdd": r["OOS"]["maxdd"],
                            "FULL_ann": r["FULL"]["ann"], "FULL_sharpe": r["FULL"]["sharpe"], "FULL_maxdd": r["FULL"]["maxdd"],
                            "oct10_pnl": r["oct10_pnl_frac"],
                            "n_liq": r["n_liq"], "n_rebal": r["n_rebal"], "n_adl": r["n_adl"],
                            "n_gapflat": r["n_gapflat"], "n_entry": r["n_entry"],
                        })
        except Exception as e:
            print("HYPE skip:", e, flush=True)

    res = pd.DataFrame(rows)
    res.to_csv(RES / "summary_by_coin.csv", index=False)
    port = res[res.coin == "PORTFOLIO"].copy()
    port.to_csv(RES / "summary_portfolio.csv", index=False)

    verdicts = []
    for lev in LEVS:
        base = port[(port.gap_mode == "flat") & (port.strategy == "c") & (port.leverage == lev) & (port.adl == False)].iloc[0]
        adlrow = port[(port.gap_mode == "flat") & (port.strategy == "c") & (port.leverage == lev) & (port.adl == True)].iloc[0]
        hold = port[(port.gap_mode == "hold") & (port.strategy == "c") & (port.leverage == lev) & (port.adl == False)].iloc[0]
        hold_adl = port[(port.gap_mode == "hold") & (port.strategy == "c") & (port.leverage == lev) & (port.adl == True)].iloc[0]
        oct_worse = min(float(base.oct10_pnl), float(adlrow.oct10_pnl))
        one_year = float(base.FULL_ann)
        survives = oct_worse > -abs(one_year) if np.isfinite(one_year) else False
        ok = (float(base.OOS_ann) > 0.045) and (float(base.FULL_maxdd) > -0.10) and survives
        verdicts.append({
            "leverage": lev,
            "OOS_ann": base.OOS_ann, "IS_ann": base.IS_ann, "FULL_ann": base.FULL_ann,
            "FULL_maxdd": base.FULL_maxdd, "FULL_sharpe": base.FULL_sharpe,
            "oct10_base": base.oct10_pnl, "oct10_adl": adlrow.oct10_pnl,
            "oct10_worse": oct_worse, "one_year_carry": one_year,
            "n_liq": int(base.n_liq), "n_rebal": int(base.n_rebal), "n_gapflat": int(base.n_gapflat),
            "pass": bool(ok),
            "hold_IS_ann": hold.IS_ann, "hold_OOS_ann": hold.OOS_ann, "hold_FULL_ann": hold.FULL_ann,
            "hold_FULL_maxdd": hold.FULL_maxdd, "hold_FULL_sharpe": hold.FULL_sharpe,
            "hold_oct10": hold.oct10_pnl, "hold_oct10_adl": hold_adl.oct10_pnl,
            "hold_n_liq": int(hold.n_liq), "hold_n_rebal": int(hold.n_rebal),
        })
    vd = pd.DataFrame(verdicts)
    vd.to_csv(RES / "verdicts.csv", index=False)
    print("\n=== VERDICTS ===", flush=True)
    print(vd.to_string(index=False), flush=True)

    # charts
    fig, ax = plt.subplots(figsize=(11, 5))
    for lev in LEVS:
        p = port_eq[("hold", "c", lev, False)]
        ax.plot(p["eq"].index, (p["eq"] - p["capital"]) / p["capital"] * 100, label=f"c {lev:.1f}x hold")
    ax.axvline(SPLIT, color="gray", ls="--", lw=1, label="OOS start")
    ax.axvline(pd.Timestamp("2025-10-10", tz="UTC"), color="red", ls=":", lw=1, label="10 Oct 2025")
    ax.set_ylabel("Cumulative return on capital (%)")
    ax.set_title("HL short / Binance perp long — hold-through-gaps sensitivity")
    ax.legend(); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(RES / "equity_by_leverage.png", dpi=120); plt.close()

    fig, ax = plt.subplots(figsize=(11, 5))
    for lev in LEVS:
        p = port_eq[("flat", "c", lev, False)]
        ax.plot(p["eq"].index, (p["eq"] - p["capital"]) / p["capital"] * 100, label=f"c {lev:.1f}x flat")
    ax.axvline(SPLIT, color="gray", ls="--", lw=1)
    ax.axvline(pd.Timestamp("2025-10-10", tz="UTC"), color="red", ls=":", lw=1, label="10 Oct 2025")
    ax.set_ylabel("Cumulative return on capital (%)")
    ax.set_title("Prereg gap-flat path — archive holes force exit/re-entry costs")
    ax.legend(); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(RES / "equity_by_leverage_flat.png", dpi=120); plt.close()

    fig, ax = plt.subplots(figsize=(11, 5))
    for c in COINS:
        path = oct_paths.get((f"hold_{c}", 2.0)) or oct_paths.get((c, 2.0))
        if not path:
            continue
        ts = [p[0] for p in path]
        mr = [p[2] for p in path]  # Binance MR — the side that dies on crash
        if any(pd.notna(x) for x in mr):
            ax.plot(ts, mr, label=c, alpha=0.8)
    ax.axhline(0.005, color="red", ls="--", lw=1, label="~Binance MMR 0.5%")
    ax.set_title("Binance long margin ratio on 10 Oct 2025 (c, 2x, hold)")
    ax.set_ylabel("equity / mark-notional")
    ax.legend(ncol=4, fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(RES / "oct10_binance_margin_ratios.png", dpi=120); plt.close()

    fig, ax = plt.subplots(figsize=(11, 5))
    for c in COINS:
        path = oct_paths.get((f"hold_{c}", 2.0)) or oct_paths.get((c, 2.0))
        if not path:
            continue
        ts = [p[0] for p in path]
        mr = [p[1] for p in path]
        if any(pd.notna(x) for x in mr):
            ax.plot(ts, mr, label=c, alpha=0.8)
    ax.axhline(0.05, color="red", ls="--", lw=1, label="HL MMR alts 5%")
    ax.axhline(0.0125, color="orange", ls="--", lw=1, label="HL MMR BTC 1.25%")
    ax.set_title("HL short margin ratio on 10 Oct 2025 (c, 2x, hold)")
    ax.set_ylabel("equity / mark-notional")
    ax.legend(ncol=4, fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(RES / "oct10_margin_ratios.png", dpi=120); plt.close()

    for (label, strat, lev, adl), p in port_eq.items():
        if strat != "c" or adl:
            continue
        s = (p["eq"] - p["capital"]) / p["capital"]
        s.to_frame("cum_ret").to_csv(RES / f"cumret_{label}_c_{lev}x.csv")

    with open(RES / "run_meta.json", "w") as f:
        json.dump({"n": N_BASE, "coins": COINS, "cache_ver": CACHE_VER,
                   "start": str(START), "split": str(SPLIT), "end": str(END)}, f, indent=2)
    print("done →", RES, flush=True)
    return res, vd


if __name__ == "__main__":
    run()
