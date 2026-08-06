"""Load manual inputs and build report-friendly helper tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.transform.report_summary import _load_yaml, _to_number  # reuse

STATUS_COLUMNS = [
    "Quotation Approved",
    "Quotation Pending",
    "Ready To Ship",
    "Shipped",
    "Returned",
    "Expired",
]


def _load_percent_map(path: Path, keys: list[str]) -> dict[str, float]:
    if not path.is_file():
        return {}
    doc = _load_yaml(path)
    raw = {}
    for k in keys:
        raw = doc.get(k) or {}
        if raw:
            break
    out: dict[str, float] = {}
    for k, v in raw.items():
        if v is None or str(v).strip() == "":
            continue
        try:
            out[str(k).strip()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def load_nr_percent(path: Path) -> dict[str, float]:
    """NR% keyed by reporting Group name (see customer_group_mapping)."""
    return _load_percent_map(path, ["nr_percent_by_group", "nr_by_group", "by_group"])


def load_gc_percent(path: Path) -> dict[str, float]:
    """GC% keyed by reporting Group name (see customer_group_mapping)."""
    return _load_percent_map(path, ["gc_percent_by_group", "gc_by_group"])


def load_sd_percent(path: Path) -> dict[str, float]:
    """SD% keyed by reporting Group name (see customer_group_mapping)."""
    return _load_percent_map(path, ["sd_percent_by_group", "sd_by_group"])


def load_base_excluded_customer_groups(rules_path: Path) -> list[str]:
    """Base exact customer groups from `summary_rules.yaml`."""
    if not rules_path.is_file():
        return []
    doc = _load_yaml(rules_path)
    vals = [str(x).strip() for x in (doc.get("excluded_customer_groups") or []) if str(x).strip()]
    seen: set[str] = set()
    out: list[str] = []
    for v in vals:
        k = v.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def load_daily_excluded_customer_groups(daily_path: Path) -> list[str]:
    """Exact exclusions listed in `config/inputs/daily.yaml`."""
    if not daily_path.is_file():
        return []
    doc = _load_yaml(daily_path)
    vals = [str(x).strip() for x in (doc.get("additional_excluded_customer_groups") or []) if str(x).strip()]
    seen: set[str] = set()
    out: list[str] = []
    for v in vals:
        k = v.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def reporting_groups_from_mapping(mapping_path: Path) -> list[str]:
    """Distinct reporting Group names from customer_group_mapping.yaml (for NR% forms)."""
    if not mapping_path.is_file():
        return []
    doc = _load_yaml(mapping_path)
    raw = doc.get("mapping") or {}
    seen: set[str] = set()
    for v in raw.values():
        s = str(v).strip()
        if s:
            seen.add(s)
    return sorted(seen, key=str.casefold)


def load_manual_context(path: Path) -> dict[str, Any]:
    """Manual context from YAML. Supported key: `excluded_group_status_values`."""
    if not path.is_file():
        return {}
    doc = _load_yaml(path)
    return dict(doc.get("fields") or doc)


def manual_group_adjustments_table(manual: dict[str, Any]) -> pd.DataFrame:
    """
    Parse manual adjustments keyed by Excluded Chain + Group + status values.
    Expected shape:
    {
      "excluded_group_status_values": [
        {"chain": "Amazon", "group": "Online Sale", "Quotation Approved": 10, ...}
      ]
    }
    """
    rows_raw = list(manual.get("excluded_group_status_values") or [])
    if not rows_raw:
        return pd.DataFrame(columns=["Customer Group", "Group", *STATUS_COLUMNS])
    rows: list[dict[str, Any]] = []
    for x in rows_raw:
        if not isinstance(x, dict):
            continue
        chain = str(x.get("chain", "")).strip()
        group = str(x.get("group", "")).strip()
        if not chain or not group:
            continue
        row: dict[str, Any] = {"Customer Group": chain, "Group": group}
        for c in STATUS_COLUMNS:
            row[c] = x.get(c, 0)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["Customer Group", "Group", *STATUS_COLUMNS])
    df = pd.DataFrame(rows, columns=["Customer Group", "Group", *STATUS_COLUMNS])
    for c in STATUS_COLUMNS:
        df[c] = _to_number(df[c])
    return df


def apply_manual_rows_to_customer_pivot(pivot_df: pd.DataFrame, manual: dict[str, Any]) -> pd.DataFrame:
    """Append manual rows at customer grain, then re-aggregate by Customer Group + Group."""
    adj = manual_group_adjustments_table(manual)
    if adj.empty:
        return pivot_df

    out = pivot_df.copy()
    for c in STATUS_COLUMNS:
        if c not in out.columns:
            out[c] = 0.0
    if "Customer Group" not in out.columns:
        out["Customer Group"] = ""
    if "Group" not in out.columns:
        out["Group"] = ""
    out = out[["Customer Group", "Group", *STATUS_COLUMNS]]

    combined = pd.concat([out, adj[["Customer Group", "Group", *STATUS_COLUMNS]]], ignore_index=True)
    grouped = combined.groupby(["Customer Group", "Group"], dropna=False)[STATUS_COLUMNS].sum().reset_index()
    for c in STATUS_COLUMNS:
        grouped[c] = grouped[c].round(2)
    grouped = grouped.sort_values(["Customer Group", "Group"], key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)
    return grouped


def apply_manual_group_adjustments(group_df: pd.DataFrame, manual: dict[str, Any]) -> pd.DataFrame:
    """Add manual status values by Group into aggregated Group_Summary."""
    adj = manual_group_adjustments_table(manual)
    if adj.empty:
        return group_df

    out = group_df.copy()
    if "Group" not in out.columns:
        return out
    for c in STATUS_COLUMNS:
        if c not in out.columns:
            out[c] = 0.0

    add = adj.groupby("Group", dropna=False)[STATUS_COLUMNS].sum().reset_index()
    merged = out.merge(add, on="Group", how="outer", suffixes=("", "__manual"))
    for c in STATUS_COLUMNS:
        base = _to_number(merged[c] if c in merged.columns else pd.Series([0] * len(merged)))
        extra_col = f"{c}__manual"
        extra = _to_number(merged[extra_col] if extra_col in merged.columns else pd.Series([0] * len(merged)))
        merged[c] = (base + extra).round(2)
        if extra_col in merged.columns:
            merged = merged.drop(columns=[extra_col])
    if "NR%" not in merged.columns:
        merged["NR%"] = pd.NA
    return merged


def manual_context_table(manual: dict[str, Any]) -> pd.DataFrame:
    """
    Build the `Manual_Context` sheet from manual group-status additions.
    Expected shape:
    {
      "excluded_group_status_values": [
        {"group": "Offline Sale", "Quotation Approved": 1, ...}
      ]
    }
    """
    df = manual_group_adjustments_table(manual)
    if df.empty:
        return pd.DataFrame(columns=["Customer Group", "Group", *STATUS_COLUMNS])
    total_row = {"Customer Group": "TOTAL_MANUAL_ADDITION", "Group": ""}
    for c in STATUS_COLUMNS:
        total_row[c] = round(float(_to_number(df[c]).sum()), 2)
    total_df = pd.DataFrame([total_row])
    return pd.concat([df, total_df], ignore_index=True)


def audit_table(meta: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = [
        {"metric": "distinct_excluded_customer_groups_in_source", "value": len(meta.excluded_customer_groups_seen)},
        {"metric": "user_reported_excluded_total", "value": meta.excluded_customer_groups_reported_total},
        {"metric": "reported_matches_computed", "value": meta.reported_vs_computed_match},
    ]
    for name in meta.excluded_customer_groups_seen:
        rows.append({"metric": "excluded_customer_group", "value": name})
    return pd.DataFrame(rows)
