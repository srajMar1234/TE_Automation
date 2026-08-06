"""TE Report Studio — operator UI (localhost or hosted). Run: streamlit run app/studio.py"""

from __future__ import annotations

import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.product.custom_view import apply_filters, build_custom_view
from src.product.cutover import cutover_workbook_bytes, run_automatic_cutover
from src.product.group_rollup import apply_gc_percent, apply_nr_percent, apply_sd_percent, rollup_by_reporting_group
from src.product.inputs import (
    STATUS_COLUMNS,
    apply_manual_rows_to_customer_pivot,
    load_base_excluded_customer_groups,
    load_daily_excluded_customer_groups,
    load_gc_percent,
    load_nr_percent,
    load_sd_percent,
    reporting_groups_from_mapping,
)
from src.product.runtime_inputs import DailyExclusionInput, parse_excluded_groups_multiline
from src.product.standard_reports import (
    build_gross_sale_report,
    build_pipeline_nr_report,
    build_summary_excluding_hom_report,
)
from src.pipeline.export_job import export_all_order_reports
from src.output.manual_merge import merge_report_zips_to_excel
from src.product.workbook import write_product_workbook_bytes
from src.transform.report_summary import build_report_summary

st.set_page_config(page_title="TE Report Studio", layout="wide")
st.title("TE Report Studio")
st.caption("Business users should provide all runtime values here. No YAML edits required for daily use.")

root = ROOT
mapping_path = root / "config" / "customer_group_mapping.yaml"
rules_path = root / "config" / "summary_rules.yaml"
daily_yaml_path = root / "config" / "inputs" / "daily.yaml"
default_nr_yaml = root / "config" / "inputs" / "nr_percent.yaml"
CUTOVER_HISTORY_DIR = root / "data" / "cutover_history"
MARKETPLACE_DEFAULT_GROUP = "Marketplace Sale (FBA,FBF, Jio)"

if "studio_work_dir" not in st.session_state:
    st.session_state["studio_work_dir"] = str(Path(tempfile.mkdtemp(prefix="te_studio_")))
if "download_dir" not in st.session_state:
    st.session_state["download_dir"] = st.session_state["studio_work_dir"]
if "combined_path" not in st.session_state:
    st.session_state["combined_path"] = ""
if "last_scrape_at" not in st.session_state:
    st.session_state["last_scrape_at"] = ""
if "last_combine_at" not in st.session_state:
    st.session_state["last_combine_at"] = ""
if "record_counts" not in st.session_state:
    st.session_state["record_counts"] = {}
if "op_status" not in st.session_state:
    st.session_state["op_status"] = "Idle"
if "op_status_level" not in st.session_state:
    st.session_state["op_status_level"] = "info"


def set_op_status(message: str, level: str = "info") -> None:
    st.session_state["op_status"] = message
    st.session_state["op_status_level"] = level


def percent_dict_from_editor(df: pd.DataFrame, percent_col: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        group = row.get("Group")
        value = row.get(percent_col)
        if group is None or pd.isna(value) or value is None or str(value).strip() == "":
            continue
        try:
            out[str(group).strip()] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def combined_workbook_path() -> Path | None:
    """Combined workbook produced in step 0 (session temp folder only)."""
    raw = st.session_state.get("combined_path") or ""
    if not str(raw).strip():
        return None
    p = Path(str(raw).strip()).expanduser().resolve()
    return p if p.is_file() else None


if "auto_preview_boot" not in st.session_state:
    st.session_state["auto_preview_boot"] = True
    if combined_workbook_path() is not None:
        st.session_state["auto_preview_next"] = True


def count_records_by_tab(workbook_path: Path) -> dict[str, int]:
    if not workbook_path.is_file():
        return {}
    try:
        xl = pd.ExcelFile(workbook_path)
        out: dict[str, int] = {}
        for name in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=name)
            out[name] = int(len(df))
        return out
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def cached_build_report_summary(
    workbook_path_str: str,
    workbook_mtime_ns: int,
    mapping_items: tuple[tuple[str, str], ...],
    additional_excluded_items: tuple[str, ...],
    merge_daily_yaml: bool,
):
    _ = workbook_mtime_ns
    daily = DailyExclusionInput(additional_excluded_customer_groups=list(additional_excluded_items))
    return build_report_summary(
        Path(workbook_path_str),
        customer_group_mapping_overrides=dict(mapping_items),
        daily_exclusions=daily,
        merge_daily_yaml=merge_daily_yaml,
    )


def freeze_manual_rows(rows: list[dict[str, object]]) -> tuple[tuple[object, ...], ...]:
    frozen: list[tuple[object, ...]] = []
    for row in rows:
        frozen.append(
            (
                str(row.get("chain", "")),
                str(row.get("group", "")),
                *[float(row.get(c, 0.0) or 0.0) for c in STATUS_COLUMNS],
            )
        )
    return tuple(frozen)


@st.cache_data(show_spinner=False)
def cached_reporting_groups(mapping_path_str: str, mtime_ns: int) -> list[str]:
    _ = mtime_ns
    return reporting_groups_from_mapping(Path(mapping_path_str))


@st.cache_data(show_spinner=False)
def cached_nr_gc_sd_defaults(nr_yaml_path_str: str, mtime_ns: int) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    _ = mtime_ns
    nr_yaml_path = Path(nr_yaml_path_str)
    return (
        load_nr_percent(nr_yaml_path),
        load_gc_percent(nr_yaml_path),
        load_sd_percent(nr_yaml_path),
    )


@st.cache_data(show_spinner=False)
def cached_exclusion_seeds(
    rules_path_str: str,
    rules_mtime_ns: int,
    daily_yaml_path_str: str,
    daily_mtime_ns: int,
) -> tuple[list[str], list[str]]:
    _ = rules_mtime_ns, daily_mtime_ns
    return (
        load_base_excluded_customer_groups(Path(rules_path_str)),
        load_daily_excluded_customer_groups(Path(daily_yaml_path_str)),
    )


def thaw_manual_rows(rows: tuple[tuple[object, ...], ...]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for item in rows:
        if len(item) != 2 + len(STATUS_COLUMNS):
            continue
        row: dict[str, object] = {"chain": item[0], "group": item[1]}
        for idx, col in enumerate(STATUS_COLUMNS, start=2):
            row[col] = item[idx]
        out.append(row)
    return out


@st.cache_data(show_spinner=False)
def cached_write_product_workbook_bytes(
    workbook_path_str: str,
    workbook_mtime_ns: int,
    mapping_items: tuple[tuple[str, str], ...],
    nr_items: tuple[tuple[str, float], ...],
    gc_items: tuple[tuple[str, float], ...],
    sd_items: tuple[tuple[str, float], ...],
    manual_rows_frozen: tuple[tuple[object, ...], ...],
    additional_excluded_items: tuple[str, ...],
    reported_total: int | None,
    merge_daily_yaml: bool,
    report3_items: tuple[tuple[str, float], ...],
) -> bytes:
    _ = workbook_mtime_ns
    manual_context = {"excluded_group_status_values": thaw_manual_rows(manual_rows_frozen)}
    daily = DailyExclusionInput(
        additional_excluded_customer_groups=list(additional_excluded_items),
        excluded_customer_groups_reported_total=reported_total,
    )
    return write_product_workbook_bytes(
        Path(workbook_path_str),
        nr_percent=dict(nr_items) if nr_items else None,
        gc_percent=dict(gc_items) if gc_items else None,
        sd_percent=dict(sd_items) if sd_items else None,
        manual_context=manual_context,
        report3_inputs=dict(report3_items),
        daily_exclusions=daily,
        merge_daily_yaml=merge_daily_yaml,
        customer_group_mapping_overrides=dict(mapping_items),
    )


def parse_manual_adjustments(df: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, row in df.iterrows():
        chain = str(row.get("chain", "")).strip()
        group = str(row.get("group", "")).strip()
        has_value = any(str(row.get(c, "")).strip() not in ("", "None", "nan") for c in STATUS_COLUMNS)
        if not chain and not group and not has_value:
            continue
        if not chain or not group:
            continue
        item: dict[str, object] = {"chain": chain, "group": group}
        for col in STATUS_COLUMNS:
            raw = row.get(col)
            try:
                val = float(raw) if raw is not None and str(raw).strip() != "" else 0.0
            except (TypeError, ValueError):
                val = 0.0
            item[col] = round(val, 2)
        rows.append(item)
    return rows


def seed_manual_adjustments(base: list[str], daily_seed: list[str], extra: list[str]) -> pd.DataFrame:
    seen: set[str] = set()
    merged: list[str] = []
    for name in [*base, *daily_seed, *extra]:
        s = str(name).strip()
        if not s:
            continue
        k = s.casefold()
        if k in seen:
            continue
        seen.add(k)
        merged.append(s)
    data = []
    daily_norm = {str(x).strip().casefold() for x in daily_seed}
    for x in merged:
        default_group = MARKETPLACE_DEFAULT_GROUP if x.casefold() in daily_norm else ""
        row: dict[str, object] = {"chain": x, "group": default_group}
        for c in STATUS_COLUMNS:
            row[c] = None
        data.append(row)
    return pd.DataFrame(data, columns=["chain", "group", *STATUS_COLUMNS])


def parse_mapping_overrides(df: pd.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        cg = str(row.get("Customer Group", "")).strip()
        grp = str(row.get("Group", "")).strip()
        if cg and grp:
            out[cg] = grp
    return out


def _norm_group_key(name: str) -> str:
    s = str(name).strip().casefold()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def map_defaults_to_groups(groups: list[str], defaults: dict[str, float]) -> dict[str, float]:
    """Map default % values to canonical groups, tolerant to spacing/punctuation differences."""
    d_norm = {_norm_group_key(k): v for k, v in defaults.items()}
    out: dict[str, float] = {}
    for g in groups:
        k = _norm_group_key(g)
        if k in d_norm:
            out[g] = float(d_norm[k])
    return out


def apply_calculated_columns(base: pd.DataFrame, calc_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add calculated columns from rows:
    new_column, left_column, operator, right_column
    """
    out = base.copy()
    if calc_df is None or calc_df.empty:
        return out
    numeric_cache: dict[str, pd.Series] = {}

    def _numeric(col: str) -> pd.Series:
        if col not in numeric_cache:
            numeric_cache[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        return numeric_cache[col]

    for _, row in calc_df.iterrows():
        new_col = str(row.get("new_column", "")).strip()
        left = str(row.get("left_column", "")).strip()
        op = str(row.get("operator", "")).strip()
        right = str(row.get("right_column", "")).strip()
        if not new_col or not left or not op or not right:
            continue
        if left not in out.columns or right not in out.columns:
            continue
        a = _numeric(left)
        b = _numeric(right)
        if op == "+":
            out[new_col] = (a + b).round(2)
        elif op == "-":
            out[new_col] = (a - b).round(2)
        elif op == "*":
            out[new_col] = (a * b).round(2)
        elif op == "/":
            out[new_col] = (a / b.replace(0, pd.NA)).fillna(0.0).round(2)
    return out


def build_adjustment_rows(adjust_df: pd.DataFrame, group_source: pd.DataFrame) -> pd.DataFrame:
    """
    Build manual/custom rows:
    line_item, operation(+/-), group, metric, manual_adjustment
    amount = (+/- group metric total) + manual_adjustment
    """
    if adjust_df is None or adjust_df.empty:
        return pd.DataFrame(columns=["Line Item", "Amount"])
    rows: list[dict[str, object]] = []
    group_metric_totals: dict[tuple[str, str], float] = {}
    group_series = group_source["Group"].astype(str).str.strip().str.casefold()
    for _, row in adjust_df.iterrows():
        line = str(row.get("line_item", "")).strip()
        op = str(row.get("operation", "+")).strip() or "+"
        grp = str(row.get("group", "")).strip()
        metric = str(row.get("metric", "")).strip()
        if not line:
            continue
        base = 0.0
        if grp and metric and metric in group_source.columns:
            key = (grp.casefold(), metric)
            if key not in group_metric_totals:
                subset = group_source[group_series == grp.casefold()]
                group_metric_totals[key] = float(pd.to_numeric(subset[metric], errors="coerce").fillna(0.0).sum())
            base = group_metric_totals[key]
            if op == "-":
                base = -base
        manual_val = row.get("manual_adjustment")
        try:
            manual_amt = float(manual_val) if manual_val is not None and str(manual_val).strip() != "" else 0.0
        except (TypeError, ValueError):
            manual_amt = 0.0
        rows.append({"Line Item": line, "Amount": round(base + manual_amt, 2)})
    return pd.DataFrame(rows)


# 0) One-click export + combined workbook (session temp only; no project downloads folder)
st.subheader("0. Fetch Reports (Daily Run)")
st.caption(
    "One click: log in, download report ZIPs, merge into **combined_reports.xlsx**, then continue to step 3. "
    "Files live in a temporary session folder (not saved under the project)."
)
if st.session_state["op_status_level"] == "success":
    st.success(st.session_state["op_status"])
elif st.session_state["op_status_level"] == "error":
    st.error(st.session_state["op_status"])
else:
    st.info(st.session_state["op_status"])

if st.button("Run export & build combined workbook", type="primary", key="fetch_and_combine"):
    set_op_status("Exporting reports from the website…", "info")
    try:
        work = Path(st.session_state["studio_work_dir"])
        work.mkdir(parents=True, exist_ok=True)
        with st.spinner("Exporting reports (browser)…"):
            export_all_order_reports(root, download_dir=work)
        st.session_state["download_dir"] = str(work)
        st.session_state["last_scrape_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with st.spinner("Calculating daily Cutover from T-1 history..."):
            automatic_cutover = run_automatic_cutover(
                work,
                history_dir=CUTOVER_HISTORY_DIR,
                mapping_path=mapping_path,
                rules_path=rules_path,
                nr_percent=load_nr_percent(default_nr_yaml),
            )
            st.session_state["automatic_cutover"] = automatic_cutover
        set_op_status("Merging ZIPs into combined workbook…", "info")
        with st.spinner("Merging into combined_reports.xlsx…"):
            out = merge_report_zips_to_excel(work, work / "combined_reports.xlsx")
        st.session_state["combined_path"] = str(out.resolve())
        st.session_state["last_combine_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state["record_counts"] = count_records_by_tab(out)
        st.session_state["auto_preview_next"] = True
        set_op_status("Export and merge finished. You can continue from step 3.", "success")
        st.success("Combined workbook is ready. Continue with NR% / exclusions / preview below.")
        with out.open("rb") as f:
            st.download_button(
                label="Download combined_reports.xlsx (optional)",
                data=f.read(),
                file_name="combined_reports.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="combined_dl",
            )
    except Exception as e:
        set_op_status(f"Export or merge failed: {e}", "error")
        st.exception(e)

with st.expander("Run Status Panel", expanded=True):
    s1, s2 = st.columns(2)
    s1.markdown(f"**Last export time:** {st.session_state.get('last_scrape_at') or '-'}")
    s2.markdown(f"**Last merge time:** {st.session_state.get('last_combine_at') or '-'}")
    s3, s4 = st.columns(2)
    s3.markdown("**Session work folder (temp):**")
    s3.code(st.session_state.get("studio_work_dir", "-"), language=None)
    s4.markdown("**Combined workbook:**")
    s4.code(st.session_state.get("combined_path") or "-", language=None)
    rec = st.session_state.get("record_counts", {}) or {}
    if rec:
        rec_df = pd.DataFrame([{"Tab": k, "Records": v} for k, v in rec.items()])
        st.dataframe(rec_df, hide_index=True, use_container_width=True)
    else:
        st.caption("Record counts will appear after a successful export in step 0.")

st.divider()

# 1) Data source (combined workbook only — no manual upload)
st.subheader("1. Combined orders file")
_src = combined_workbook_path()
if _src is not None:
    st.success(f"Using combined workbook: `{_src}`")
else:
    st.warning(
        "No combined workbook yet. Run **Run export & build combined workbook** in step 0, then continue from step 3 / Preview."
    )

# 2) Exclusions
st.subheader("2. Exclusions for this run")
st.caption("These chains are excluded from automatic totals. You can add more chains dynamically.")
additional_excluded_text = st.text_area("Additional excluded chains (one per line)", height=120, placeholder="Example:\nSome New Chain")
reported_excl = st.number_input("Reported number of excluded customer groups (optional audit)", min_value=0, value=0, step=1)
merge_server_daily = st.checkbox("Also merge server daily.yaml (advanced)", value=False)
additional_excluded = parse_excluded_groups_multiline(additional_excluded_text)

# 3) NR%, GC%, and SD%
st.subheader("3. NR%, GC%, and SD% by reporting group")
groups = cached_reporting_groups(str(mapping_path), mapping_path.stat().st_mtime_ns)
raw_nr_defaults, raw_gc_defaults, raw_sd_defaults = cached_nr_gc_sd_defaults(
    str(default_nr_yaml), default_nr_yaml.stat().st_mtime_ns
)
nr_defaults = map_defaults_to_groups(groups, raw_nr_defaults)
gc_defaults = map_defaults_to_groups(groups, raw_gc_defaults)
sd_defaults = map_defaults_to_groups(groups, raw_sd_defaults)
nr_df = pd.DataFrame(
    [{"Group": g, "NR %": nr_defaults.get(g), "GC %": gc_defaults.get(g), "SD %": sd_defaults.get(g)} for g in groups]
)
edited_nr = st.data_editor(
    nr_df,
    column_config={
        "NR %": st.column_config.NumberColumn("NR %", min_value=0.0, max_value=100.0, step=0.01, format="%.2f"),
        "GC %": st.column_config.NumberColumn("GC %", min_value=0.0, max_value=100.0, step=0.01, format="%.2f"),
        "SD %": st.column_config.NumberColumn("SD %", min_value=0.0, max_value=100.0, step=0.01, format="%.2f"),
    },
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    key="nr_editor",
)

# 4) Manual additions
st.subheader("4. Manual additions for excluded chains")
st.caption("Map each excluded chain to Group and enter status values. These rows are injected into Customer Pivot.")
base_excluded, daily_seed_excluded = cached_exclusion_seeds(
    str(rules_path),
    rules_path.stat().st_mtime_ns,
    str(daily_yaml_path),
    daily_yaml_path.stat().st_mtime_ns,
)
seed_df = seed_manual_adjustments(base_excluded, daily_seed_excluded, additional_excluded)
group_options = groups
manual_adjust_df = st.data_editor(
    seed_df,
    column_config={
        "chain": st.column_config.TextColumn("Excluded Chain"),
        "group": st.column_config.SelectboxColumn("Group", options=group_options, required=False),
        "Quotation Approved": st.column_config.NumberColumn("Quotation Approved", step=0.01, format="%.2f"),
        "Quotation Pending": st.column_config.NumberColumn("Quotation Pending", step=0.01, format="%.2f"),
        "Ready To Ship": st.column_config.NumberColumn("Ready to Ship", step=0.01, format="%.2f"),
        "Shipped": st.column_config.NumberColumn("Shipped", step=0.01, format="%.2f"),
        "Returned": st.column_config.NumberColumn("Returned", step=0.01, format="%.2f"),
        "Expired": st.column_config.NumberColumn("Expired", step=0.01, format="%.2f"),
    },
    hide_index=True,
    use_container_width=True,
    num_rows="dynamic",
    key="manual_adjust_editor",
)

# 5) Unmapped groups gate
st.subheader("5. Unmapped customer groups (required)")
st.caption("If any customer group has no Group mapping, map it here before Preview or Generate.")
mapping_overrides_df = st.session_state.get("mapping_overrides_df", pd.DataFrame(columns=["Customer Group", "Group"]))
if st.button("Scan unmapped customer groups"):
    src = combined_workbook_path()
    if src is None:
        st.error("Combined workbook not found. Run **Run export & build combined workbook** in step 0 first.")
    else:
        try:
            set_op_status("Scanning unmapped customer groups...", "info")
            with st.spinner("Scanning unmapped customer groups..."):
                _, pivot_scan, _ = cached_build_report_summary(
                    str(src.resolve()),
                    src.stat().st_mtime_ns,
                    tuple(sorted(parse_mapping_overrides(mapping_overrides_df).items())),
                    tuple(additional_excluded),
                    merge_server_daily,
                )
                unmapped = sorted(
                    pivot_scan[pivot_scan["Group"].astype(str).str.strip() == ""]["Customer Group"].astype(str).drop_duplicates().tolist(),
                    key=str.casefold,
                )
                st.session_state["mapping_overrides_df"] = pd.DataFrame(
                    [{"Customer Group": x, "Group": ""} for x in unmapped]
                )
            set_op_status(f"Scan completed. Found {len(unmapped)} unmapped customer group(s).", "success")
            st.success(f"Found {len(unmapped)} unmapped customer group(s).")
        except Exception as e:
            set_op_status(f"Unmapped group scan failed: {e}", "error")
            st.exception(e)

mapping_overrides_df = st.session_state.get("mapping_overrides_df", pd.DataFrame(columns=["Customer Group", "Group"]))
mapping_overrides_df = st.data_editor(
    mapping_overrides_df,
    column_config={
        "Customer Group": st.column_config.TextColumn("Customer Group", disabled=True),
        "Group": st.column_config.SelectboxColumn("Map to Group", options=group_options, required=False),
    },
    hide_index=True,
    use_container_width=True,
    num_rows="dynamic",
    key="map_editor",
)
st.session_state["mapping_overrides_df"] = mapping_overrides_df
mapping_overrides = parse_mapping_overrides(mapping_overrides_df)
unresolved_count = 0
if not mapping_overrides_df.empty:
    unresolved_count = int((mapping_overrides_df["Group"].astype(str).str.strip() == "").sum())
if unresolved_count > 0:
    st.warning(f"{unresolved_count} unmapped customer groups still need mapping.")

# 6) Generate / Preview
st.subheader("6. Generate & Preview")
st.markdown("**Report 3 Manual Inputs (Summary Excluding HOM)**")
r3c1, r3c2, r3c3, r3c4 = st.columns(4)
marico_offtake_gross = r3c1.number_input("Marico Offtake Gross", value=0.0, step=0.01, format="%.2f")
marico_offtake_nr_percent = r3c2.number_input("Marico Offtake NR %", value=0.0, step=0.01, format="%.2f")
other_adjustment_gross = r3c3.number_input("Other Adjustment Gross", value=0.0, step=0.01, format="%.2f")
other_adjustment_nr = r3c4.number_input("Other Adjustment NR", value=0.0, step=0.01, format="%.2f")
col_a, col_b = st.columns(2)
build_clicked = col_a.button("Build Excel report", type="primary")
preview_clicked = col_b.button("Load preview tables")
auto_preview_next = bool(st.session_state.pop("auto_preview_next", False))

if build_clicked or preview_clicked or auto_preview_next:
    src = combined_workbook_path()
    if src is None:
        st.error("Combined workbook not found. Run **Run export & build combined workbook** in step 0 first.")
    elif unresolved_count > 0:
        st.error("Resolve all unmapped customer groups in section 5 before proceeding.")
    else:
        do_preview = preview_clicked or auto_preview_next
        do_build = build_clicked
        manual_rows = parse_manual_adjustments(manual_adjust_df)
        manual_context = {"excluded_group_status_values": manual_rows}
        nr_map = percent_dict_from_editor(edited_nr, "NR %")
        gc_map = percent_dict_from_editor(edited_nr, "GC %")
        sd_map = percent_dict_from_editor(edited_nr, "SD %")
        try:
            if do_build:
                action_label = "Build Excel report"
            elif do_preview:
                action_label = "Load preview tables"
            else:
                action_label = "Update"
            set_op_status(f"{action_label} started...", "info")
            with st.spinner(f"{action_label} in progress..."):
                # Validate mapping completeness against current dataset.
                _, pivot_scan, _ = cached_build_report_summary(
                    str(src.resolve()),
                    src.stat().st_mtime_ns,
                    tuple(sorted(mapping_overrides.items())),
                    tuple(additional_excluded),
                    merge_server_daily,
                )
            unresolved_now = pivot_scan[pivot_scan["Group"].astype(str).str.strip() == ""]["Customer Group"].astype(str).drop_duplicates().tolist()
            if unresolved_now:
                st.session_state["mapping_overrides_df"] = pd.DataFrame(
                    [{"Customer Group": x, "Group": ""} for x in sorted(unresolved_now, key=str.casefold)]
                )
                st.error("New unmapped customer groups found. Map them in section 5 and retry.")
                set_op_status("Stopped: new unmapped customer groups found. Map them in section 5 and retry.", "error")
            else:
                if do_preview:
                    with st.spinner("Preparing preview tables..."):
                        pivot_df = apply_manual_rows_to_customer_pivot(pivot_scan, manual_context)
                        group_df = rollup_by_reporting_group(pivot_df)
                        group_df = apply_nr_percent(group_df, nr_map if nr_map else load_nr_percent(default_nr_yaml))
                        group_df = apply_gc_percent(group_df, gc_map if gc_map else load_gc_percent(default_nr_yaml))
                        group_df = apply_sd_percent(group_df, sd_map if sd_map else load_sd_percent(default_nr_yaml))
                        gross_df = build_gross_sale_report(group_df)
                        pipeline_nr_df = build_pipeline_nr_report(group_df)
                        summary_ex_hom_df = build_summary_excluding_hom_report(
                            group_df,
                            marico_offtake_gross=marico_offtake_gross,
                            marico_offtake_nr_percent=marico_offtake_nr_percent,
                            other_adjustment_gross=other_adjustment_gross,
                            other_adjustment_nr=other_adjustment_nr,
                        )
                        st.session_state["pivot_df"] = pivot_df
                        st.session_state["group_df"] = group_df
                        st.session_state["gross_df"] = gross_df
                        st.session_state["pipeline_nr_df"] = pipeline_nr_df
                        st.session_state["summary_ex_hom_df"] = summary_ex_hom_df
                    st.success("Preview loaded.")
                    set_op_status("Preview completed successfully.", "success")
                if do_build:
                    with st.spinner("Building final Excel report..."):
                        data = cached_write_product_workbook_bytes(
                            str(src.resolve()),
                            src.stat().st_mtime_ns,
                            tuple(sorted(mapping_overrides.items())),
                            tuple(sorted((nr_map if nr_map else {}).items())),
                            tuple(sorted((gc_map if gc_map else {}).items())),
                            tuple(sorted((sd_map if sd_map else {}).items())),
                            freeze_manual_rows(manual_rows),
                            tuple(additional_excluded),
                            int(reported_excl) if reported_excl > 0 else None,
                            merge_server_daily,
                            tuple(
                                sorted(
                                    {
                                        "marico_offtake_gross": marico_offtake_gross,
                                        "marico_offtake_nr_percent": marico_offtake_nr_percent,
                                        "other_adjustment_gross": other_adjustment_gross,
                                        "other_adjustment_nr": other_adjustment_nr,
                                    }.items()
                                )
                            ),
                        )
                    st.success("Report ready.")
                    set_op_status("Build completed successfully. Report is ready for download.", "success")
                    st.download_button(
                        label="Download te_product_report.xlsx",
                        data=data,
                        file_name="te_product_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
        except Exception as e:
            set_op_status(f"Operation failed: {e}", "error")
            st.exception(e)

pivot_df = st.session_state.get("pivot_df")
group_df = st.session_state.get("group_df")
gross_df = st.session_state.get("gross_df")
pipeline_nr_df = st.session_state.get("pipeline_nr_df")
summary_ex_hom_df = st.session_state.get("summary_ex_hom_df")
if pivot_df is not None and group_df is not None:
    t1, t2, t3, t4, t5, t6 = st.tabs(
        ["Customer pivot", "Group summary", "Custom pivot", "Gross Sale Report", "Pipeline NR Report", "Summary Excluding HOM"]
    )
    with t1:
        st.dataframe(pivot_df, use_container_width=True)
    with t2:
        st.dataframe(group_df, use_container_width=True)
    with t3:
        st.caption(
            "Create multiple custom pivots in one go. "
            "Each report can include base fields, calculated columns, and custom adjustment rows."
        )
        report_count = st.number_input("How many custom reports to generate now?", min_value=1, max_value=8, value=3, step=1)
        # Build editors first; ``st.session_state[key]`` for data_editor is edit metadata (dict), not a DataFrame.
        # We must use each ``st.data_editor`` return value, so the generate button runs after this loop.
        calc_editor_frames: list[pd.DataFrame] = []
        adj_editor_frames: list[pd.DataFrame] = []
        for i in range(int(report_count)):
            prefix = f"pv_{i}"
            with st.expander(f"Report {i+1} settings", expanded=(i == 0)):
                title = st.text_input("Report title", value=f"Custom Report {i+1}", key=f"{prefix}_title")
                source = st.selectbox("Dataset", ["Pivot_Summary", "Group_Summary"], index=1, key=f"{prefix}_ds")
                df_cfg = pivot_df if source == "Pivot_Summary" else group_df
                cols_cfg = list(df_cfg.columns)
                index_cols = st.multiselect(
                    "Rows (index)",
                    cols_cfg,
                    default=(["Group"] if "Group" in cols_cfg else []),
                    key=f"{prefix}_ix",
                )
                value_cols = st.multiselect("Values", [c for c in cols_cfg if c not in index_cols], key=f"{prefix}_v")
                agg = st.selectbox("Aggregation", ["sum", "mean", "count", "min", "max"], index=0, key=f"{prefix}_agg")
                filt_col = st.selectbox("Filter column (optional)", ["—"] + cols_cfg, key=f"{prefix}_fc")
                filt_val = st.text_input("Filter value", key=f"{prefix}_fv")

                st.markdown("**Calculated Columns (optional)**")
                calc_seed = pd.DataFrame(columns=["new_column", "left_column", "operator", "right_column"])
                calc_edited = st.data_editor(
                    calc_seed,
                    column_config={
                        "new_column": st.column_config.TextColumn("New Column"),
                        "left_column": st.column_config.SelectboxColumn("Left", options=cols_cfg),
                        "operator": st.column_config.SelectboxColumn("Op", options=["+", "-", "*", "/"]),
                        "right_column": st.column_config.SelectboxColumn("Right", options=cols_cfg),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"{prefix}_calc_df",
                )

                st.markdown("**Adjustment / Manual Rows (optional)**")
                metric_opts = [c for c in group_df.columns if c != "Group"]
                adj_seed = pd.DataFrame(columns=["line_item", "operation", "group", "metric", "manual_adjustment"])
                adj_edited = st.data_editor(
                    adj_seed,
                    column_config={
                        "line_item": st.column_config.TextColumn("Line Item"),
                        "operation": st.column_config.SelectboxColumn("Operation", options=["+", "-"]),
                        "group": st.column_config.SelectboxColumn("Group", options=group_options),
                        "metric": st.column_config.SelectboxColumn("Metric", options=metric_opts),
                        "manual_adjustment": st.column_config.NumberColumn("Manual Adjustment", step=0.01, format="%.2f"),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"{prefix}_adj_df",
                )
                calc_editor_frames.append(calc_edited if isinstance(calc_edited, pd.DataFrame) else pd.DataFrame(columns=calc_seed.columns))
                adj_editor_frames.append(adj_edited if isinstance(adj_edited, pd.DataFrame) else pd.DataFrame(columns=adj_seed.columns))

        if st.button("Generate all custom reports", key="pv_multi_go"):
            results: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
            n = int(report_count)
            for i in range(n):
                prefix = f"pv_{i}"
                title = str(st.session_state.get(f"{prefix}_title", f"Custom Report {i+1}")).strip() or f"Custom Report {i+1}"
                source = st.session_state.get(f"{prefix}_ds", "Group_Summary")
                df_pv = pivot_df if source == "Pivot_Summary" else group_df
                cols_pv = list(df_pv.columns)
                index_cols = st.session_state.get(f"{prefix}_ix", ["Group"] if "Group" in cols_pv else [])
                value_cols = st.session_state.get(f"{prefix}_v", [])
                agg = st.session_state.get(f"{prefix}_agg", "sum")
                filt_col = st.session_state.get(f"{prefix}_fc", "—")
                filt_val = st.session_state.get(f"{prefix}_fv", "")

                spec: dict = {"index": index_cols, "values": value_cols, "aggfunc": agg}
                work = df_pv
                if filt_col != "—" and str(filt_val).strip():
                    work = apply_filters(df_pv, {filt_col: str(filt_val).strip()})

                calc_df = calc_editor_frames[i] if i < len(calc_editor_frames) else pd.DataFrame()
                adj_df = adj_editor_frames[i] if i < len(adj_editor_frames) else pd.DataFrame()
                try:
                    out = build_custom_view(work, spec)
                    out = apply_calculated_columns(out, calc_df)
                    adjustments = build_adjustment_rows(adj_df, group_df)
                    results.append((title, out, adjustments))
                except Exception as e:
                    st.error(f"{title}: {e}")

            st.session_state["custom_results"] = results

        results = st.session_state.get("custom_results", [])
        if results:
            st.markdown("### Generated Custom Reports")
            for idx, (title, out_df, adj_df) in enumerate(results, start=1):
                st.markdown(f"**{idx}. {title}**")
                st.dataframe(out_df, use_container_width=True)
                if not adj_df.empty:
                    st.caption("Adjustment / manual rows")
                    st.dataframe(adj_df, use_container_width=True)
                st.download_button(
                    f"Download {title} (CSV)",
                    out_df.to_csv(index=False).encode("utf-8"),
                    file_name=f"{title.replace(' ', '_').lower()}.csv",
                    mime="text/csv",
                    key=f"pv_dl_{idx}",
                )
    with t4:
        if gross_df is None:
            gross_df = build_gross_sale_report(group_df)
        st.dataframe(gross_df, use_container_width=True)
        st.download_button(
            "Download Gross Sale Report (CSV)",
            gross_df.to_csv(index=False).encode("utf-8"),
            file_name="gross_sale_report.csv",
            mime="text/csv",
            key="gross_sale_dl",
        )
    with t5:
        if pipeline_nr_df is None:
            pipeline_nr_df = build_pipeline_nr_report(group_df)
        st.dataframe(pipeline_nr_df, use_container_width=True)
        st.download_button(
            "Download Pipeline NR Report (CSV)",
            pipeline_nr_df.to_csv(index=False).encode("utf-8"),
            file_name="pipeline_nr_report.csv",
            mime="text/csv",
            key="pipeline_nr_dl",
        )
    with t6:
        if summary_ex_hom_df is None:
            summary_ex_hom_df = build_summary_excluding_hom_report(
                group_df,
                marico_offtake_gross=marico_offtake_gross,
                marico_offtake_nr_percent=marico_offtake_nr_percent,
                other_adjustment_gross=other_adjustment_gross,
                other_adjustment_nr=other_adjustment_nr,
            )
        st.dataframe(summary_ex_hom_df, use_container_width=True)
        st.download_button(
            "Download Summary Excluding HOM (CSV)",
            summary_ex_hom_df.to_csv(index=False).encode("utf-8"),
            file_name="summary_excluding_hom_report.csv",
            mime="text/csv",
            key="summary_ex_hom_dl",
        )

st.divider()
st.subheader("7. Daily Cutover (T-1 vs T)")
st.caption(
    "No upload is required. Step 0 automatically uses today's downloaded File 3 and File 4, compares them with the latest "
    "earlier File 4 snapshot, generates Cutover, and saves today's File 4 for the next run."
)
with st.expander("Calculation rule", expanded=False):
    st.markdown(
        "**Qualifying movement:** QP/QA at T-1 → RTS/Shipped at T.  "
        "\n**Gross Amount:** today's inclusive-tax value for the qualifying line.  "
        "\n**NR:** Gross Amount × the monthly NR%.  "
        "\nThe workbook also retains literal T − T-1 quantity and amount differences for audit. "
        "The first run seeds the T-1 history; subsequent daily runs calculate automatically."
    )
automatic_cutover = st.session_state.get("automatic_cutover")
if automatic_cutover is None:
    st.info("Run **Fetch Reports (Daily Run)** in step 0. Cutover will run as part of the same operation.")
elif automatic_cutover.status == "seeded":
    st.warning(automatic_cutover.message)
elif automatic_cutover.status == "unmapped":
    st.error(automatic_cutover.message)
else:
    st.success(automatic_cutover.message)

cutover_result = automatic_cutover.result if automatic_cutover is not None else None
if cutover_result is not None and not cutover_result.unmapped_groups:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("T-1 lines checked", f"{len(cutover_result.detail):,}")
    c2.metric("Qualifying movements", f"{int(cutover_result.detail['Qualifying Transition'].sum()):,}")
    c3.metric("Cancelled / not found", f"{int((cutover_result.detail['Status T'] == 'Cancelled').sum()):,}")
    c4.metric("Excluded source rows", f"{cutover_result.excluded_rows:,}")
    cut_summary_tab, cut_detail_tab = st.tabs(["Cutover Summary", "Detailed Audit"])
    with cut_summary_tab:
        st.dataframe(cutover_result.summary, hide_index=True, use_container_width=True)
    with cut_detail_tab:
        st.dataframe(cutover_result.detail, hide_index=True, use_container_width=True)
    st.download_button(
        "Download Cutover Excel",
        data=cutover_workbook_bytes(cutover_result),
        file_name=f"TE_Cutover_{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="cutover_excel_download",
    )
