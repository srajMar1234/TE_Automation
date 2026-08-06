"""Roll up customer-level pivot to reporting Group; attach percentage inputs."""

from __future__ import annotations

import pandas as pd

from src.transform.report_summary import _norm_key


def rollup_by_reporting_group(pivot_df: pd.DataFrame) -> pd.DataFrame:
    """Sum all numeric columns by ``Group`` (drops Customer Group grain)."""
    dim = {"Customer Group", "Group"}
    nums = [c for c in pivot_df.columns if c not in dim]
    if "Group" not in pivot_df.columns:
        raise ValueError("Pivot_Summary must include a Group column")
    g = pivot_df.groupby("Group", dropna=False)[nums].sum().reset_index()
    for c in nums:
        g[c] = g[c].round(2)
    return g


def apply_nr_percent(group_df: pd.DataFrame, nr_by_group: dict[str, float]) -> pd.DataFrame:
    """Add NR% column; keys matched case-insensitively on Group."""

    def lookup(cell: object) -> float:
        g = str(cell).strip() if cell is not None and not (isinstance(cell, float) and pd.isna(cell)) else ""
        if not g:
            return float("nan")
        if g in nr_by_group:
            return nr_by_group[g]
        nk = _norm_key(g)
        for k, v in nr_by_group.items():
            if _norm_key(k) == nk:
                return v
        return float("nan")

    out = group_df.copy()
    out["NR%"] = out["Group"].map(lookup)
    return out


def apply_gc_percent(group_df: pd.DataFrame, gc_by_group: dict[str, float]) -> pd.DataFrame:
    """Add GC% column; keys matched case-insensitively on Group."""

    def lookup(cell: object) -> float:
        g = str(cell).strip() if cell is not None and not (isinstance(cell, float) and pd.isna(cell)) else ""
        if not g:
            return float("nan")
        if g in gc_by_group:
            return gc_by_group[g]
        nk = _norm_key(g)
        for k, v in gc_by_group.items():
            if _norm_key(k) == nk:
                return v
        return float("nan")

    out = group_df.copy()
    out["GC%"] = out["Group"].map(lookup)
    return out


def apply_sd_percent(group_df: pd.DataFrame, sd_by_group: dict[str, float]) -> pd.DataFrame:
    """Add SD% column; keys matched case-insensitively on Group."""

    def lookup(cell: object) -> float:
        g = str(cell).strip() if cell is not None and not (isinstance(cell, float) and pd.isna(cell)) else ""
        if not g:
            return float("nan")
        if g in sd_by_group:
            return sd_by_group[g]
        nk = _norm_key(g)
        for k, v in sd_by_group.items():
            if _norm_key(k) == nk:
                return v
        return float("nan")

    out = group_df.copy()
    out["SD%"] = out["Group"].map(lookup)
    return out
