"""Assemble the full product Excel workbook (summaries + manual inputs + custom views)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd

from src.product.custom_view import build_custom_view, load_views_from_dir
from src.product.group_rollup import apply_gc_percent, apply_nr_percent, apply_sd_percent, rollup_by_reporting_group
from src.product.inputs import (
    apply_manual_group_adjustments,
    apply_manual_rows_to_customer_pivot,
    audit_table,
    load_gc_percent,
    load_manual_context,
    load_nr_percent,
    load_sd_percent,
    manual_context_table,
)
from src.product.runtime_inputs import DailyExclusionInput
from src.product.standard_reports import (
    build_gross_sale_report,
    build_pipeline_nr_report,
    build_summary_excluding_hom_report,
)
from src.transform.report_summary import build_report_summary


def _safe_sheet_name(name: str, fallback: str = "Sheet") -> str:
    invalid = "[]:*?/\\"
    s = (name or fallback).strip() or fallback
    for c in invalid:
        s = s.replace(c, "_")
    return s[:31]


def _source_frames(
    pivot_df: pd.DataFrame,
    group_df: pd.DataFrame,
    gross_sale_df: pd.DataFrame,
    pipeline_nr_df: pd.DataFrame,
    summary_ex_hom_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    return {
        "Pivot_Summary": pivot_df,
        "pivot_customer": pivot_df,
        "Group_Summary": group_df,
        "group": group_df,
        "Gross_Sale_Report": gross_sale_df,
        "gross_sale_report": gross_sale_df,
        "Pipeline_NR_Report": pipeline_nr_df,
        "pipeline_nr_report": pipeline_nr_df,
        "Summary_Excluding_HOM_Report": summary_ex_hom_df,
        "summary_excluding_hom_report": summary_ex_hom_df,
    }


def _parse_nr_override(nr_percent: dict[str, float] | None) -> dict[str, float]:
    if not nr_percent:
        return {}
    out: dict[str, float] = {}
    for k, v in nr_percent.items():
        if v is None or str(v).strip() == "":
            continue
        try:
            out[str(k).strip()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _prepare_product_frames(
    combined_xlsx: Path,
    *,
    nr_percent_path: Path,
    manual_context_path: Path,
    daily_inputs_path: Path,
    report_views_dir: Path,
    rules_path: Path | None,
    mapping_path: Path | None,
    customer_group_mapping_overrides: dict[str, str] | None,
    nr_percent: dict[str, float] | None,
    gc_percent: dict[str, float] | None,
    sd_percent: dict[str, float] | None,
    manual_context: dict[str, Any] | None,
    report3_inputs: dict[str, float] | None,
    daily_exclusions: DailyExclusionInput | None,
    merge_daily_yaml: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list, dict]:
    unique_df, pivot_df, meta = build_report_summary(
        combined_xlsx,
        rules_path=rules_path,
        mapping_path=mapping_path,
        customer_group_mapping_overrides=customer_group_mapping_overrides,
        daily_inputs_path=daily_inputs_path,
        daily_exclusions=daily_exclusions,
        merge_daily_yaml=merge_daily_yaml,
    )
    if nr_percent is not None:
        nr = _parse_nr_override(nr_percent)
    else:
        nr = load_nr_percent(nr_percent_path)
    if gc_percent is not None:
        gc = _parse_nr_override(gc_percent)
    else:
        gc = load_gc_percent(nr_percent_path)
    if sd_percent is not None:
        sd = _parse_nr_override(sd_percent)
    else:
        sd = load_sd_percent(nr_percent_path)

    if manual_context is not None:
        manual = dict(manual_context)
    else:
        manual = load_manual_context(manual_context_path)
    pivot_df = apply_manual_rows_to_customer_pivot(pivot_df, manual)
    unique_vals = sorted(pivot_df["Customer Group"].astype(str).drop_duplicates().tolist(), key=str.casefold)
    unique_df = pd.DataFrame({"Customer Group": unique_vals})
    group_df = rollup_by_reporting_group(pivot_df)
    group_df = apply_manual_group_adjustments(group_df, manual)
    group_df = apply_nr_percent(group_df, nr)
    group_df = apply_gc_percent(group_df, gc)
    group_df = apply_sd_percent(group_df, sd)
    gross_sale_df = build_gross_sale_report(group_df)
    pipeline_nr_df = build_pipeline_nr_report(group_df)
    r3 = report3_inputs or {}
    summary_ex_hom_df = build_summary_excluding_hom_report(
        group_df,
        marico_offtake_gross=float(r3.get("marico_offtake_gross", 0.0) or 0.0),
        marico_offtake_nr_percent=float(r3.get("marico_offtake_nr_percent", 0.0) or 0.0),
        other_adjustment_gross=float(r3.get("other_adjustment_gross", 0.0) or 0.0),
        other_adjustment_nr=float(r3.get("other_adjustment_nr", 0.0) or 0.0),
    )
    manual_df = manual_context_table(manual)
    audit_df = audit_table(meta)

    sources = _source_frames(pivot_df, group_df, gross_sale_df, pipeline_nr_df, summary_ex_hom_df)
    views = load_views_from_dir(report_views_dir)
    return unique_df, pivot_df, group_df, gross_sale_df, pipeline_nr_df, summary_ex_hom_df, manual_df, audit_df, views, sources


def _write_sheets_to_writer(
    writer: pd.ExcelWriter,
    *,
    unique_df: pd.DataFrame,
    pivot_df: pd.DataFrame,
    group_df: pd.DataFrame,
    gross_sale_df: pd.DataFrame,
    pipeline_nr_df: pd.DataFrame,
    summary_ex_hom_df: pd.DataFrame,
    manual_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    views: list,
    sources: dict[str, pd.DataFrame],
) -> None:
    used_names: set[str] = set()

    def add_sheet(name: str, frame: pd.DataFrame) -> None:
        base = _safe_sheet_name(name)
        sheet = base
        n = 2
        while sheet in used_names:
            suf = f"_{n}"
            sheet = (base[: 31 - len(suf)] + suf) if len(base) + len(suf) > 31 else base + suf
            n += 1
        used_names.add(sheet)
        frame.to_excel(writer, sheet_name=sheet, index=False)

    add_sheet("Unique_Customer_Groups", unique_df)
    add_sheet("Pivot_Summary", pivot_df)
    add_sheet("Group_Summary", group_df)
    add_sheet("Gross_Sale_Report", gross_sale_df)
    add_sheet("Pipeline_NR_Report", pipeline_nr_df)
    add_sheet("Summary_Excluding_HOM_Report", summary_ex_hom_df)
    add_sheet("Manual_Context", manual_df)
    add_sheet("Exclusion_Audit", audit_df)

    for stem, spec in views:
        src_key = str(spec.get("source") or "Group_Summary").strip()
        df_src = sources.get(src_key)
        if df_src is None:
            df_src = sources.get(src_key.replace(" ", "_"))
        if df_src is None:
            df_src = pivot_df if "Pivot" in src_key else group_df
        try:
            view_df = build_custom_view(df_src, spec)
        except Exception as exc:  # noqa: BLE001
            view_df = pd.DataFrame({"error": [str(exc)]})
        title = spec.get("title") or stem
        add_sheet(f"View_{title}", view_df)


def write_product_workbook(
    combined_xlsx: Path,
    output_xlsx: Path,
    *,
    nr_percent_path: Path | None = None,
    manual_context_path: Path | None = None,
    daily_inputs_path: Path | None = None,
    report_views_dir: Path | None = None,
    rules_path: Path | None = None,
    mapping_path: Path | None = None,
    customer_group_mapping_overrides: dict[str, str] | None = None,
    nr_percent: dict[str, float] | None = None,
    gc_percent: dict[str, float] | None = None,
    sd_percent: dict[str, float] | None = None,
    manual_context: dict[str, Any] | None = None,
    report3_inputs: dict[str, float] | None = None,
    daily_exclusions: DailyExclusionInput | None = None,
    merge_daily_yaml: bool = True,
) -> Path:
    """
    Read combined multi-tab export, apply summary rules + daily exclusions,
    and write customer pivot, group rollup with NR%/GC%/SD%, manual fields, audit, and YAML views.

    For the web UI, pass ``nr_percent``, ``manual_context``, and ``daily_exclusions`` dicts/objects
    and set ``merge_daily_yaml=False`` if operators should not depend on server YAML files.
    """
    root = Path(__file__).resolve().parents[2]
    nr_percent_path = nr_percent_path or (root / "config" / "inputs" / "nr_percent.yaml")
    manual_context_path = manual_context_path or (root / "config" / "inputs" / "manual_context.yaml")
    daily_inputs_path = daily_inputs_path or (root / "config" / "inputs" / "daily.yaml")
    report_views_dir = report_views_dir or (root / "config" / "report_views")

    unique_df, pivot_df, group_df, gross_sale_df, pipeline_nr_df, summary_ex_hom_df, manual_df, audit_df, views, sources = _prepare_product_frames(
        combined_xlsx,
        nr_percent_path=nr_percent_path,
        manual_context_path=manual_context_path,
        daily_inputs_path=daily_inputs_path,
        report_views_dir=report_views_dir,
        rules_path=rules_path,
        mapping_path=mapping_path,
        customer_group_mapping_overrides=customer_group_mapping_overrides,
        nr_percent=nr_percent,
        gc_percent=gc_percent,
        sd_percent=sd_percent,
        manual_context=manual_context,
        report3_inputs=report3_inputs,
        daily_exclusions=daily_exclusions,
        merge_daily_yaml=merge_daily_yaml,
    )

    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        _write_sheets_to_writer(
            writer,
            unique_df=unique_df,
            pivot_df=pivot_df,
            group_df=group_df,
            gross_sale_df=gross_sale_df,
            pipeline_nr_df=pipeline_nr_df,
            summary_ex_hom_df=summary_ex_hom_df,
            manual_df=manual_df,
            audit_df=audit_df,
            views=views,
            sources=sources,
        )

    return output_xlsx


def write_product_workbook_bytes(
    combined_xlsx: Path,
    *,
    nr_percent_path: Path | None = None,
    manual_context_path: Path | None = None,
    daily_inputs_path: Path | None = None,
    report_views_dir: Path | None = None,
    rules_path: Path | None = None,
    mapping_path: Path | None = None,
    customer_group_mapping_overrides: dict[str, str] | None = None,
    nr_percent: dict[str, float] | None = None,
    gc_percent: dict[str, float] | None = None,
    sd_percent: dict[str, float] | None = None,
    manual_context: dict[str, Any] | None = None,
    report3_inputs: dict[str, float] | None = None,
    daily_exclusions: DailyExclusionInput | None = None,
    merge_daily_yaml: bool = True,
) -> bytes:
    """Same as :func:`write_product_workbook` but returns an in-memory ``.xlsx`` for browser download."""
    root = Path(__file__).resolve().parents[2]
    nr_percent_path = nr_percent_path or (root / "config" / "inputs" / "nr_percent.yaml")
    manual_context_path = manual_context_path or (root / "config" / "inputs" / "manual_context.yaml")
    daily_inputs_path = daily_inputs_path or (root / "config" / "inputs" / "daily.yaml")
    report_views_dir = report_views_dir or (root / "config" / "report_views")

    unique_df, pivot_df, group_df, gross_sale_df, pipeline_nr_df, summary_ex_hom_df, manual_df, audit_df, views, sources = _prepare_product_frames(
        combined_xlsx,
        nr_percent_path=nr_percent_path,
        manual_context_path=manual_context_path,
        daily_inputs_path=daily_inputs_path,
        report_views_dir=report_views_dir,
        rules_path=rules_path,
        mapping_path=mapping_path,
        customer_group_mapping_overrides=customer_group_mapping_overrides,
        nr_percent=nr_percent,
        gc_percent=gc_percent,
        sd_percent=sd_percent,
        manual_context=manual_context,
        report3_inputs=report3_inputs,
        daily_exclusions=daily_exclusions,
        merge_daily_yaml=merge_daily_yaml,
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _write_sheets_to_writer(
            writer,
            unique_df=unique_df,
            pivot_df=pivot_df,
            group_df=group_df,
            gross_sale_df=gross_sale_df,
            pipeline_nr_df=pipeline_nr_df,
            summary_ex_hom_df=summary_ex_hom_df,
            manual_df=manual_df,
            audit_df=audit_df,
            views=views,
            sources=sources,
        )
    return buf.getvalue()
