"""Built-in standard report builders."""

from __future__ import annotations

import pandas as pd


def build_gross_sale_report(group_df: pd.DataFrame) -> pd.DataFrame:
    """
    Gross Sale Report:
    - Rows: reporting groups
    - Shipped: sum shipped
    - Return: sum returned
    - Net: shipped - return
    - NR: net * NR%
    """
    required = {"Group", "Shipped", "Returned"}
    missing = [c for c in required if c not in group_df.columns]
    if missing:
        raise ValueError(f"Group_Summary missing required columns for Gross Sale Report: {missing}")

    work = group_df.copy()
    shipped = pd.to_numeric(work["Shipped"], errors="coerce").fillna(0.0)
    returned = pd.to_numeric(work["Returned"], errors="coerce").fillna(0.0)
    net = shipped - returned

    nr_pct = pd.to_numeric(work["NR%"] if "NR%" in work.columns else pd.Series([0] * len(work)), errors="coerce").fillna(0.0)
    nr_val = (net * (nr_pct / 100.0)).round(2)

    out = pd.DataFrame(
        {
            "Particulars": work["Group"].astype(str),
            "Shipped": shipped.round(2),
            "Return": returned.round(2),
            "Net": net.round(2),
            "NR": nr_val.round(2),
            "%": nr_pct.round(2),
        }
    )

    shipped_total = float(out["Shipped"].sum())
    return_total = float(out["Return"].sum())
    net_total = float(out["Net"].sum())
    nr_total = float(out["NR"].sum())
    pct_total = round((nr_total / net_total) * 100.0, 2) if net_total else 0.0

    total_row = pd.DataFrame(
        [
            {
                "Particulars": "Sale As Per Business Report",
                "Shipped": round(shipped_total, 2),
                "Return": round(return_total, 2),
                "Net": round(net_total, 2),
                "NR": round(nr_total, 2),
                "%": pct_total,
            }
        ]
    )
    return pd.concat([out, total_row], ignore_index=True)


def build_pipeline_nr_report(group_df: pd.DataFrame) -> pd.DataFrame:
    """
    Report #2:
    Base columns by Group:
    - Quotation Pending
    - Quotation Approved
    - RTS (Ready To Ship)
    - Expiry (Expired)

    Calculated:
    - QP = Quotation Pending * NR%
    - QA = Quotation Approved * NR%
    - RTS NR = RTS * NR%
    - NR% (display)
    """
    required = {"Group", "Quotation Pending", "Quotation Approved", "Ready To Ship", "Expired"}
    missing = [c for c in required if c not in group_df.columns]
    if missing:
        raise ValueError(f"Group_Summary missing required columns for Pipeline NR Report: {missing}")

    work = group_df.copy()
    qp_base = pd.to_numeric(work["Quotation Pending"], errors="coerce").fillna(0.0)
    qa_base = pd.to_numeric(work["Quotation Approved"], errors="coerce").fillna(0.0)
    rts_base = pd.to_numeric(work["Ready To Ship"], errors="coerce").fillna(0.0)
    exp_base = pd.to_numeric(work["Expired"], errors="coerce").fillna(0.0)
    nr_pct = pd.to_numeric(work["NR%"] if "NR%" in work.columns else pd.Series([0] * len(work)), errors="coerce").fillna(0.0)
    factor = nr_pct / 100.0

    out = pd.DataFrame(
        {
            "Particulars": work["Group"].astype(str),
            "Quotation Pending": qp_base.round(2),
            "Quotation Approved": qa_base.round(2),
            "RTS": rts_base.round(2),
            "Expiry": exp_base.round(2),
            "QP": (qp_base * factor).round(2),
            "QA": (qa_base * factor).round(2),
            "RTS NR": (rts_base * factor).round(2),
            "NR%": nr_pct.round(2),
        }
    )

    total_row = pd.DataFrame(
        [
            {
                "Particulars": "Total Amount",
                "Quotation Pending": round(float(out["Quotation Pending"].sum()), 2),
                "Quotation Approved": round(float(out["Quotation Approved"].sum()), 2),
                "RTS": round(float(out["RTS"].sum()), 2),
                "Expiry": round(float(out["Expiry"].sum()), 2),
                "QP": round(float(out["QP"].sum()), 2),
                "QA": round(float(out["QA"].sum()), 2),
                "RTS NR": round(float(out["RTS NR"].sum()), 2),
                "NR%": "",
            }
        ]
    )
    return pd.concat([out, total_row], ignore_index=True)


def build_summary_excluding_hom_report(
    group_df: pd.DataFrame,
    *,
    marico_offtake_gross: float = 0.0,
    marico_offtake_nr_percent: float = 0.0,
    other_adjustment_gross: float = 0.0,
    other_adjustment_nr: float = 0.0,
) -> pd.DataFrame:
    """Report #3: Summary Excluding (HOM)."""
    gross = build_gross_sale_report(group_df)
    pipe = build_pipeline_nr_report(group_df)

    def _g_row(particular: str) -> pd.Series:
        m = gross[gross["Particulars"].astype(str).str.casefold() == particular.casefold()]
        if m.empty:
            return pd.Series(dtype=float)
        return m.iloc[0]

    def _p_row(particular: str) -> pd.Series:
        m = pipe[pipe["Particulars"].astype(str).str.casefold() == particular.casefold()]
        if m.empty:
            return pd.Series(dtype=float)
        return m.iloc[0]

    def _num(v: object) -> float:
        return float(pd.to_numeric(pd.Series([v]), errors="coerce").fillna(0.0).iloc[0])

    g_total = _g_row("Sale As Per Business Report")
    g_hom = _g_row("HOM Sale")
    g_marico = _g_row("Marico MT (Primary)")

    p_total = _p_row("Total Amount")
    p_hom = _p_row("HOM Sale")
    p_marico = _p_row("Marico MT (Primary)")

    r2 = {"line_item": "Sales As Per Business Report", "gross_sale": _num(g_total.get("Net")) - _num(g_hom.get("Net")), "nr": _num(g_total.get("NR")) - _num(g_hom.get("NR"))}
    r3 = {"line_item": "Add: Marico MT (Offtake)", "gross_sale": marico_offtake_gross, "nr": marico_offtake_gross * (marico_offtake_nr_percent / 100.0)}
    r4 = {"line_item": "Less: Marico MT (Primary)", "gross_sale": -_num(g_marico.get("Net")), "nr": -_num(g_marico.get("NR"))}
    r5 = {"line_item": "Less: Other Adjustment (Till Block 3)", "gross_sale": -other_adjustment_gross, "nr": -other_adjustment_nr}
    r6 = {"line_item": "Sub Total Shipped", "gross_sale": r2["gross_sale"] + r3["gross_sale"] + r4["gross_sale"] + r5["gross_sale"], "nr": r2["nr"] + r3["nr"] + r4["nr"] + r5["nr"]}
    r7 = {
        "line_item": "Less: Marico MT (Primary) QP/QA/RTS",
        "gross_sale": _num(p_marico.get("Quotation Pending")) + _num(p_marico.get("Quotation Approved")) + _num(p_marico.get("RTS")),
        "nr": _num(p_marico.get("QP")) + _num(p_marico.get("QA")) + _num(p_marico.get("RTS NR")),
    }
    r8 = {
        "line_item": "Add: Quotation Pending",
        "gross_sale": _num(p_total.get("Quotation Pending")) - _num(p_hom.get("Quotation Pending")),
        "nr": _num(p_total.get("QP")) - _num(p_hom.get("QP")),
    }
    r9 = {
        "line_item": "Add: Quotation Approved",
        "gross_sale": _num(p_total.get("Quotation Approved")) - _num(p_hom.get("Quotation Approved")),
        "nr": _num(p_total.get("QA")) - _num(p_hom.get("QA")),
    }
    r10 = {
        "line_item": "Add: Ready to Ship",
        "gross_sale": _num(p_total.get("RTS")) - _num(p_hom.get("RTS")),
        "nr": _num(p_total.get("RTS NR")) - _num(p_hom.get("RTS NR")),
    }
    r11 = {"line_item": "Add: Expiry", "gross_sale": _num(p_total.get("Expiry")), "nr": _num(p_total.get("Expiry"))}
    r12 = {
        "line_item": "Total To Date (Excluding HOM)",
        "gross_sale": r6["gross_sale"] + r7["gross_sale"] + r8["gross_sale"] + r9["gross_sale"] + r10["gross_sale"] + r11["gross_sale"],
        "nr": r6["nr"] + r7["nr"] + r8["nr"] + r9["nr"] + r10["nr"] + r11["nr"],
    }
    r14 = {"line_item": "  Shipped", "gross_sale": _num(g_hom.get("Net")), "nr": _num(g_hom.get("NR"))}
    r15 = {"line_item": "  QP", "gross_sale": _num(p_hom.get("Quotation Pending")), "nr": _num(p_hom.get("QP"))}
    r16 = {"line_item": "  QA", "gross_sale": _num(p_hom.get("Quotation Approved")), "nr": _num(p_hom.get("QA"))}
    r17 = {"line_item": "  RTS", "gross_sale": _num(p_hom.get("RTS")), "nr": _num(p_hom.get("RTS NR"))}
    r13 = {"line_item": "Add: HOM Sales", "gross_sale": r14["gross_sale"] + r15["gross_sale"] + r16["gross_sale"] + r17["gross_sale"], "nr": r14["nr"] + r15["nr"] + r16["nr"] + r17["nr"]}
    r18 = {"line_item": "Total To Date", "gross_sale": r12["gross_sale"] + r13["gross_sale"], "nr": r12["nr"] + r13["nr"]}
    r19 = {"line_item": "Total To Date (Only shipped) till T-1", "gross_sale": r6["gross_sale"] + r13["gross_sale"], "nr": r6["nr"] + r13["nr"]}

    rows = [r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, r13, r14, r15, r16, r17, r18, r19]
    out = pd.DataFrame(rows, columns=["line_item", "gross_sale", "nr"])
    out = out.rename(columns={"line_item": "Line Item Desc", "gross_sale": "Gross Sale", "nr": "NR"})
    out["Gross Sale"] = pd.to_numeric(out["Gross Sale"], errors="coerce").fillna(0.0).round(2)
    out["NR"] = pd.to_numeric(out["NR"], errors="coerce").fillna(0.0).round(2)
    return out

