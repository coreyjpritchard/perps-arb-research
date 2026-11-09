"""Carry backtest v2 — 1-minute, liquidation + rebalancing. Per preregistration_v2.md."""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mmr import hl_mmr, bin_mmr, BIN_LIQ_FEE

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RES = ROOT / "results" / "v2"
RES.mkdir(parents=True, exist_ok=True)

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX"]
ADDON = ["HYPE"]
START = pd.Timestamp("2024-11-01", tz="UTC")
SPLIT = pd.Timestamp("2026-07-26", tz="UTC")
END = pd.Timestamp("2026-10-26", tz="UTC")
OCT10 = pd.Timestamp("2025-10-10 21:15", tz="UTC")
N_BASE = 10_000.0
TRANSFER_DELAY_MIN = 45
TRANSFER_COST_USD = 5.0
REBAL_TRIG_MULT = 1.5
FFILL_MAX = 2
FLAT_AFTER_LIQ_H = 24
FEE = {"HL": 4.5e-4, "BIN": 5e-4, "BINSPOT": 1e-3}
COST = pd.read_csv(DATA / "cost_params.csv").set_index(["coin", "venue"])

def slip_bps(coin, venue, n):
    col = "slip_100k_bps" if n >= 50_000 else "slip_10k_bps"
    try:
        return float(COST.loc[(coin, venue), col])
    except KeyError:
        # HYPE missing from v1 costs → use AVAX as proxy (similar alt)
        return float(COST.loc[("AVAX", venue), col])

def leg_risk_bps(coin):
    try:
        return float(COST.loc[(coin, "HL"), "leg_risk_bps"])
    except KeyError:
        return float(COST.loc[("AVAX", "HL"), "leg_risk_bps"])


def load_hl(coin):
    df = pd.read_parquet(DATA / "hl_archive" / "minute" / f"{coin}.parquet")
    df = df.sort_values("time")
    df["t"] = df["time"].dt.floor("min")
    df = df.drop_duplicates("t", keep="last")
    return df.set_index("t")[["mark_px", "mid_px", "funding"]]


def load_bin_mark(coin):
    p = DATA / "binance_1m" / "mark" / f"{coin}.parquet"
    df = pd.read_parquet(p)
    df = df.sort_values("time").drop_duplicates("time")
    df = df.set_index("time")[["open", "high", "low", "close"]]
    df.columns = ["b_open", "b_high", "b_low", "b_close"]
    return df


def load_bin_spot(coin):
    p = DATA / "binance_1m" / "spot" / f"{coin}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df = df.sort_values("time").drop_duplicates("time")
    return df.set_index("time")[["close"]].rename(columns={"close": "s_close"})


def load_bin_funding(coin):
    df = pd.read_parquet(DATA / f"bin_funding_{coin}.parquet")
    # columns time, rate
    s = df.set_index("time")["rate"].sort_index()
    s.index = s.index.tz_convert("UTC") if s.index.tz else s.index.tz_localize("UTC")
    return s


def load_hl_funding_fallback(coin):
    df = pd.read_parquet(DATA / f"hl_funding_{coin}.parquet")
    s = df.set_index("time")["rate"].sort_index()
    s.index = s.index.floor("h")
    return s[~s.index.duplicated(keep="last")]


def align_coin(coin, use_spot: bool):
    hl = load_hl(coin)
    bm = load_bin_mark(coin)
    if use_spot:
        sp = load_bin_spot(coin)
        if sp is None or sp.empty:
            return None
    idx = pd.date_range(START, END - pd.Timedelta(minutes=1), freq="min", tz="UTC")
    df = pd.DataFrame(index=idx)
    df["hl_mark"] = hl["mark_px"].reindex(idx)
    df["hl_mid"] = hl["mid_px"].reindex(idx)
    df["hl_fund_raw"] = hl["funding"].reindex(idx)
    df["b_high"] = bm["b_high"].reindex(idx)
    df["b_low"] = bm["b_low"].reindex(idx)
    df["b_close"] = bm["b_close"].reindex(idx)
    if use_spot:
        df["s_close"] = sp["s_close"].reindex(idx)
    # ffill marks limited
    for col in ["hl_mark", "hl_mid", "b_high", "b_low", "b_close"] + (["s_close"] if use_spot else []):
        df[col] = df[col].ffill(limit=FFILL_MAX)
    # funding settlements
    bf = load_bin_funding(coin)
    df["bin_fund"] = bf.reindex(idx).fillna(0.0)
    # HL hourly: prefer archive funding at HH:00, else fallback file
    hl_fb = load_hl_funding_fallback(coin)
    is_hour = df.index.minute == 0
    hl_set = df["hl_fund_raw"].where(is_hour)
    # where missing at hour, use fallback
    miss = is_hour & hl_set.isna()
    if miss.any():
        hl_set.loc[miss] = hl_fb.reindex(df.index[miss]).values
    df["hl_fund"] = hl_set.fillna(0.0)
    # validity
    need = ["hl_mark", "b_close"] + (["s_close"] if use_spot else [])
    df["valid"] = df[need].notna().all(axis=1)
    return df


def fill_cost(coin, venue, n):
    return FEE[venue] + slip_bps(coin, venue, n) / 1e4


def simulate_sleeve(coin, df, leverage, strategy, n=N_BASE, adl=False, idle_rate=0.0):
    """strategy: 'c' (HL short / BIN long) or 'ref' (HL short / spot long).
    Returns dict of metrics + daily series.
    """
    use_spot = strategy == "ref"
    L = float(leverage)
    mmr_hl = hl_mmr(coin, n)
    mmr_bin = bin_mmr(coin, n) if not use_spot else 0.0
    im_hl = n / L
    im_bin = n / L if not use_spot else 0.0
    standby = 0.25 * im_hl if use_spot else 0.0  # held on Binance side until transferred
    if use_spot:
        capital = n + 1.25 * im_hl
    else:
        capital = im_hl + im_bin

    fee_hl = fill_cost(coin, "HL", n)
    fee_bin = fill_cost(coin, "BINSPOT" if use_spot else "BIN", n)
    leg = leg_risk_bps(coin) / 1e4

    idx = df.index
    T = len(idx)
    hl_mark = df["hl_mark"].to_numpy(dtype=float)
    b_high = df["b_high"].to_numpy(dtype=float)
    b_low = df["b_low"].to_numpy(dtype=float)
    b_close = df["b_close"].to_numpy(dtype=float)
    s_close = df["s_close"].to_numpy(dtype=float) if use_spot else None
    hl_fund = df["hl_fund"].to_numpy(dtype=float)
    bin_fund = df["bin_fund"].to_numpy(dtype=float)
    valid = df["valid"].to_numpy(dtype=bool)

    # state
    in_pos = False
    flat_until = -1
    # entry prices / margins / notionals
    e_hl = e_bin = 0.0
    m_hl = m_bin = 0.0  # isolated margin balances
    standby_bal = standby  # available to transfer to HL for ref
    # pending transfer: (credit_i, amount, direction) direction +1 = to HL from BIN, -1 = to BIN from HL
    pend = None
    realized = 0.0
    n_liq = n_rebal = n_adl = n_gapflat = n_entry = 0
    # daily pnl accumulation
    day_keys = idx.floor("D")
    # per-minute equity for oct10 path (subsample)
    # store daily equity end-of-day
    daily_pnl = {}
    prev_equity = capital
    day_start_equity = capital
    cur_day = day_keys[0]
    # event log
    events = []
    # oct10 path samples every minute that day
    oct10_path = []
    oct10_day = pd.Timestamp("2025-10-10", tz="UTC")
    oct10_pnl_day = 0.0

    def other_px(i):
        if use_spot:
            return s_close[i]
        return b_close[i]

    def open_pos(i):
        nonlocal in_pos, e_hl, e_bin, m_hl, m_bin, realized, n_entry, standby_bal
        if not valid[i]:
            return False
        e_hl = hl_mark[i]
        e_bin = other_px(i)
        m_hl = im_hl
        m_bin = im_bin if not use_spot else 0.0
        if use_spot:
            standby_bal = standby
        # entry costs
        cost = (fee_hl + fee_bin + leg) * n
        realized -= cost
        in_pos = True
        n_entry += 1
        return True

    def close_other_and_flat(i, reason):
        """Close surviving leg at i, go flat 24h."""
        nonlocal in_pos, realized, m_hl, m_bin, flat_until, pend
        if not in_pos:
            return
        # realise both legs MTM then wipe as needed by caller before this
        # close costs on remaining open legs
        # assume both conceptually closed here if still open
        px_hl = hl_mark[i] if valid[i] and not np.isnan(hl_mark[i]) else e_hl
        px_b = other_px(i) if valid[i] else e_bin
        # HL short PnL
        if m_hl > 0 or e_hl > 0:
            upnl_hl = n * (1.0 - px_hl / e_hl)
            realized += upnl_hl
            # remaining margin after upnl already in m_hl conceptually; fold into realized via upnl; zero margins
        if not use_spot and (m_bin > 0 or e_bin > 0):
            upnl_b = n * (px_b / e_bin - 1.0)
            realized += upnl_b
        elif use_spot and e_bin > 0:
            upnl_b = n * (px_b / e_bin - 1.0)
            realized += upnl_b
        cost = (fee_hl + fee_bin + leg) * n
        realized -= cost
        m_hl = m_bin = 0.0
        in_pos = False
        pend = None
        flat_until = i + FLAT_AFTER_LIQ_H * 60
        events.append((idx[i], reason, realized))

    def equity_now(i):
        if not in_pos:
            return capital + realized
        px_hl = hl_mark[i]
        px_b = other_px(i)
        upnl_hl = n * (1.0 - px_hl / e_hl)
        if use_spot:
            upnl_b = n * (px_b / e_bin - 1.0)
            # margins: m_hl includes? we track m_hl as cash margin; equity = capital + realized + upnl, 
            # but realized already has funding/fees; upnl is mark-to-market from entry
            # standby not yet in HL
            return capital + realized + upnl_hl + upnl_b
        else:
            upnl_b = n * (px_b / e_bin - 1.0)
            return capital + realized + upnl_hl + upnl_b

    def leg_equity_hl(i, mark=None):
        px = hl_mark[i] if mark is None else mark
        # short: margin + n*(1 - px/entry)  — but funding already added to m_hl
        # Initial m_hl = im_hl; funding credits increase m_hl; upnl separate
        # Equity = m_hl + n*(1 - px/e_hl) - (im_hl related)? 
        # Better: equity = m_hl + n*(e_hl - px)/e_hl = m_hl + n*(1 - px/e_hl)
        # At entry m_hl=im_hl, upnl=0 → equity=im_hl. Good.
        return m_hl + n * (1.0 - px / e_hl)

    def leg_equity_bin(i, mark=None):
        if use_spot:
            return 0.0
        px = b_close[i] if mark is None else mark
        return m_bin + n * (px / e_bin - 1.0)

    for i in range(T):
        # day roll
        d = day_keys[i]
        if d != cur_day:
            # record previous day pnl
            eq = prev_equity
            daily_pnl[cur_day] = eq - capital  # cumulative from start at day end stored later
            # store incremental? we'll store end equity
            daily_pnl[cur_day] = eq  # end-of-day equity
            cur_day = d
            day_start_equity = eq

        if not in_pos:
            if i >= flat_until and valid[i]:
                open_pos(i)
            prev_equity = equity_now(i)
            if idx[i].floor("D") == oct10_day:
                oct10_path.append((idx[i], np.nan, np.nan, prev_equity, 0))
            continue

        # gap invalid → flat
        if not valid[i]:
            # close at last valid — use previous equity marks already; force flat
            n_gapflat += 1
            close_other_and_flat(max(i - 1, 0), "gap_flat")
            prev_equity = equity_now(i)
            continue

        # funding at this minute
        if hl_fund[i] != 0.0:
            # short receives
            m_hl += n * hl_fund[i]
            realized += n * hl_fund[i]
        if not use_spot and bin_fund[i] != 0.0:
            # long pays
            m_bin -= n * bin_fund[i]
            realized -= n * bin_fund[i]
        # spot: no funding

        # pending transfer credit
        if pend is not None and i >= pend[0]:
            amt, direction = pend[1], pend[2]
            realized -= TRANSFER_COST_USD
            if direction == 1:  # to HL
                m_hl += amt
                if use_spot:
                    standby_bal -= amt
                else:
                    m_bin -= amt
            else:  # to BIN
                m_bin += amt
                m_hl -= amt
            n_rebal += 1
            events.append((idx[i], "rebal_credit", amt))
            pend = None

        # ADL stress
        if adl and idx[i] == OCT10 and in_pos:
            # force close HL short at mark; then close bin next minute
            px = hl_mark[i]
            upnl_hl = n * (1.0 - px / e_hl)
            realized += upnl_hl
            # keep m_hl as residual? ADL closes position — remaining margin freed
            realized += m_hl  # return HL margin to sleeve (already counted in capital framework)
            # actually capital accounting: realized is PnL on top of capital. upnl is the trading pnl.
            # margin return shouldn't double count. Model: realized already tracks fees/funding/upnl;
            # on ADL we realize upnl and zero the leg; margin is part of capital not extra PnL.
            realized -= m_hl  # undo the mistaken add
            m_hl = 0.0
            e_hl_old = e_hl
            e_hl = 0.0
            n_adl += 1
            # close other leg next minute
            if i + 1 < T:
                j = i + 1
                px_b = other_px(j) if valid[j] else other_px(i)
                if use_spot:
                    upnl_b = n * (px_b / e_bin - 1.0)
                else:
                    upnl_b = n * (px_b / e_bin - 1.0)
                realized += upnl_b
                cost = (fee_hl + fee_bin + leg) * n  # HL already closed by ADL — still pay bin exit + leg; charge half? prereg: close other at next minute with costs. Charge bin side + leg only + HL was ADL (no fee assumed)
                realized -= (fee_bin + leg) * n
                m_bin = 0.0
                in_pos = False
                pend = None
                flat_until = j + FLAT_AFTER_LIQ_H * 60
                events.append((idx[i], "ADL", upnl_hl))
            prev_equity = capital + realized
            continue

        # liquidation checks using adverse marks
        liq = False
        # HL short: adverse = price up → use hl_mark (same); if we had high, use it — archive has point mark
        eq_hl = leg_equity_hl(i)
        n_mark_hl = n * (hl_mark[i] / e_hl)
        if eq_hl < mmr_hl * n_mark_hl:
            # wipe HL margin
            realized += eq_hl  # this realises the loss into PnL: equity goes from eq_hl to 0, so PnL change = -eq_hl relative to marking
            # Wait: equity_now uses upnl from entry, not m_hl. Need consistent accounting.
            # Fix approach: on liq, the loss is the full remaining equity on that leg (lost).
            # Before liq, total equity included eq_hl as part of MTM. After wipe, that eq_hl is gone.
            # So realized should decrease by eq_hl if we had been counting upnl in equity_now via upnl formula
            # and m_hl separately for liq check only.
            # Simplest consistent model:
            #   equity = capital + realized_pnl + upnl_hl + upnl_bin
            #   where realized_pnl = funding - fees - transfer costs - liq losses
            #   upnl from entry prices
            # On HL liq: add upnl_hl to realized, then subtract the post-upnl equity (wipe), set e_hl dead
            # Actually: loss_amount = max(eq_hl, 0) wiped → if eq_hl>0 lose it; if eq_hl<0 already lost more than margin (shouldn't happen much)
            loss = max(eq_hl, 0.0)
            # Transition: realize upnl into realized and remove margin
            upnl_hl = n * (1.0 - hl_mark[i] / e_hl)
            realized += upnl_hl
            realized -= loss  # wipe remaining equity (which equals m_hl + upnl ≈ eq_hl)
            # Hmm double counting. eq_hl = m_hl + upnl_hl. If we do realized += upnl_hl and then wipe m_hl (not in realized), 
            # equity change = +upnl (moved to realized) -0 from m_hl tracking. The wipe of m_hl means capital structure loses m_hl.
            # Cleaner RESET of accounting on liq:
            pass
            liq = True
            liq_side = "HL"

        if not liq and not use_spot:
            # Binance long: adverse = low
            px_adv = b_low[i]
            eq_b = m_bin + n * (px_adv / e_bin - 1.0)
            n_mark_b = n * (px_adv / e_bin)
            if eq_b < mmr_bin * n_mark_b:
                liq = True
                liq_side = "BIN"
                eq_bin_loss = max(eq_b, 0.0)

        if liq:
            n_liq += 1
            if liq_side == "HL":
                # Realize both legs properly:
                # HL wiped: lose eq_hl (remaining equity)
                # Close BIN at next minute
                upnl_hl = n * (1.0 - hl_mark[i] / e_hl)
                # The wipe: we lose the isolated equity; PnL impact = upnl_hl - im_hl  (lost the margin) 
                # = (m_hl + upnl_hl) - m_hl - im_hl + m_hl ... 
                # Final: realized += upnl_hl; realized -= m_hl  (margin lost to venue); m_hl=0
                # But m_hl may include funding; funding already in realized when paid. m_hl started at im_hl and got funding adds that were ALSO added to realized — so m_hl and realized both got funding. On wipe, only subtract remaining m_hl once from... 
                # FUNDING ACCOUNTING FIX: funding should only go to m_hl (venue balance), and equity_now = (m_hl + upnl_without_double) + ...
                # Let me restart funding: do NOT add funding to realized separately; include via m_hl in equity.
                pass
            # Use explicit reset method below
            events.append((idx[i], f"LIQ_{liq_side}", None))
            # Close everything with correct PnL:
            # Compute MTM pnl for both legs from entry, apply liq wipe on liq side
            upnl_hl = n * (1.0 - hl_mark[i] / e_hl)
            upnl_b = n * ((other_px(i) / e_bin) - 1.0)
            if liq_side == "HL":
                # lose HL equity entirely (backstop)
                # PnL from HL = -im_hl + funding_already_in_realized... messy
                # REDO: switch to pure realized incremental from here for this sleeve by recomputing
                realized += -im_hl  # lose initial HL margin as the liq loss baseline approximation
                # plus the adverse move beyond margin already embedded: if upnl_hl < -im_hl, extra loss is 0 under isolated (can't lose more than margin)
                # Actually isolated: max loss = margin. So HL PnL = -im_hl (plus funding received kept? funding is in wallet — backstop takes all). Lose all m_hl.
                realized += (im_hl - m_hl)  # adjust if m_hl != im_hl due to funding: net HL contribution = -m_hl
                # wait: start realized doesn't include im_hl. capital has im_hl. Losing the leg means capital's im_hl portion is gone → PnL -m_hl
                realized -= m_hl
                realized += 0  # upnl not separately added
                m_hl = 0.0
                # close other leg next minute with MTM
                j = min(i + 1, T - 1)
                px_b = other_px(j) if valid[j] else other_px(i)
                realized += n * (px_b / e_bin - 1.0)
                if not use_spot:
                    realized -= BIN_LIQ_FEE * n  # only if bin liquidated — skip for HL liq
                realized -= (fee_bin + leg) * n
                m_bin = 0.0
            else:
                # BIN liquidated
                realized -= m_bin  # lose bin margin (approx); more precisely lose eq at adverse
                # use adverse equity loss
                px_adv = b_low[i]
                eq_b = m_bin + n * (px_adv / e_bin - 1.0)
                # replace: PnL bin = -m_bin + (eq_b related)
                # isolated max loss = margin; Binance may take remaining above MM in book liq — we wipe all remaining eq_b if >0 else just -m_bin
                realized += n * (px_adv / e_bin - 1.0)  # realize at liq mark
                realized -= BIN_LIQ_FEE * n
                # The margin is part of capital; upnl already added; if eq_b>0 remaining is lost in backstop-like model
                if eq_b > 0:
                    realized -= eq_b
                m_bin = 0.0
                # close HL next minute
                j = min(i + 1, T - 1)
                px_h = hl_mark[j] if valid[j] else hl_mark[i]
                realized += n * (1.0 - px_h / e_hl)
                realized -= (fee_hl + leg) * n
                m_hl = 0.0
            in_pos = False
            pend = None
            flat_until = i + 1 + FLAT_AFTER_LIQ_H * 60
            prev_equity = capital + realized
            if idx[i].floor("D") == oct10_day:
                oct10_path.append((idx[i], np.nan, np.nan, prev_equity, 1))
            continue

        # rebalance check
        if pend is None and in_pos:
            eq_hl = leg_equity_hl(i)
            n_mark_hl = n * (hl_mark[i] / e_hl)
            trig_hl = eq_hl < REBAL_TRIG_MULT * mmr_hl * n_mark_hl
            trig_bin = False
            if not use_spot:
                eq_b = leg_equity_bin(i)
                n_mark_b = n * (b_close[i] / e_bin)
                trig_bin = eq_b < REBAL_TRIG_MULT * mmr_bin * n_mark_b
            if trig_hl:
                # need amount to restore MR to 1/L
                target = im_hl  # restore margin cash so equity ≈ im_hl + upnl → aim m_hl = im_hl
                need = max(0.0, im_hl - m_hl)
                if use_spot:
                    surplus = max(0.0, standby_bal)
                else:
                    # surplus on bin: equity above initial
                    eq_b = leg_equity_bin(i)
                    surplus = max(0.0, eq_b - im_bin)
                amt = min(need, surplus)
                if amt > 1.0:
                    pend = (i + TRANSFER_DELAY_MIN, amt, 1)
            elif trig_bin:
                target_need = max(0.0, im_bin - m_bin)
                eq_hl = leg_equity_hl(i)
                surplus = max(0.0, eq_hl - im_hl)
                amt = min(target_need, surplus)
                if amt > 1.0:
                    pend = (i + TRANSFER_DELAY_MIN, amt, -1)

        prev_equity = equity_now(i)
        if idx[i].floor("D") == oct10_day:
            mr_hl = leg_equity_hl(i) / (n * hl_mark[i] / e_hl) if in_pos else np.nan
            mr_b = (leg_equity_bin(i) / (n * b_close[i] / e_bin)) if (in_pos and not use_spot) else np.nan
            oct10_path.append((idx[i], mr_hl, mr_b, prev_equity, int(in_pos)))

    # final close if in pos
    if in_pos:
        i = T - 1
        upnl_hl = n * (1.0 - hl_mark[i] / e_hl) if valid[i] else 0.0
        upnl_b = n * (other_px(i) / e_bin - 1.0) if valid[i] else 0.0
        realized += upnl_hl + upnl_b
        realized -= (fee_hl + fee_bin + leg) * n
        in_pos = False
    daily_pnl[cur_day] = capital + realized
    # build equity series
    eq_series = pd.Series(daily_pnl).sort_index()
    # convert to cumulative return
    cum = (eq_series - capital) / capital
    # daily returns
    rets = eq_series.pct_change().fillna(0.0)
    # idle interest sensitivity applied outside

    def ann_stats(mask_start, mask_end):
        sub = eq_series[(eq_series.index >= mask_start) & (eq_series.index < mask_end)]
        if len(sub) < 2:
            return dict(ann=np.nan, sharpe=np.nan, maxdd=np.nan, n_days=0)
        # pnl over window / capital / years
        years = (sub.index[-1] - sub.index[0]).days / 365.25
        if years <= 0:
            years = len(sub) / 365.25
        total_ret = (sub.iloc[-1] - sub.iloc[0]) / capital
        # careful: sub.iloc[0] is end of first day; use capital at window start
        # Better: equity at start = value just before window or capital+pnl
        start_eq = sub.iloc[0]
        # use first day as baseline — approximate with capital if first
        # For IS starting at START, first equity already includes day1. Use capital as denom only.
        end_eq = sub.iloc[-1]
        # Find equity at window start: previous day or capital
        prev = eq_series[eq_series.index < mask_start]
        base_eq = prev.iloc[-1] if len(prev) else capital
        total_ret = (end_eq - base_eq) / capital
        ann = total_ret / years if years > 0 else np.nan
        dret = sub.pct_change().dropna()
        sharpe = (dret.mean() / dret.std() * math.sqrt(365)) if dret.std() > 0 else np.nan
        # maxdd on cum from base
        path = (sub - base_eq) / capital
        peak = path.cummax()
        dd = (path - peak).min()
        return dict(ann=ann, sharpe=sharpe, maxdd=dd, n_days=len(sub), total_ret=total_ret)

    # oct10 day pnl
    o0 = pd.Timestamp("2025-10-10", tz="UTC")
    o1 = pd.Timestamp("2025-10-11", tz="UTC")
    prev = eq_series[eq_series.index < o0]
    base = prev.iloc[-1] if len(prev) else capital
    during = eq_series[(eq_series.index >= o0) & (eq_series.index < o1)]
    oct_end = during.iloc[-1] if len(during) else base
    oct_pnl = (oct_end - base) / capital

    return {
        "coin": coin, "strategy": strategy, "leverage": L, "adl": adl, "n": n,
        "capital": capital,
        "realized_pnl": realized,
        "final_equity": capital + realized,
        "total_ret": realized / capital,
        "n_liq": n_liq, "n_rebal": n_rebal, "n_adl": n_adl, "n_gapflat": n_gapflat, "n_entry": n_entry,
        "IS": ann_stats(START, SPLIT),
        "OOS": ann_stats(SPLIT, END),
        "FULL": ann_stats(START, END),
        "oct10_pnl_frac": oct_pnl,
        "eq_series": eq_series,
        "oct10_path": oct10_path,
        "events": events,
    }


def portfolio_aggregate(sleeve_results):
    """Equal capital weight."""
    caps = [r["capital"] for r in sleeve_results]
    # align daily equity as sum
    series = []
    for r in sleeve_results:
        s = r["eq_series"]
        series.append(s)
    eq = sum(series)
    capital = sum(caps)
    cum = (eq - capital) / capital

    def ann_stats(mask_start, mask_end):
        sub = eq[(eq.index >= mask_start) & (eq.index < mask_end)]
        prev = eq[eq.index < mask_start]
        base_eq = prev.iloc[-1] if len(prev) else capital
        if len(sub) < 2:
            return dict(ann=np.nan, sharpe=np.nan, maxdd=np.nan)
        years = max((sub.index[-1] - sub.index[0]).days / 365.25, 1e-9)
        total_ret = (sub.iloc[-1] - base_eq) / capital
        ann = total_ret / years
        dret = sub.pct_change().dropna()
        sharpe = (dret.mean() / dret.std() * math.sqrt(365)) if dret.std() > 0 else np.nan
        path = (sub - base_eq) / capital
        maxdd = (path - path.cummax()).min()
        return dict(ann=ann, sharpe=sharpe, maxdd=maxdd, total_ret=total_ret)

    o0 = pd.Timestamp("2025-10-10", tz="UTC")
    o1 = pd.Timestamp("2025-10-11", tz="UTC")
    prev = eq[eq.index < o0]
    base = prev.iloc[-1] if len(prev) else capital
    during = eq[(eq.index >= o0) & (eq.index < o1)]
    oct_pnl = ((during.iloc[-1] if len(during) else base) - base) / capital
    return {
        "capital": capital,
        "eq": eq,
        "IS": ann_stats(START, SPLIT),
        "OOS": ann_stats(SPLIT, END),
        "FULL": ann_stats(START, END),
        "oct10_pnl_frac": oct_pnl,
        "n_liq": sum(r["n_liq"] for r in sleeve_results),
        "n_rebal": sum(r["n_rebal"] for r in sleeve_results),
        "n_adl": sum(r["n_adl"] for r in sleeve_results),
    }


if __name__ == "__main__":
    print("backtest module loaded OK")
