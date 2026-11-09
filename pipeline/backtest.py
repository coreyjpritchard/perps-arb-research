"""Funding-carry backtest per ../preregistration.md. Usage: python backtest.py
Outputs: ../results/bt_*.csv, ../results/*.png, ../results/bt_summary.json"""
import os, json, itertools, numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from common import COINS

ROOT = os.path.join(os.path.dirname(__file__), ".."); DATA = os.path.join(ROOT, "data"); RES = os.path.join(ROOT, "results")
os.makedirs(RES, exist_ok=True)
START, SPLIT, END = [pd.Timestamp(x, tz="UTC") for x in ("2024-11-01", "2026-07-26", "2026-10-26")]
WARM = START - pd.Timedelta(days=7)
GRID = pd.date_range(WARM, END, freq="8h")
W = 21; ANN = 3 * 365
THETAS = [0.05, 0.10, 0.15, 0.20, 0.30]
FEE = {"HL": {"taker": 4.5e-4, "maker": 1.5e-4}, "BIN": {"taker": 5e-4, "maker": 2e-4},
       "BYB": {"taker": 5.5e-4, "maker": 2e-4}, "BINSPOT": {"taker": 1e-3, "maker": 1e-3}}
FPREFIX = {"HL": "hl", "BIN": "bin", "BYB": "byb"}
PPREFIX = {"HL": "hl", "BIN": "bin", "BYB": "byb", "BINSPOT": "binspot"}
COST = pd.read_csv(os.path.join(DATA, "cost_params.csv")).set_index(["coin", "venue"])
rd = lambda n: pd.read_parquet(os.path.join(DATA, n + ".parquet"))

# ---------- load & align ----------
FUND, PX, GAPS = {}, {}, []
for c in COINS:
    for v, p in FPREFIX.items():
        df = rd(f"{p}_funding_{c}")
        hr = df.time.dt.floor("h")
        bucket = hr.dt.ceil("8h")
        s = df.groupby(bucket).rate.sum().reindex(GRID)
        n = df.groupby(bucket).rate.size().reindex(GRID)
        FUND[(c, v)] = s
        if v == "HL":
            bad = GRID[(n != 8) & (GRID > WARM)]
            if len(bad): GAPS.append(f"{c} HL: {len(bad)} 8h buckets without exactly 8 hourly prints")
        miss = s[GRID >= START].isna().sum()
        if miss: GAPS.append(f"{c} {v}: {miss} 8h buckets with no funding print (treated as 0, sleeve forced flat)")
    for v, p in PPREFIX.items():
        df = rd(f"{p}_px4h_{c}")
        s = df.set_index("close_time").close
        s = s[~s.index.duplicated()].reindex(GRID)
        miss = s[GRID >= START].isna().sum()
        if miss: GAPS.append(f"{c} {v}: {miss} missing 8h-grid prices (ffill<=1 bar)")
        PX[(c, v)] = s.ffill(limit=1)


def costs_for(c, v, mode):
    """per-fill cost fraction on one leg: fee + slippage."""
    fee = FEE[v]["maker" if mode == "maker" else "taker"]
    slip = 0.0 if mode == "maker" else COST.loc[(c, v), "slip_100k_bps" if mode == "100k" else "slip_10k_bps"] / 1e4
    return fee, slip


def simulate(c, short_v, long_v, kind, theta, cm=1.0, mode="10k", lev=2.0):
    """kind: 'spread' (both directions), 'carry' (short HL vs spot, one direction), 'always'.
    Returns per-period DataFrame (returns on capital) and trade list."""
    fa = FUND[(c, short_v)].fillna(np.nan)
    fb = FUND[(c, long_v)] if long_v != "BINSPOT" else pd.Series(0.0, index=GRID)
    pa, pb = PX[(c, short_v)], PX[(c, long_v)]
    ra, rb = pa.pct_change(), pb.pct_change()
    valid = fa.notna() & fb.notna() & ra.notna() & rb.notna()
    spread = (fa - fb).fillna(0.0)
    trail = spread.rolling(W, min_periods=W).mean() * ANN
    cap = 2 / lev if long_v != "BINSPOT" else 1 + 1 / lev
    feeA, slipA = costs_for(c, short_v, mode); feeB, slipB = costs_for(c, long_v, mode)
    leg = COST.loc[(c, "HL"), "leg_risk_bps"] / 1e4
    rt_fee, rt_slip, rt_leg = (feeA + feeB) * cm, (slipA + slipB) * cm, leg * cm
    idx = GRID[GRID >= START]
    pos = 0; rows = []; trades = []; cur = None
    for i, t in enumerate(idx):
        # PnL over (t_prev, t] for position held from previous decision
        fund = pnl_px = 0.0
        if pos != 0:
            if valid[t]:
                fund = pos * spread[t]               # pos=+1: short A long B
                pnl_px = pos * (rb[t] - ra[t])
            cur["fund"] += fund; cur["px"] += pnl_px
        # decision at t
        tr = trail[t]; new = pos
        if kind == "always":
            new = 1 if i < len(idx) - 1 else 0
        else:
            if not valid[t] or np.isnan(tr): new = 0
            elif pos == 0:
                if tr > theta: new = 1
                elif kind == "spread" and tr < -theta: new = -1
            elif pos * tr < theta / 2: new = 0
            if i == len(idx) - 1: new = 0
        cfee = cslip = cleg = 0.0; nchg = 0
        if new != pos:
            n_changes = (1 if pos != 0 else 0) + (1 if new != 0 else 0)
            cfee, cslip, cleg = rt_fee * n_changes, rt_slip * n_changes, rt_leg * n_changes; nchg = n_changes
            if pos != 0:
                cur["cost"] += (rt_fee + rt_slip + rt_leg); cur["exit"] = t; trades.append(cur)
            if new != 0:
                cur = {"coin": c, "short": short_v if new > 0 else long_v, "long": long_v if new > 0 else short_v,
                       "entry": t, "fund": 0.0, "px": 0.0, "cost": rt_fee + rt_slip + rt_leg}
            pos = new
        rows.append((t, fund / cap, pnl_px / cap, -cfee / cap, -cslip / cap, -cleg / cap, pos != 0, nchg))
    df = pd.DataFrame(rows, columns=["t", "fund", "basis", "fee", "slip", "leg", "inpos", "chg"]).set_index("t")
    # costs of a decision at t are booked in the period (t, t+8h] (next row); the final forced exit stays on the last row
    for k in ["fee", "slip", "leg", "chg"]:
        last = df[k].iloc[-1]; df[k] = df[k].shift(1).fillna(0.0); df.iloc[-1, df.columns.get_loc(k)] += last
    df["net"] = df[["fund", "basis", "fee", "slip", "leg"]].sum(axis=1)
    df["cap"] = cap
    tr = pd.DataFrame(trades)
    if len(tr): tr["net"] = tr.fund + tr.px - tr.cost; tr["net_on_cap"] = tr.net / cap
    return df, tr


PAIRS = [("HL", "BIN"), ("HL", "BYB"), ("BIN", "BYB")]


def sleeves(strat):
    if strat == "a": return [(c, a, b, "spread") for c in COINS for a, b in PAIRS]
    if strat == "b": return [(c, "HL", "BINSPOT", "carry") for c in COINS]
    if strat == "c": return [(c, "HL", "BIN", "always") for c in COINS]
    if strat == "c2": return [(c, "HL", "BINSPOT", "always") for c in COINS]


def run(strat, theta, **kw):
    per, trs = {}, []
    for c, a, b, kind in sleeves(strat):
        df, tr = simulate(c, a, b, kind, theta, **kw); per[(c, a, b)] = df
        if len(tr): tr["pair"] = f"{a}-{b}"; trs.append(tr)
    return per, (pd.concat(trs) if trs else pd.DataFrame())


def metrics(per, trades, lo, hi):
    """Portfolio = equal capital per sleeve -> mean of sleeve returns on capital."""
    sl = {k: v[(v.index > lo) & (v.index <= hi)] for k, v in per.items()}
    port = pd.concat([v.net for v in sl.values()], axis=1).mean(axis=1)
    daily = port.groupby((port.index - pd.Timedelta("1ns")).floor("D")).sum()
    days = (hi - lo).days
    ann = daily.sum() / days * 365
    sh = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan
    cum = daily.cumsum(); dd = (cum - cum.cummax()).min()
    comp = {k: np.mean([v[k].sum() for v in sl.values()]) / days * 365 for k in ["fund", "basis", "fee", "slip", "leg"]}
    inpos = np.mean([v.inpos.mean() for v in sl.values()])
    # turnover: notional traded (2 legs per change, N=1) / capital, annualised
    turn = np.mean([(v.chg.sum() * 2 / v.cap.iloc[0]) for v in sl.values()]) / days * 365
    tr = trades[(trades.exit > lo) & (trades.exit <= hi)] if len(trades) else trades
    return {"ann_net": ann, "sharpe": sh, "maxdd": dd, "time_in_pos": inpos, "ann_net_while_deployed": ann / inpos if inpos > 0 else np.nan,
            "turnover_x_per_yr": turn, "n_trades": len(tr), "hit_rate": (tr.net > 0).mean() if len(tr) else np.nan,
            "avg_hold_days": ((tr.exit - tr.entry).dt.total_seconds() / 86400).mean() if len(tr) else np.nan,
            **{f"ann_{k}": v for k, v in comp.items()}}, daily


def sleeve_table(per, lo, hi):
    out = []
    for (c, a, b), v in per.items():
        v = v[(v.index > lo) & (v.index <= hi)]; days = (hi - lo).days
        d = v.net.groupby((v.index - pd.Timedelta("1ns")).floor("D")).sum()
        out.append({"coin": c, "legs": f"{a}/{b}", "ann_net": d.sum() / days * 365,
                    "sharpe": d.mean() / d.std() * np.sqrt(365) if d.std() > 0 else np.nan,
                    "ann_gross_funding": v.fund.sum() / days * 365, "ann_basis": v.basis.sum() / days * 365,
                    "ann_costs": (v.fee + v.slip + v.leg).sum() / days * 365, "time_in_pos": v.inpos.mean()})
    return pd.DataFrame(out)


def worst_episodes(per, n=3):
    eps = []
    for (c, a, b), v in per.items():
        r = v.net.rolling(21).sum()[v.inpos.rolling(21).max() > 0]
        if len(r.dropna()): t = r.idxmin(); eps.append({"coin": c, "legs": f"{a}/{b}", "window_end": t, "net_7d_on_cap": r.min()})
    return pd.DataFrame(eps).sort_values("net_7d_on_cap").head(n)


if __name__ == "__main__":
    S = {"gaps": GAPS}
    # ---- IS theta selection ----
    sel = {}
    for strat in ["a", "b"]:
        rows = []
        for th in THETAS:
            per, tr = run(strat, th); m, _ = metrics(per, tr, START, SPLIT); m["theta"] = th; rows.append(m)
        g = pd.DataFrame(rows); g.to_csv(os.path.join(RES, f"bt_IS_grid_{strat}.csv"), index=False)
        sel[strat] = float(g.loc[g.sharpe.idxmax(), "theta"]); print(strat, "IS grid\n", g.round(4).to_string())
    S["theta"] = sel
    # ---- frozen run, IS & OOS ----
    summ, dailies = [], {}
    for strat in ["a", "b", "c", "c2"]:
        th = sel.get(strat, 0.0)
        per, tr = run(strat, th)
        for lab, lo, hi in [("IS", START, SPLIT), ("OOS", SPLIT, END), ("FULL", START, END)]:
            m, d = metrics(per, tr, lo, hi); m.update(strategy=strat, period=lab, theta=th); summ.append(m)
            dailies[(strat, lab)] = d
            st = sleeve_table(per, lo, hi); st.insert(0, "period", lab); st.insert(0, "strategy", strat)
            st.to_csv(os.path.join(RES, f"bt_sleeves_{strat}_{lab}.csv"), index=False)
        if len(tr): tr.to_csv(os.path.join(RES, f"bt_trades_{strat}.csv"), index=False)
        worst_episodes(per).to_csv(os.path.join(RES, f"bt_worst_{strat}.csv"), index=False)
    sm = pd.DataFrame(summ); sm.to_csv(os.path.join(RES, "bt_summary.csv"), index=False)
    print(sm.round(4).to_string())
    # ---- sensitivity (frozen theta) ----
    sens = []
    for strat in ["a", "b", "c"]:
        th = sel.get(strat, 0.0)
        variants = [("cost x0", dict(cm=0)), ("cost x0.5", dict(cm=0.5)), ("cost x1 (base)", dict(cm=1)),
                    ("cost x1.5", dict(cm=1.5)), ("cost x2", dict(cm=2)), ("maker fees, no slip", dict(mode="maker")),
                    ("$100k slippage", dict(mode="100k")), ("1x leverage", dict(lev=1.0)), ("3x leverage", dict(lev=3.0))]
        for name, kw in variants:
            per, tr = run(strat, th, **kw)
            for lab, lo, hi in [("IS", START, SPLIT), ("OOS", SPLIT, END)]:
                m, _ = metrics(per, tr, lo, hi)
                sens.append({"strategy": strat, "variant": name, "period": lab, "ann_net": m["ann_net"], "sharpe": m["sharpe"], "maxdd": m["maxdd"]})
    pd.DataFrame(sens).to_csv(os.path.join(RES, "bt_sensitivity.csv"), index=False)
    # ---- funding regime table ----
    reg = []
    for c in COINS:
        f = pd.DataFrame({v: FUND[(c, v)] for v in FPREFIX})[GRID >= START]
        q = f.groupby(f.index.tz_localize(None).to_period("Q")).mean() * ANN
        for per_, r in q.iterrows(): reg.append({"coin": c, "quarter": str(per_), **{f"{k}_ann": r[k] for k in FPREFIX}})
    pd.DataFrame(reg).to_csv(os.path.join(RES, "bt_funding_by_quarter.csv"), index=False)
    # last-30d check of prior claim
    lo30 = END - pd.Timedelta(days=30); chk = []
    for c in COINS:
        chk.append({"coin": c, **{f"{v}_30d_ann": FUND[(c, v)][(GRID > lo30) & (GRID <= END)].mean() * ANN for v in FPREFIX},
                    **{f"{v}_full_ann": FUND[(c, v)][(GRID > START) & (GRID <= END)].mean() * ANN for v in FPREFIX}})
    pd.DataFrame(chk).to_csv(os.path.join(RES, "bt_funding_check.csv"), index=False)
    # ---- charts ----
    fig, ax = plt.subplots(figsize=(11, 5))
    lbl = {"a": f"(a) cross-venue spread θ={sel['a']:.0%}", "b": f"(b) cash-and-carry θ={sel['b']:.0%}",
           "c": "(c) always-on HL short / Binance long", "c2": "always-on HL short / Binance spot (ref)"}
    for s in ["a", "b", "c", "c2"]:
        d = dailies[(s, "FULL")]; ax.plot(d.index, d.cumsum() * 100, label=lbl[s])
    ax.axvline(SPLIT, color="k", ls="--", lw=1); ax.text(SPLIT, ax.get_ylim()[1] * 0.95, " OOS →")
    ax.set_ylabel("cumulative net return on capital, %"); ax.set_title("Funding carry: cumulative net PnL (8-coin equal-capital portfolio, base costs, 2x/leg)")
    ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(os.path.join(RES, "cum_net_pnl.png"), dpi=120)
    fig, axs = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for c in COINS:
        sp = (FUND[(c, "HL")] - FUND[(c, "BIN")])[GRID >= START].rolling(90).mean() * ANN * 100
        axs[0].plot(sp.index, sp, label=c, lw=1)
        sp2 = (FUND[(c, "HL")] - FUND[(c, "BYB")])[GRID >= START].rolling(90).mean() * ANN * 100
        axs[1].plot(sp2.index, sp2, label=c, lw=1)
    for a_, t_ in zip(axs, ["HL − Binance", "HL − Bybit"]):
        a_.axhline(0, color="k", lw=.8); a_.axvline(SPLIT, color="k", ls="--", lw=1); a_.set_ylabel("% / yr"); a_.set_title(f"Funding spread {t_}, 30-day rolling mean, annualised"); a_.grid(alpha=.3)
    axs[0].legend(ncol=8, fontsize=8); fig.tight_layout(); fig.savefig(os.path.join(RES, "funding_spread.png"), dpi=120)
    json.dump(S, open(os.path.join(RES, "bt_summary.json"), "w"), indent=1, default=str)
    print(S)
