"""
LBO / private equity returns modeling.

Pure Python — no numpy required. Covers:
  - Entry valuation and capital structure
  - Debt schedule with amortization and cash sweep
  - Operating model (revenue + EBITDA growth)
  - Exit at multiple expansion / compression
  - Returns: MOIC, IRR, equity bridge, cash-on-cash
  - Sensitivity tables (entry multiple × exit multiple, leverage × EBITDA growth)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class LBOInputs:
    # Entry
    revenue:          float        # LTM revenue ($M)
    ebitda_margin:    float        # as decimal, e.g. 0.25
    entry_multiple:   float        # EV / EBITDA at entry
    # Capital structure
    debt_ebitda:      float        # turns of leverage at entry
    interest_rate:    float = 0.08 # blended interest rate
    amort_pct:        float = 0.05 # % of initial debt amortized per year
    cash_sweep:       float = 0.50 # % of excess FCF applied to debt paydown
    # Operating assumptions
    revenue_growth:   float = 0.08 # CAGR
    margin_expansion: float = 0.00 # annual EBITDA margin improvement (pp)
    capex_pct_rev:    float = 0.03 # capex as % revenue
    nwc_pct_rev:      float = 0.05 # NWC as % revenue (change = cash drag)
    tax_rate:         float = 0.25
    da_pct_rev:       float = 0.02 # D&A as % revenue
    # Exit
    hold_years:       int   = 5
    exit_multiple:    float | None = None  # None = same as entry
    # Management / fees
    mgmt_fee_pct:     float = 0.02  # % of invested equity per year
    transaction_costs:float = 0.02  # % of TEV at entry and exit


@dataclass
class YearlyProjection:
    year: int
    revenue: float
    ebitda: float
    ebitda_margin: float
    da: float
    ebit: float
    interest: float
    ebt: float
    taxes: float
    net_income: float
    capex: float
    nwc_change: float
    fcf_pre_debt: float
    debt_amort: float
    cash_sweep_amt: float
    debt_end: float
    equity_value: float  # at current year if exiting


@dataclass
class LBOResult:
    # Entry
    entry_ebitda:     float
    entry_ev:         float
    entry_debt:       float
    entry_equity:     float
    transaction_fees: float
    total_equity_invested: float
    # Exit
    exit_year:        int
    exit_ebitda:      float
    exit_ev:          float
    exit_debt:        float
    exit_equity:      float
    exit_fees:        float
    net_exit_equity:  float
    # Returns
    moic:             float
    irr:              float
    cash_on_cash:     float
    # Detail
    projections:      list[YearlyProjection]
    debt_schedule:    list[dict]
    equity_bridge:    list[dict]
    sensitivity:      dict  # MOIC table keyed by scenario


# ── Core model ───────────────────────────────────────────────────────────────

def run_lbo(inp: LBOInputs) -> LBOResult:
    ebitda0 = inp.revenue * inp.ebitda_margin
    entry_ev = ebitda0 * inp.entry_multiple
    entry_debt = ebitda0 * inp.debt_ebitda
    entry_equity = entry_ev - entry_debt
    txn_fee_entry = entry_ev * inp.transaction_costs
    total_equity = entry_equity + txn_fee_entry

    debt = entry_debt
    rev = inp.revenue
    margin = inp.ebitda_margin
    prev_nwc = rev * inp.nwc_pct_rev
    projections: list[YearlyProjection] = []
    cumulative_mgmt_fees = 0.0

    for yr in range(1, inp.hold_years + 1):
        rev *= (1 + inp.revenue_growth)
        margin = min(margin + inp.margin_expansion, 0.999)
        ebitda = rev * margin
        da = rev * inp.da_pct_rev
        ebit = ebitda - da
        interest = debt * inp.interest_rate
        ebt = ebit - interest
        taxes = max(ebt * inp.tax_rate, 0)
        net_income = ebt - taxes
        capex = rev * inp.capex_pct_rev
        nwc_now = rev * inp.nwc_pct_rev
        nwc_change = nwc_now - prev_nwc
        prev_nwc = nwc_now
        mgmt_fee = total_equity * inp.mgmt_fee_pct
        cumulative_mgmt_fees += mgmt_fee

        fcf = ebitda - interest - taxes - capex - nwc_change - da + da  # da add-back
        fcf = ebitda - da + da - interest - taxes - capex - nwc_change  # simplify
        # FCF = EBITDA - interest - taxes - capex - ΔNWC
        fcf_pre = ebitda - interest - taxes - capex - nwc_change
        fcf_pre -= mgmt_fee

        # Debt paydown
        sched_amort = min(entry_debt * inp.amort_pct, debt)
        excess_fcf = max(fcf_pre - sched_amort, 0)
        sweep = excess_fcf * inp.cash_sweep
        total_paydown = sched_amort + sweep
        debt = max(debt - total_paydown, 0)

        exit_mult = inp.exit_multiple if inp.exit_multiple else inp.entry_multiple
        equity_at_yr = ebitda * exit_mult - debt

        projections.append(YearlyProjection(
            year=yr,
            revenue=round(rev, 2),
            ebitda=round(ebitda, 2),
            ebitda_margin=round(margin, 4),
            da=round(da, 2),
            ebit=round(ebit, 2),
            interest=round(interest, 2),
            ebt=round(ebt, 2),
            taxes=round(taxes, 2),
            net_income=round(net_income, 2),
            capex=round(capex, 2),
            nwc_change=round(nwc_change, 2),
            fcf_pre_debt=round(fcf_pre, 2),
            debt_amort=round(sched_amort, 2),
            cash_sweep_amt=round(sweep, 2),
            debt_end=round(debt, 2),
            equity_value=round(equity_at_yr, 2),
        ))

    # Exit
    exit_p = projections[-1]
    exit_mult = inp.exit_multiple if inp.exit_multiple else inp.entry_multiple
    exit_ev = exit_p.ebitda * exit_mult
    exit_fees = exit_ev * inp.transaction_costs
    exit_equity = exit_ev - exit_p.debt_end - exit_fees

    moic = exit_equity / total_equity if total_equity > 0 else 0
    irr = _irr(total_equity, exit_equity, inp.hold_years)
    coc = exit_equity / total_equity if total_equity > 0 else 0

    debt_schedule = [
        {
            "year": p.year,
            "debt_beginning": round((projections[p.year - 2].debt_end if p.year > 1 else entry_debt), 2),
            "scheduled_amort": p.debt_amort,
            "cash_sweep": p.cash_sweep_amt,
            "debt_end": p.debt_end,
            "interest": p.interest,
        }
        for p in projections
    ]

    equity_bridge = [
        {"item": "Entry EV",                  "value": round(entry_ev, 2)},
        {"item": "(-) Entry debt",             "value": round(-entry_debt, 2)},
        {"item": "(-) Transaction fees",       "value": round(-txn_fee_entry, 2)},
        {"item": "= Equity invested",          "value": round(total_equity, 2)},
        {"item": "Exit EV",                    "value": round(exit_ev, 2)},
        {"item": "(-) Exit debt",              "value": round(-exit_p.debt_end, 2)},
        {"item": "(-) Exit fees",              "value": round(-exit_fees, 2)},
        {"item": "(-) Mgmt fees (cumulative)", "value": round(-cumulative_mgmt_fees, 2)},
        {"item": "= Equity proceeds",          "value": round(exit_equity, 2)},
        {"item": "MOIC",                       "value": round(moic, 2)},
        {"item": "IRR",                        "value": f"{round(irr * 100, 1)}%"},
    ]

    sensitivity = _sensitivity(inp)

    return LBOResult(
        entry_ebitda=round(ebitda0, 2),
        entry_ev=round(entry_ev, 2),
        entry_debt=round(entry_debt, 2),
        entry_equity=round(entry_equity, 2),
        transaction_fees=round(txn_fee_entry, 2),
        total_equity_invested=round(total_equity, 2),
        exit_year=inp.hold_years,
        exit_ebitda=round(exit_p.ebitda, 2),
        exit_ev=round(exit_ev, 2),
        exit_debt=round(exit_p.debt_end, 2),
        exit_equity=round(exit_equity, 2),
        exit_fees=round(exit_fees, 2),
        net_exit_equity=round(exit_equity, 2),
        moic=round(moic, 2),
        irr=round(irr, 4),
        cash_on_cash=round(coc, 2),
        projections=projections,
        debt_schedule=debt_schedule,
        equity_bridge=equity_bridge,
        sensitivity=sensitivity,
    )


def _irr(invested: float, proceeds: float, years: int) -> float:
    """Approximate IRR via Newton-Raphson on a single cash-flow LBO."""
    if invested <= 0 or proceeds <= 0 or years <= 0:
        return 0.0
    # NPV(r) = -invested + proceeds / (1+r)^years = 0
    # => r = (proceeds/invested)^(1/years) - 1
    return (proceeds / invested) ** (1 / years) - 1


def _sensitivity(inp: LBOInputs) -> dict:
    """2×2 MOIC sensitivity: entry_multiple × exit_multiple."""
    entry_multiples = [inp.entry_multiple - 2, inp.entry_multiple - 1,
                       inp.entry_multiple, inp.entry_multiple + 1, inp.entry_multiple + 2]
    exit_multiples  = [inp.entry_multiple - 2, inp.entry_multiple - 1,
                       inp.entry_multiple, inp.entry_multiple + 1, inp.entry_multiple + 2]

    table: dict[str, dict[str, float]] = {}
    for em in entry_multiples:
        if em <= 0:
            continue
        row: dict[str, float] = {}
        for xm in exit_multiples:
            if xm <= 0:
                continue
            try:
                test = LBOInputs(
                    revenue=inp.revenue, ebitda_margin=inp.ebitda_margin,
                    entry_multiple=em, debt_ebitda=inp.debt_ebitda,
                    interest_rate=inp.interest_rate, amort_pct=inp.amort_pct,
                    cash_sweep=inp.cash_sweep, revenue_growth=inp.revenue_growth,
                    margin_expansion=inp.margin_expansion,
                    capex_pct_rev=inp.capex_pct_rev, nwc_pct_rev=inp.nwc_pct_rev,
                    tax_rate=inp.tax_rate, da_pct_rev=inp.da_pct_rev,
                    hold_years=inp.hold_years, exit_multiple=xm,
                    mgmt_fee_pct=inp.mgmt_fee_pct, transaction_costs=inp.transaction_costs,
                )
                r = run_lbo(test)
                row[f"{xm}x exit"] = r.moic
            except Exception:
                row[f"{xm}x exit"] = 0.0
        table[f"{em}x entry"] = row
    return table


# ── Simple returns calculator (no LBO complexity) ────────────────────────────

def simple_returns(
    invested: float,
    proceeds: float,
    years: float,
    dividends: float = 0.0,
) -> dict:
    total_proceeds = proceeds + dividends
    moic = total_proceeds / invested if invested else 0
    irr = (total_proceeds / invested) ** (1 / years) - 1 if invested and years else 0
    return {
        "invested": round(invested, 2),
        "proceeds": round(proceeds, 2),
        "dividends": round(dividends, 2),
        "total_proceeds": round(total_proceeds, 2),
        "moic": round(moic, 2),
        "irr_pct": round(irr * 100, 1),
        "absolute_gain": round(total_proceeds - invested, 2),
    }
