"""Build summary sheets from a multi-tab orders workbook (unique customer groups + pivot by order status)."""

from __future__ import annotations

from functools import lru_cache
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.product.runtime_inputs import DailyExclusionInput
from src.transform.summary_types import SummaryMeta

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_SOURCE_SHEETS = ("Expired Report", "Returned Report", "Shipped Report", "QPQA Report")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm_key(s: str) -> str:
    t = str(s).strip()
    t = re.sub(r"\s+", " ", t)
    return t.casefold()


def _customer_group_from_row(
    name_raw: Any,
    cg_raw: Any,
    col_cn: str | None,
    name_overrides: list[dict[str, str]],
) -> str | None:
    """Apply Customer Name overrides, then normalize Customer Group."""
    cg0 = cg_raw
    if col_cn is not None and not pd.isna(name_raw):
        nk_name = _norm_key(str(name_raw))
        for rule in name_overrides:
            want = _norm_key(str(rule.get("customer_name", "")))
            if want and nk_name == want:
                cg0 = rule.get("customer_group", cg0)
                break
    if cg0 is None or (isinstance(cg0, float) and pd.isna(cg0)):
        return None
    cg_display = re.sub(r"\s+", " ", str(cg0).strip())
    if not cg_display or cg_display.lower() == "nan":
        return None
    return cg_display


def _is_excluded_customer_group(
    cg_display: str,
    excluded_norm: set[str],
    excluded_substrings: list[str],
) -> bool:
    k = _norm_key(cg_display)
    if k in excluded_norm:
        return True
    for sub in excluded_substrings:
        t = str(sub).strip().casefold()
        if t and t in k:
            return True
    return False


def _load_daily_exclusions(path: Path | None) -> tuple[set[str], int | None]:
    """Returns normalized customer group keys to exclude, and optional user-reported total count."""
    if path is None or not path.is_file():
        return set(), None
    doc = _load_yaml(path)
    extra = {_norm_key(str(x)) for x in (doc.get("additional_excluded_customer_groups") or []) if str(x).strip()}
    reported = doc.get("excluded_customer_groups_reported_total")
    if reported is not None and reported != "":
        try:
            reported = int(reported)
        except (TypeError, ValueError):
            reported = None
    else:
        reported = None
    return extra, reported


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Match column by case-insensitive substring or exact normalized name."""
    want = [_norm_key(c) for c in candidates]
    for col in df.columns:
        ck = _norm_key(col)
        for w in want:
            if ck == w or w in ck or ck in w:
                return col
    return None


def _to_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


@lru_cache(maxsize=8)
def _load_source_dataframe_cached(path_str: str, mtime_ns: int) -> pd.DataFrame:
    """Read only the raw source sheets once per workbook version."""
    _ = mtime_ns  # part of cache key
    xl = pd.ExcelFile(path_str)
    sheet_names = [s for s in xl.sheet_names if s in _RAW_SOURCE_SHEETS] or list(xl.sheet_names)
    frames: list[pd.DataFrame] = []
    for sheet in sheet_names:
        df = pd.read_excel(xl, sheet_name=sheet)
        df["_source_sheet"] = sheet
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _canonical_order_status(raw: Any, aliases: dict[str, str]) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    key = re.sub(r"\s+", " ", s).casefold()
    if key in aliases:
        return aliases[key]
    # Heuristics for common export variants (labels differ by report / OpenCart)
    if "ready" in key and "ship" in key:
        return "Ready To Ship"
    if "quotation" in key and "approved" in key:
        return "Quotation Approved"
    if "quotation" in key and "pending" in key:
        return "Quotation Pending"
    if key == "shipped" or key.startswith("shipped "):
        return "Shipped"
    if "return" in key:
        return "Returned"
    if key == "expired":
        return "Expired"
    return None


def build_report_summary(
    input_xlsx: Path,
    *,
    rules_path: Path | None = None,
    mapping_path: Path | None = None,
    customer_group_mapping_overrides: dict[str, str] | None = None,
    daily_inputs_path: Path | None = None,
    daily_exclusions: DailyExclusionInput | None = None,
    merge_daily_yaml: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, SummaryMeta]:
    """
    Returns (unique_customer_groups_df, pivot_df, meta).

    Pivot columns: Customer Group, Group, then one numeric column per order status in rules.
    """
    rules_path = rules_path or _PROJECT_ROOT / "config" / "summary_rules.yaml"
    mapping_path = mapping_path or _PROJECT_ROOT / "config" / "customer_group_mapping.yaml"
    default_daily = _PROJECT_ROOT / "config" / "inputs" / "daily.yaml"
    daily_path_eff = daily_inputs_path if daily_inputs_path is not None else default_daily
    rules = _load_yaml(rules_path)
    mapping_doc = _load_yaml(mapping_path)
    group_map: dict[str, str] = mapping_doc.get("mapping") or {}
    map_override_norm = {_norm_key(k): str(v).strip() for k, v in (customer_group_mapping_overrides or {}).items() if str(k).strip() and str(v).strip()}

    file_extra: set[str] = set()
    file_reported: int | None = None
    if merge_daily_yaml and daily_path_eff.is_file():
        file_extra, file_reported = _load_daily_exclusions(daily_path_eff)

    if daily_exclusions is not None:
        ui_extra = {_norm_key(x) for x in daily_exclusions.additional_excluded_customer_groups if str(x).strip()}
        daily_extra = file_extra | ui_extra
        reported_total = daily_exclusions.excluded_customer_groups_reported_total
        if reported_total is None:
            reported_total = file_reported
    else:
        daily_extra = file_extra
        reported_total = file_reported

    excluded = {_norm_key(x) for x in (rules.get("excluded_customer_groups") or [])} | daily_extra
    excluded_substrings = list(rules.get("excluded_customer_group_substrings") or [])
    name_overrides = list(rules.get("customer_name_overrides") or [])
    status_cols_cfg: dict[str, str] = rules.get("order_status_columns") or {}
    alias_raw = rules.get("order_status_aliases") or {}
    aliases = {_norm_key(k): v for k, v in alias_raw.items()}

    all_df = _load_source_dataframe_cached(
        str(input_xlsx.resolve()),
        input_xlsx.stat().st_mtime_ns,
    ).copy()

    col_cg = _find_column(all_df, ["Customer Group", "customer group"])
    col_cn = _find_column(all_df, ["Customer Name", "customer name"])
    col_os = _find_column(all_df, ["Order Status", "order status"])
    col_incl = _find_column(all_df, ["Total Incl Tax", "Total Incl. Tax", "total incl"])
    col_excl = _find_column(all_df, ["Total Excl Tax", "Total Excl. Tax", "total excl"])

    if not col_cg or not col_os:
        raise ValueError(
            f"Missing required columns. Found Customer Group={col_cg!r}, Order Status={col_os!r}. "
            f"Columns: {list(all_df.columns)}"
        )
    if not col_incl or not col_excl:
        raise ValueError(
            f"Missing tax columns. Found Total Incl Tax={col_incl!r}, Total Excl Tax={col_excl!r}. "
            f"Columns: {list(all_df.columns)}"
        )

    work = pd.DataFrame(
        {
            "_customer_group_raw": all_df[col_cg],
            "_customer_name_raw": all_df[col_cn] if col_cn else pd.Series([None] * len(all_df)),
            "_order_status_raw": all_df[col_os],
            "_incl": _to_number(all_df[col_incl]),
            "_excl": _to_number(all_df[col_excl]),
        }
    )

    # Customer-group override from customer name, vectorized.
    override_map = {
        _norm_key(str(rule.get("customer_name", ""))): str(rule.get("customer_group", "")).strip()
        for rule in name_overrides
        if str(rule.get("customer_name", "")).strip() and str(rule.get("customer_group", "")).strip()
    }
    name_norm = (
        work["_customer_name_raw"]
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.casefold()
    )
    cg_clean = (
        work["_customer_group_raw"]
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    override_series = name_norm.map(override_map)
    work["_customer_group"] = override_series.where(override_series.notna(), cg_clean)
    work = work[
        work["_customer_group"].notna()
        & (work["_customer_group"].astype(str).str.strip() != "")
        & (work["_customer_group"].astype(str).str.casefold() != "nan")
    ].copy()
    work["_customer_group_norm"] = work["_customer_group"].astype(str).map(_norm_key)

    exact_mask = work["_customer_group_norm"].isin(excluded)
    substr_mask = pd.Series(False, index=work.index)
    for sub in excluded_substrings:
        token = str(sub).strip().casefold()
        if token:
            substr_mask = substr_mask | work["_customer_group_norm"].str.contains(re.escape(token), regex=True)
    excluded_mask = exact_mask | substr_mask
    seen_sorted = sorted(
        work.loc[excluded_mask, "_customer_group"].astype(str).drop_duplicates().tolist(),
        key=str.casefold,
    )
    work = work.loc[~excluded_mask].copy()

    status_norm = (
        work["_order_status_raw"]
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.casefold()
    )
    canonical = status_norm.map(aliases)
    canonical = canonical.mask(canonical.isna() & status_norm.str.contains("ready") & status_norm.str.contains("ship"), "Ready To Ship")
    canonical = canonical.mask(canonical.isna() & status_norm.str.contains("quotation") & status_norm.str.contains("approved"), "Quotation Approved")
    canonical = canonical.mask(canonical.isna() & status_norm.str.contains("quotation") & status_norm.str.contains("pending"), "Quotation Pending")
    canonical = canonical.mask(canonical.isna() & ((status_norm == "shipped") | status_norm.str.startswith("shipped ")), "Shipped")
    canonical = canonical.mask(canonical.isna() & status_norm.str.contains("return"), "Returned")
    canonical = canonical.mask(canonical.isna() & (status_norm == "expired"), "Expired")
    work["_status"] = canonical
    canonical_statuses = list(status_cols_cfg.keys())
    work = work[work["_status"].isin(canonical_statuses)].copy()

    amount_kind = work["_status"].map(status_cols_cfg)
    work["_amount"] = work["_incl"].where(amount_kind == "total_incl_tax", work["_excl"])

    grouped = (
        work.groupby(["_customer_group", "_status"], dropna=False)["_amount"]
        .sum()
        .unstack(fill_value=0.0)
    )
    unique_sorted = sorted(grouped.index.astype(str).tolist(), key=str.casefold)
    grouped = grouped.reindex(index=unique_sorted, columns=canonical_statuses, fill_value=0.0)
    pivot_df = grouped.reset_index().rename(columns={"_customer_group": "Customer Group"})
    pivot_df["Group"] = pivot_df["Customer Group"].map(
        lambda cg: map_override_norm.get(_norm_key(cg))
        or group_map.get(cg)
        or next((mv for mk, mv in group_map.items() if _norm_key(mk) == _norm_key(cg)), "")
    )
    pivot_df = pivot_df[["Customer Group", "Group", *canonical_statuses]]
    for st in canonical_statuses:
        pivot_df[st] = _to_number(pivot_df[st]).round(2)
    unique_df = pd.DataFrame({"Customer Group": unique_sorted})

    match: bool | None = None
    if reported_total is not None:
        match = reported_total == len(seen_sorted)
    meta = SummaryMeta(
        excluded_customer_groups_seen=seen_sorted,
        excluded_customer_groups_reported_total=reported_total,
        reported_vs_computed_match=match,
    )
    return unique_df, pivot_df, meta


def write_summary_workbook(
    input_xlsx: Path,
    output_xlsx: Path,
    *,
    rules_path: Path | None = None,
    mapping_path: Path | None = None,
    customer_group_mapping_overrides: dict[str, str] | None = None,
    daily_inputs_path: Path | None = None,
    daily_exclusions: DailyExclusionInput | None = None,
    merge_daily_yaml: bool = True,
) -> Path:
    unique_df, pivot_df, _meta = build_report_summary(
        input_xlsx,
        rules_path=rules_path,
        mapping_path=mapping_path,
        customer_group_mapping_overrides=customer_group_mapping_overrides,
        daily_inputs_path=daily_inputs_path,
        daily_exclusions=daily_exclusions,
        merge_daily_yaml=merge_daily_yaml,
    )
    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        unique_df.to_excel(writer, sheet_name="Unique_Customer_Groups", index=False)
        pivot_df.to_excel(writer, sheet_name="Pivot_Summary", index=False)
    return output_xlsx
