"""YAML-driven pivot / slice views (Excel-style, config-defined)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _load_view_spec(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _safe_sheet_name(title: str, fallback: str) -> str:
    invalid = "[]:*?/\\"
    s = (title or fallback).strip() or fallback
    for c in invalid:
        s = s.replace(c, "_")
    return s[:31]


def apply_filters(df: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    if not filters:
        return df
    out = df
    for col, val in filters.items():
        if col not in out.columns:
            continue
        if isinstance(val, list):
            out = out[out[col].isin(val)]
        else:
            out = out[out[col] == val]
    return out


def build_custom_view(df: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    """
    Build a pivot-like table from a spec::

        index: [Group]           # row labels
        columns: []              # optional column labels (second axis)
        values: [Shipped, Expired]
        aggfunc: sum
        filters: { Group: [Online Sale] }
    """
    work = apply_filters(df, spec.get("filters"))
    index = spec.get("index") or spec.get("rows") or []
    columns = spec.get("columns") or []
    values = spec.get("values")
    if not values:
        raise ValueError("View spec must define values: list of column names")
    if isinstance(values, str):
        values = [values]
    agg = spec.get("aggfunc", "sum")
    missing = [c for c in list(index) + list(columns) + list(values) if c not in work.columns]
    if missing:
        raise ValueError(f"Unknown columns in view spec: {missing}. Available: {list(work.columns)}")

    if columns:
        pt = pd.pivot_table(
            work,
            index=index,
            columns=columns,
            values=values,
            aggfunc=agg,
            fill_value=0,
        )
        return pt.reset_index()
    if len(values) == 1:
        return (
            work.groupby(index, dropna=False)[values[0]]
            .agg(agg)
            .reset_index()
        )
    return work.groupby(index, dropna=False)[values].agg(agg).reset_index()


def load_views_from_dir(views_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    if not views_dir.is_dir():
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for p in sorted(views_dir.glob("*.yaml")):
        spec = _load_view_spec(p)
        if spec.get("disabled"):
            continue
        out.append((p.stem, spec))
    return out
