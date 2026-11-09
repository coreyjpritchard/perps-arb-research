"""PnL decomposition for one sleeve — funding, fees, liq, gap, rebal, residual."""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pandas as pd
from engine import (
    load_aligned, FEE, _slip, _leg, N_BASE, START, END, SPLIT,
    TRANSFER_DELAY, TRANSFER_COST, REBAL_MULT, FLAT_MIN, OCT10_ADL,
)
from mmr import hl_mmr, bin_mmr, BIN_LIQ_FEE

def decompose(coin, leverage, strategy="c", gap_mode="hold", n=N_BASE, adl=False):
    use_spot = strategy == "ref"
    df = load_aligned(coin, use_spot=use_spot, gap_mode=gap_mode)
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
    bc = df["b_close"].to_numpy(dtype=np.float64)
    sc = df["s_close"].to_numpy(dtype=np.float64)
    hf = df["hl_fund"].to_numpy(dtype=np.float64)
    bfnd = df["bin_fund"].to_numpy(dtype=np.float64)
    valid = df["valid"].to_numpy()
    adl_i = int(idx.get_indexer([OCT10_ADL], method="nearest")[0]) if adl else -1

    in_pos = False
    flat_until = 0
    e_hl = e_b = 0.0
    m_hl = m_bin = standby = cash = 0.0
    pend_i = -1; pend_amt = 0.0; pend_dir = 0
    n_liq = n_rebal = n_gap = n_entry = 0

    fund_hl = fund_bin = 0.0
    fees = slip_leg = 0.0  # combined fee+slip+leg charged
    liq_loss = 0.0
    rebal_cost = 0.0
    gap_cost = 0.0

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

    for i in range(T):
        if not in_pos:
            if i >= flat_until and valid[i]:
                e_hl = hl[i]; e_b = long_px(i)
                m_hl = im_h; m_bin = im_b; standby = standby0
                cost = (fee_h + fee_b + leg) * n
                cash -= cost; fees += cost
                in_pos = True; n_entry += 1
            continue

        if not valid[i]:
            n_gap += 1
            cost = (fee_h + fee_b + leg) * n
            eq = eq_now(max(i - 1, 0)) - cost
            gap_cost += cost
            cash = eq - capital
            m_hl = m_bin = standby = 0.0
            e_hl = e_b = 0.0
            in_pos = False; pend_i = -1
            flat_until = i
            continue

        if hf[i]:
            pnl = n * hf[i]; m_hl += pnl; fund_hl += pnl
        if (not use_spot) and bfnd[i]:
            pnl = -n * bfnd[i]; m_bin += pnl; fund_bin += pnl  # fund_bin is PnL (negative = paid)

        if pend_i >= 0 and i >= pend_i:
            cash -= TRANSFER_COST; rebal_cost += TRANSFER_COST
            if pend_dir == 1:
                m_hl += pend_amt
                if use_spot: standby -= pend_amt
                else: m_bin -= pend_amt
            else:
                m_bin += pend_amt; m_hl -= pend_amt
            n_rebal += 1; pend_i = -1

        if adl and i == adl_i:
            j = min(i + 1, T - 1)
            u_hl = n * (1.0 - hl[i] / e_hl)
            if use_spot:
                u_l = n * ((sc[j] if valid[j] else sc[i]) / e_b - 1.0)
                eq = m_hl + u_hl + n + u_l + standby + cash
            else:
                u_l = n * ((bc[j] if valid[j] else bc[i]) / e_b - 1.0)
                eq = m_hl + u_hl + m_bin + u_l + cash
            cost = (fee_b + leg) * n
            eq -= cost; fees += cost
            cash = eq - capital
            m_hl = m_bin = standby = 0.0
            e_hl = e_b = 0.0
            in_pos = False; pend_i = -1
            flat_until = j + FLAT_MIN
            continue

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
            eq_before = eq_now(i)
            if liq_side == "HL":
                wiped = max(0.0, eq_h)
                if use_spot:
                    u_l = n * ((sc[j] if valid[j] else sc[i]) / e_b - 1.0)
                    eq = 0.0 + n + u_l + standby + cash
                else:
                    u_l = n * ((bc[j] if valid[j] else bc[i]) / e_b - 1.0)
                    eq = 0.0 + m_bin + u_l + cash
                cost = (fee_b + leg) * n
                eq -= cost; fees += cost
                liq_loss += wiped
            else:
                wiped = max(0.0, m_bin + n * (bl[i] / e_b - 1.0))
                u_h = n * (1.0 - (hl[j] if valid[j] else hl[i]) / e_hl)
                eq = m_hl + u_h + 0.0 + cash
                cost = (fee_h + leg) * n + BIN_LIQ_FEE * n
                eq -= cost; fees += cost
                liq_loss += wiped + BIN_LIQ_FEE * n
            cash = eq - capital
            m_hl = m_bin = standby = 0.0
            e_hl = e_b = 0.0
            in_pos = False; pend_i = -1
            flat_until = j + FLAT_MIN
            continue

        if pend_i < 0:
            if n_m_h > 0 and eq_h < REBAL_MULT * mmr_h * n_m_h:
                target = (1.0 / L) * n_m_h
                need = max(0.0, target - eq_h)
                if use_spot:
                    donor_cap = max(0.0, standby); surplus = donor_cap
                else:
                    eq_b_mtm = m_bin + n * (bc[i] / e_b - 1.0)
                    floor_b = (1.0 / L) * (n * bc[i] / e_b)
                    surplus = max(0.0, eq_b_mtm - floor_b)
                    donor_cap = max(0.0, m_bin)
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

    if in_pos:
        cost = (fee_h + fee_b + leg) * n
        eq = eq_now(T - 1) - cost
        fees += cost
        cash = eq - capital
        in_pos = False

    final = capital + cash
    total_pnl = final - capital
    residual = total_pnl - (fund_hl + fund_bin - fees - liq_loss - rebal_cost - gap_cost)
    # note: liq_loss and gap_cost are not fully independent of final equity path;
    # residual captures basis/price-drift + accounting. Report components as tracked cash flows.
    return {
        "coin": coin, "leverage": L, "gap_mode": gap_mode, "capital": capital,
        "fund_hl": fund_hl, "fund_bin_pnl": fund_bin, "net_funding": fund_hl + fund_bin,
        "fees_slip_leg": fees, "liq_loss_tracked": liq_loss, "rebal_cost": rebal_cost,
        "gap_exit_cost": gap_cost, "total_pnl": total_pnl, "total_ret": total_pnl / capital,
        "n_liq": n_liq, "n_rebal": n_rebal, "n_gapflat": n_gap, "n_entry": n_entry,
        "residual_incl_basis": total_pnl - (fund_hl + fund_bin) + fees + rebal_cost,
        # residual_incl_basis ≈ basis + liq wealth effects + gap MTM at exit
    }


if __name__ == "__main__":
    rows = []
    for mode in ("flat", "hold"):
        for coin in ["BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX"]:
            print("decomp", mode, coin, flush=True)
            rows.append(decompose(coin, 1.0, "c", mode))
    df = pd.DataFrame(rows)
    out = Path(__file__).resolve().parents[2] / "results" / "v2" / "pnl_decomp_1x.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    # portfolio totals
    for mode in ("flat", "hold"):
        sub = df[df.gap_mode == mode]
        print(f"\n=== PORT {mode} 1x ===")
        for c in ["fund_hl","fund_bin_pnl","net_funding","fees_slip_leg","liq_loss_tracked","rebal_cost","gap_exit_cost","total_pnl"]:
            print(f"  {c}: {sub[c].sum():.2f}")
        print(f"  capital: {sub.capital.sum():.2f}  ret: {sub.total_pnl.sum()/sub.capital.sum():.4f}")
