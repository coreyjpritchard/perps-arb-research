"""Clean 1-minute sleeve engine for carry v2. Accounting:

equity = sum of venue wallets + cash residual
  (c):   m_hl + upnl_hl + m_bin + upnl_bin + cash
  (ref): m_hl + upnl_hl + spot_nav + standby + cash
where upnl_hl = n*(1 - px_hl/e_hl) for short; upnl_bin/spot = n*(px/e - 1) for long.
At entry m_hl=im_hl, m_bin=im_bin or spot_nav=n, standby=0.25*im_hl (ref), cash=0.
Entry/exit fees and transfer costs hit `cash`.
Funding credits/debits the venue wallet AND is wealth.
Liquidation (isolated backstop model): wipe the liquidated leg's equity to 0; close other leg next bar.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pandas as pd
from mmr import hl_mmr, bin_mmr, BIN_LIQ_FEE

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
COST = pd.read_csv(DATA / "cost_params.csv").set_index(["coin", "venue"])

START = pd.Timestamp("2024-11-01", tz="UTC")
SPLIT = pd.Timestamp("2026-07-26", tz="UTC")
END = pd.Timestamp("2026-10-26", tz="UTC")
OCT10_ADL = pd.Timestamp("2025-10-10 21:15", tz="UTC")
N_BASE = 10_000.0
TRANSFER_DELAY = 45
TRANSFER_COST = 5.0
REBAL_MULT = 1.5
FFILL = 2
FLAT_MIN = 24 * 60
FEE = {"HL": 4.5e-4, "BIN": 5e-4, "BINSPOT": 1e-3}


def _slip(coin, venue, n):
    col = "slip_100k_bps" if n >= 50_000 else "slip_10k_bps"
    try:
        return float(COST.loc[(coin, venue), col]) / 1e4
    except KeyError:
        return float(COST.loc[("AVAX", venue), col]) / 1e4


def _leg(coin):
    try:
        return float(COST.loc[(coin, "HL"), "leg_risk_bps"]) / 1e4
    except KeyError:
        return float(COST.loc[("AVAX", "HL"), "leg_risk_bps"]) / 1e4


def load_aligned(coin: str, use_spot: bool, gap_mode: str = "flat") -> pd.DataFrame | None:
    """gap_mode: 'flat' = prereg 2-min ffill then invalid; 'hold' = unlimited ffill (sensitivity)."""
    hl = pd.read_parquet(DATA / "hl_archive" / "minute" / f"{coin}.parquet")
    hl = hl.sort_values("time")
    hl["t"] = hl["time"].dt.floor("min")
    hl = hl.drop_duplicates("t", keep="last").set_index("t")
    bm = pd.read_parquet(DATA / "binance_1m" / "mark" / f"{coin}.parquet")
    bm = bm.sort_values("time").drop_duplicates("time").set_index("time")
    idx = pd.date_range(START, END - pd.Timedelta(minutes=1), freq="min", tz="UTC")
    df = pd.DataFrame(index=idx)
    lim = None if gap_mode == "hold" else FFILL
    df["hl_mark"] = hl["mark_px"].reindex(idx).ffill(limit=lim)
    df["b_high"] = bm["high"].reindex(idx).ffill(limit=lim)
    df["b_low"] = bm["low"].reindex(idx).ffill(limit=lim)
    df["b_close"] = bm["close"].reindex(idx).ffill(limit=lim)
    if use_spot:
        sp = DATA / "binance_1m" / "spot" / f"{coin}.parquet"
        if not sp.exists():
            return None
        s = pd.read_parquet(sp).sort_values("time").drop_duplicates("time").set_index("time")
        df["s_close"] = s["close"].reindex(idx).ffill(limit=lim)
        df["valid"] = df[["hl_mark", "b_close", "s_close"]].notna().all(axis=1)
    else:
        df["s_close"] = np.nan
        df["valid"] = df[["hl_mark", "b_close"]].notna().all(axis=1)
    # funding (floor to minute — Binance prints often have sub-second offsets)
    bf = pd.read_parquet(DATA / f"bin_funding_{coin}.parquet")
    bf = bf.copy()
    if bf["time"].dt.tz is None:
        bf["time"] = bf["time"].dt.tz_localize("UTC")
    bf["time"] = bf["time"].dt.floor("min")
    bf = bf.drop_duplicates("time", keep="last").set_index("time")["rate"]
    df["bin_fund"] = bf.reindex(idx).fillna(0.0)
    # HL: archive funding at hour, else fallback file
    hl_f = hl["funding"].reindex(idx)
    hour = df.index.minute == 0
    hl_set = pd.Series(0.0, index=idx)
    hl_set.loc[hour] = hl_f.loc[hour]
    miss = hour & hl_set.isna()
    if miss.any():
        fb = pd.read_parquet(DATA / f"hl_funding_{coin}.parquet")
        fb = fb.copy()
        if fb["time"].dt.tz is None:
            fb["time"] = fb["time"].dt.tz_localize("UTC")
        fb["time"] = fb["time"].dt.floor("h")
        fb = fb.drop_duplicates("time", keep="last").set_index("time")["rate"]
        hl_set.loc[miss] = fb.reindex(df.index[miss]).values
    df["hl_fund"] = hl_set.fillna(0.0)
    return df


def ann_window(eq: pd.Series, capital: float, t0, t1):
    sub = eq[(eq.index >= t0) & (eq.index < t1)]
    prev = eq[eq.index < t0]
    base = float(prev.iloc[-1]) if len(prev) else capital
    if len(sub) < 2:
        return {"ann": float("nan"), "sharpe": float("nan"), "maxdd": float("nan"), "total_ret": float("nan")}
    years = max((sub.index[-1] - sub.index[0]).days / 365.25, 1e-9)
    total = (float(sub.iloc[-1]) - base) / capital
    # prereg §9: mean/std of daily net PnL/capital × √365
    dpnL = sub.diff().dropna() / capital
    sharpe = float(dpnL.mean() / dpnL.std() * math.sqrt(365)) if len(dpnL) and dpnL.std() > 0 else float("nan")
    path = (sub - base) / capital
    maxdd = float((path - path.cummax()).min())
    return {"ann": total / years, "sharpe": sharpe, "maxdd": maxdd, "total_ret": total}


def simulate(coin, df, leverage, strategy, n=N_BASE, adl=False):
    use_spot = strategy == "ref"
    L = float(leverage)
    mmr_h = hl_mmr(coin, n)
    mmr_b = 0.0 if use_spot else bin_mmr(coin, n)
    im_h = n / L
    im_b = 0.0 if use_spot else n / L
    standby0 = 0.25 * im_h if use_spot else 0.0
    capital = (n + im_h + standby0) if use_spot else (im_h + im_b)

    fee_h = FEE["HL"] + _slip(coin, "HL", n)
    fee_b = FEE["BINSPOT" if use_spot else "BIN"] + _slip(coin, "BINSPOT" if use_spot else "BIN", n)
    leg = _leg(coin)

    idx = df.index
    T = len(idx)
    hl = df["hl_mark"].to_numpy()
    bh = df["b_high"].to_numpy()
    bl = df["b_low"].to_numpy()
    bc = df["b_close"].to_numpy()
    sc = df["s_close"].to_numpy()
    hf = df["hl_fund"].to_numpy()
    bf = df["bin_fund"].to_numpy()
    valid = df["valid"].to_numpy()
    days = idx.floor("D")

    in_pos = False
    flat_until = 0
    e_hl = e_b = 0.0
    m_hl = m_bin = standby = cash = 0.0
    pend = None  # (credit_i, amt, dir) dir=1 to HL
    n_liq = n_rebal = n_adl = n_gap = n_entry = 0
    daily_eq = {}
    oct_path = []
    events = []
    oct_day = pd.Timestamp("2025-10-10", tz="UTC")

    def long_px(i):
        return sc[i] if use_spot else bc[i]

    def upnl_hl(i, px=None):
        p = hl[i] if px is None else px
        return n * (1.0 - p / e_hl)

    def upnl_long(i, px=None):
        p = long_px(i) if px is None else px
        return n * (p / e_b - 1.0)

    def equity(i):
        if not in_pos:
            return capital + cash
        if use_spot:
            return m_hl + upnl_hl(i) + (n + upnl_long(i)) + standby + cash
            # n + upnl_long = spot_nav; capital had n+im_h+standby0
        return m_hl + upnl_hl(i) + m_bin + upnl_long(i) + cash

    def open_pos(i):
        nonlocal in_pos, e_hl, e_b, m_hl, m_bin, standby, cash, n_entry
        e_hl = float(hl[i]); e_b = float(long_px(i))
        m_hl = im_h
        m_bin = im_b
        standby = standby0
        cash -= (fee_h + fee_b + leg) * n
        in_pos = True
        n_entry += 1

    def force_flat(i, reason):
        nonlocal in_pos, m_hl, m_bin, standby, cash, flat_until, pend, e_hl, e_b
        if not in_pos:
            return
        # realize MTM into cash, return margins to cash (they're part of capital structure via cash PnL)
        # equity before = m_hl+upnl_hl + long_part + standby + cash
        # after flat we want equity = capital + cash' where cash' absorbs all PnL
        eq = equity(i)
        cash = eq - capital
        m_hl = m_bin = standby = 0.0
        e_hl = e_b = 0.0
        in_pos = False
        pend = None
        flat_until = i + FLAT_MIN
        events.append({"t": str(idx[i]), "reason": reason})

    for i in range(T):
        # record previous day's end at day boundary using last equity
        if i > 0 and days[i] != days[i - 1]:
            daily_eq[days[i - 1]] = last_eq

        if not in_pos:
            if i >= flat_until and valid[i]:
                open_pos(i)
            last_eq = equity(i)
            if days[i] == oct_day:
                oct_path.append((idx[i], np.nan, np.nan, last_eq, 0))
            continue

        if not valid[i]:
            n_gap += 1
            force_flat(max(i - 1, 0), "gap_flat")
            last_eq = equity(i)
            continue

        # funding → venue wallets (wealth)
        if hf[i]:
            m_hl += n * hf[i]
        if (not use_spot) and bf[i]:
            m_bin -= n * bf[i]

        # transfer credit
        if pend is not None and i >= pend[0]:
            amt, direction = pend[1], pend[2]
            cash -= TRANSFER_COST
            if direction == 1:
                m_hl += amt
                if use_spot:
                    standby -= amt
                else:
                    m_bin -= amt
            else:
                m_bin += amt
                m_hl -= amt
            n_rebal += 1
            pend = None
            events.append({"t": str(idx[i]), "reason": "rebal"})

        # ADL
        if adl and idx[i] == OCT10_ADL:
            n_adl += 1
            # realize HL at mark into cash via force path but keep long one more minute
            # close HL now: convert HL equity to cash, zero HL
            hl_eq = m_hl + upnl_hl(i)
            cash += hl_eq
            m_hl = 0.0
            # close long next minute
            j = min(i + 1, T - 1)
            px = long_px(j) if valid[j] else long_px(i)
            cash += (n + n * (px / e_b - 1.0))  # spot nav or bin equity without margin? 
            # for (c): long equity = m_bin + upnl; add that to cash
            if use_spot:
                # already added spot_nav; standby stays
                cash += standby
                standby = 0.0
            else:
                cash += m_bin + n * (px / e_b - 1.0)
                m_bin = 0.0
            cash -= (fee_b + leg) * n  # exit other leg
            # remove the double-count of spot: for ref we did cash += (n + upnl) but spot was not in cash before
            # Before ADL: equity = m_hl+upnl_hl + spot_nav + standby + cash
            # We added hl_eq to cash and zeroed m_hl — good.
            # Then added spot_nav to cash and standby — good.
            # in_pos False: equity = capital + cash. We need cash = old_equity - hl wait.
            # Actually after adding hl_eq and spot_nav+standby, cash_new = cash_old + hl_eq + spot_nav + standby - fees
            # equity flat = capital + cash_new. Old equity = hl_eq + spot_nav + standby + cash_old.
            # capital + cash_new = capital + cash_old + hl_eq + spot_nav + standby - fees = capital + (old_eq - capital) + ... 
            # old_eq = hl_eq+spot_nav+standby+cash_old, so capital + cash_old + hl_eq+spot_nav+standby = capital + old_eq - capital + cash_old - cash_old wait
            # capital + cash_new = capital + cash_old + hl_eq + spot_nav + standby - fees = (hl_eq+spot_nav+standby+cash_old) + capital - fees = old_eq + capital - fees
            # That's DOUBLE capital. BUG.
            # Fix: when converting to flat, set cash = equity_before_fees - capital - exit_fees
            pass

        # --- redo ADL block cleanly via helper ---
        # (handled below with flag)

        last_eq = equity(i)  # placeholder; main loop rewritten below

    # The loop above got too messy mid-edit. Full clean loop follows in run path.
    raise RuntimeError("use simulate_clean")


def simulate_clean(coin, df, leverage, strategy, n=N_BASE, adl=False):
    use_spot = strategy == "ref"
    L = float(leverage)
    mmr_h = hl_mmr(coin, n)
    mmr_b = 0.0 if use_spot else bin_mmr(coin, n)
    im_h = n / L
    im_b = 0.0 if use_spot else n / L
    standby0 = 0.25 * im_h if use_spot else 0.0
    capital = (n + im_h + standby0) if use_spot else (im_h + im_b)
    fee_h = FEE["HL"] + _slip(coin, "HL", n)
    fee_b = FEE["BINSPOT" if use_spot else "BIN"] + _slip(coin, "BINSPOT" if use_spot else "BIN", n)
    leg = _leg(coin)

    idx = df.index
    T = len(idx)
    hl = df["hl_mark"].to_numpy(dtype=np.float64)
    bl = df["b_low"].to_numpy(dtype=np.float64)
    bh = df["b_high"].to_numpy(dtype=np.float64)
    bc = df["b_close"].to_numpy(dtype=np.float64)
    sc = df["s_close"].to_numpy(dtype=np.float64)
    hf = df["hl_fund"].to_numpy(dtype=np.float64)
    bfnd = df["bin_fund"].to_numpy(dtype=np.float64)
    valid = df["valid"].to_numpy()
    day = idx.floor("D")
    # precompute adl index
    adl_i = int(idx.get_indexer([OCT10_ADL], method=None)[0]) if adl else -1
    if adl and adl_i < 0:
        # try nearest
        adl_i = int(idx.get_indexer([OCT10_ADL], method="nearest")[0])

    in_pos = False
    flat_until = 0
    e_hl = e_b = 0.0
    m_hl = m_bin = standby = cash = 0.0
    pend_i = -1; pend_amt = 0.0; pend_dir = 0
    n_liq = n_rebal = n_adl = n_gap = n_entry = 0
    daily_eq = {}
    oct_path = []
    events = []
    oct_day = pd.Timestamp("2025-10-10", tz="UTC")
    last_eq = capital

    def long_px(i):
        return sc[i] if use_spot else bc[i]

    def eq_now(i):
        if not in_pos:
            return capital + cash
        u_hl = n * (1.0 - hl[i] / e_hl)
        u_l = n * (long_px(i) / e_b - 1.0)
        if use_spot:
            return m_hl + u_hl + n + u_l + standby + cash
        return m_hl + u_hl + m_bin + u_l + cash

    def flatten_to_cash(i, extra_fee=0.0):
        """Move current equity into cash residual; clear position state."""
        nonlocal in_pos, m_hl, m_bin, standby, cash, e_hl, e_b, pend_i
        eq = eq_now(i) - extra_fee
        cash = eq - capital
        m_hl = m_bin = standby = 0.0
        e_hl = e_b = 0.0
        in_pos = False
        pend_i = -1

    for i in range(T):
        if i > 0 and day[i] != day[i - 1]:
            daily_eq[day[i - 1]] = last_eq

        if not in_pos:
            if i >= flat_until and valid[i]:
                e_hl = hl[i]; e_b = long_px(i)
                m_hl = im_h; m_bin = im_b; standby = standby0
                cash -= (fee_h + fee_b + leg) * n
                in_pos = True; n_entry += 1
            last_eq = eq_now(i)
            if day[i] == oct_day:
                oct_path.append((idx[i], np.nan, np.nan, last_eq, 0))
            continue

        if not valid[i]:
            n_gap += 1
            flatten_to_cash(max(i - 1, 0), extra_fee=(fee_h + fee_b + leg) * n)
            # prereg §4: gap flats re-enter as soon as both series resume (no 24h wait)
            flat_until = i
            events.append({"t": str(idx[i]), "reason": "gap_flat"})
            last_eq = eq_now(i)
            continue

        # funding
        if hf[i]:
            m_hl += n * hf[i]
        if (not use_spot) and bfnd[i]:
            m_bin -= n * bfnd[i]

        # transfer credit
        if pend_i >= 0 and i >= pend_i:
            cash -= TRANSFER_COST
            if pend_dir == 1:
                m_hl += pend_amt
                if use_spot: standby -= pend_amt
                else: m_bin -= pend_amt
            else:
                m_bin += pend_amt; m_hl -= pend_amt
            n_rebal += 1; pend_i = -1
            events.append({"t": str(idx[i]), "reason": "rebal"})

        # ADL
        if adl and i == adl_i:
            n_adl += 1
            # close HL at mark (keep equity), close other next minute with fees
            # Step: realize full equity minus long exit fee at j
            j = min(i + 1, T - 1)
            # temporarily compute equity at i, then adjust long to j price
            u_hl = n * (1.0 - hl[i] / e_hl)
            if use_spot:
                u_l = n * (sc[j] / e_b - 1.0) if valid[j] else n * (sc[i] / e_b - 1.0)
                eq = m_hl + u_hl + n + u_l + standby + cash
            else:
                u_l = n * (bc[j] / e_b - 1.0) if valid[j] else n * (bc[i] / e_b - 1.0)
                eq = m_hl + u_hl + m_bin + u_l + cash
            eq -= (fee_b + leg) * n
            cash = eq - capital
            m_hl = m_bin = standby = 0.0
            e_hl = e_b = 0.0
            in_pos = False; pend_i = -1
            flat_until = j + FLAT_MIN
            events.append({"t": str(idx[i]), "reason": "ADL"})
            last_eq = capital + cash
            if day[i] == oct_day:
                oct_path.append((idx[i], np.nan, np.nan, last_eq, 0))
            continue

        # liquidation checks
        u_hl_m = n * (1.0 - hl[i] / e_hl)
        eq_h = m_hl + u_hl_m
        n_m_h = n * (hl[i] / e_hl)
        liq_side = None
        if eq_h < mmr_h * n_m_h:
            liq_side = "HL"
        elif not use_spot:
            u_adv = n * (bl[i] / e_b - 1.0)
            eq_b = m_bin + u_adv
            n_m_b = n * (bl[i] / e_b)
            if eq_b < mmr_b * n_m_b:
                liq_side = "BIN"

        if liq_side:
            n_liq += 1
            j = min(i + 1, T - 1)
            if liq_side == "HL":
                # wipe HL equity to 0; close long at j
                if use_spot:
                    u_l = n * ((sc[j] if valid[j] else sc[i]) / e_b - 1.0)
                    eq = 0.0 + n + u_l + standby + cash  # HL wiped
                else:
                    u_l = n * ((bc[j] if valid[j] else bc[i]) / e_b - 1.0)
                    eq = 0.0 + m_bin + u_l + cash
                eq -= (fee_b + leg) * n
            else:
                # wipe BIN; close HL at j
                u_h = n * (1.0 - (hl[j] if valid[j] else hl[i]) / e_hl)
                eq = m_hl + u_h + 0.0 + cash
                eq -= (fee_h + leg) * n
                eq -= BIN_LIQ_FEE * n
            cash = eq - capital
            m_hl = m_bin = standby = 0.0
            e_hl = e_b = 0.0
            in_pos = False; pend_i = -1
            flat_until = j + FLAT_MIN
            events.append({"t": str(idx[i]), "reason": f"LIQ_{liq_side}"})
            last_eq = capital + cash
            if day[i] == oct_day:
                oct_path.append((idx[i], np.nan, np.nan, last_eq, 0))
            continue

        # rebalance — need restores weak leg to MR=1/L using MTM equity (prereg §7)
        if pend_i < 0:
            eq_h = m_hl + n * (1.0 - hl[i] / e_hl)
            n_m_h = n * (hl[i] / e_hl)
            if n_m_h > 0 and eq_h < REBAL_MULT * mmr_h * n_m_h:
                target = (1.0 / L) * n_m_h
                need = max(0.0, target - eq_h)
                if use_spot:
                    donor_cap = max(0.0, standby)
                    surplus = donor_cap
                else:
                    eq_b_mtm = m_bin + n * (bc[i] / e_b - 1.0)
                    n_m_b = n * (bc[i] / e_b)
                    floor_b = (1.0 / L) * n_m_b
                    surplus = max(0.0, eq_b_mtm - floor_b)
                    donor_cap = max(0.0, m_bin)  # cannot pull more than wallet
                amt = min(need, surplus, donor_cap)
                if amt > 1.0:
                    pend_i = i + TRANSFER_DELAY; pend_amt = amt; pend_dir = 1
            elif not use_spot:
                eq_b = m_bin + n * (bc[i] / e_b - 1.0)
                n_m_b = n * (bc[i] / e_b)
                if n_m_b > 0 and eq_b < REBAL_MULT * mmr_b * n_m_b:
                    target = (1.0 / L) * n_m_b
                    need = max(0.0, target - eq_b)
                    eq_h_mtm = m_hl + n * (1.0 - hl[i] / e_hl)
                    floor_h = (1.0 / L) * n_m_h
                    surplus = max(0.0, eq_h_mtm - floor_h)
                    donor_cap = max(0.0, m_hl)
                    amt = min(need, surplus, donor_cap)
                    if amt > 1.0:
                        pend_i = i + TRANSFER_DELAY; pend_amt = amt; pend_dir = -1

        last_eq = eq_now(i)
        if day[i] == oct_day:
            mr_h = eq_h / n_m_h if n_m_h else np.nan
            if use_spot:
                mr_b = np.nan
            else:
                eq_b = m_bin + n * (bc[i] / e_b - 1.0)
                mr_b = eq_b / (n * bc[i] / e_b)
            oct_path.append((idx[i], mr_h, mr_b, last_eq, 1))

    if in_pos:
        flatten_to_cash(T - 1, extra_fee=(fee_h + fee_b + leg) * n)
        last_eq = capital + cash
    daily_eq[day[T - 1]] = last_eq

    eq = pd.Series(daily_eq).sort_index()
    o0 = pd.Timestamp("2025-10-10", tz="UTC")
    o1 = pd.Timestamp("2025-10-11", tz="UTC")
    prev = eq[eq.index < o0]
    base = float(prev.iloc[-1]) if len(prev) else capital
    during = eq[(eq.index >= o0) & (eq.index < o1)]
    oct_pnl = ((float(during.iloc[-1]) if len(during) else base) - base) / capital

    return {
        "coin": coin, "strategy": strategy, "leverage": L, "adl": adl, "n": n,
        "capital": capital, "final_equity": float(eq.iloc[-1]),
        "total_ret": (float(eq.iloc[-1]) - capital) / capital,
        "n_liq": n_liq, "n_rebal": n_rebal, "n_adl": n_adl, "n_gapflat": n_gap, "n_entry": n_entry,
        "IS": ann_window(eq, capital, START, SPLIT),
        "OOS": ann_window(eq, capital, SPLIT, END),
        "FULL": ann_window(eq, capital, START, END),
        "oct10_pnl_frac": oct_pnl,
        "eq_series": eq,
        "oct10_path": oct_path,
        "events": events,
    }


def portfolio(sleeves):
    series = [r["eq_series"] for r in sleeves]
    eq = sum(series)
    capital = sum(r["capital"] for r in sleeves)
    o0 = pd.Timestamp("2025-10-10", tz="UTC")
    o1 = pd.Timestamp("2025-10-11", tz="UTC")
    prev = eq[eq.index < o0]
    base = float(prev.iloc[-1]) if len(prev) else capital
    during = eq[(eq.index >= o0) & (eq.index < o1)]
    oct_pnl = ((float(during.iloc[-1]) if len(during) else base) - base) / capital
    return {
        "capital": capital, "eq": eq,
        "IS": ann_window(eq, capital, START, SPLIT),
        "OOS": ann_window(eq, capital, SPLIT, END),
        "FULL": ann_window(eq, capital, START, END),
        "oct10_pnl_frac": oct_pnl,
        "n_liq": sum(r["n_liq"] for r in sleeves),
        "n_rebal": sum(r["n_rebal"] for r in sleeves),
        "n_adl": sum(r["n_adl"] for r in sleeves),
    }
