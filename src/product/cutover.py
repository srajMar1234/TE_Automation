"""Daily cutover: track QP/QA order lines that become RTS or Shipped."""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import BinaryIO

import pandas as pd
import yaml
from openpyxl.styles import Font, PatternFill


PREVIOUS_PIPELINE = {"Quotation Pending", "Quotation Approved"}
TARGET_STATUSES = {"Ready To Ship", "Shipped"}

COLUMN_ALIASES = {
    "order_id": {"orderid", "orderno", "ordernumber"},
    "product_id": {"productid", "productcode", "sku", "skuid"},
    "product_name": {"productname", "itemname", "sku name", "description"},
    "customer_name": {"customername", "customer"},
    "customer_group": {"customergroup", "customergroupoverride", "group"},
    "order_status": {"orderstatus", "status"},
    "quantity": {"quantity", "qty", "orderquantity"},
    "amount": {
        "totalincltax",
        "totalinclusivetax",
        "salesinclusivetax",
        "salesincltax",
        "amountincltax",
    },
}

STATUS_ALIASES = {
    "quotationpending": "Quotation Pending",
    "qp": "Quotation Pending",
    "quotationapproved": "Quotation Approved",
    "qa": "Quotation Approved",
    "readytoship": "Ready To Ship",
    "rts": "Ready To Ship",
    "shipped": "Shipped",
    "complete": "Shipped",
    "completed": "Shipped",
}


@dataclass(frozen=True)
class CutoverResult:
    detail: pd.DataFrame
    summary: pd.DataFrame
    unmapped_groups: tuple[str, ...]
    excluded_rows: int


@dataclass(frozen=True)
class AutomaticCutoverResult:
    status: str
    message: str
    result: CutoverResult | None = None
    workbook_path: Path | None = None
    previous_snapshot: Path | None = None
    current_snapshot: Path | None = None


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().casefold())


def _read_one(payload: bytes, name: str) -> pd.DataFrame:
    suffix = Path(name).suffix.lower()
    stream = io.BytesIO(payload)
    if suffix == ".csv":
        return pd.read_csv(stream)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(stream)
    raise ValueError(f"Unsupported file type for {name}. Upload CSV, XLSX, XLS, or ZIP.")


def read_uploaded_report(upload: BinaryIO) -> pd.DataFrame:
    """Read a Streamlit upload, including ZIPs containing one or more CSV/XLSX files."""
    payload = upload.getvalue() if hasattr(upload, "getvalue") else upload.read()
    name = getattr(upload, "name", "report.xlsx")
    if Path(name).suffix.lower() != ".zip":
        return _read_one(payload, name)
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in sorted(archive.namelist()):
            if member.endswith("/") or "__MACOSX" in member:
                continue
            if Path(member).suffix.lower() not in {".csv", ".xlsx", ".xls"}:
                continue
            frames.append(_read_one(archive.read(member), member))
    if not frames:
        raise ValueError(f"No CSV or Excel report found inside {name}.")
    return pd.concat(frames, ignore_index=True, sort=False)


def read_report_path(path: Path) -> pd.DataFrame:
    """Read a downloaded report without requiring an upload widget."""
    class _PathUpload:
        name = path.name

        @staticmethod
        def getvalue() -> bytes:
            return path.read_bytes()

    return read_uploaded_report(_PathUpload())


def _find_downloaded_report(download_dir: Path, report_number: int) -> Path:
    supported = {".csv", ".xlsx", ".xls", ".zip"}
    candidates = [p for p in download_dir.rglob("*") if p.is_file() and p.suffix.lower() in supported]
    if report_number == 3:
        strong = [p for p in candidates if any(x in _key(p.name) for x in ("shippedreport", "allordersreport3", "report3"))]
    else:
        strong = [p for p in candidates if any(x in _key(p.name) for x in ("qpqareport", "allordersreport4", "report4"))]
    if not strong:
        label = "Shipped/File 3" if report_number == 3 else "QPQA/File 4"
        raise FileNotFoundError(f"Could not identify {label} in {download_dir}.")
    return max(strong, key=lambda p: p.stat().st_mtime_ns)


def run_automatic_cutover(
    download_dir: Path,
    *,
    history_dir: Path,
    mapping_path: Path,
    rules_path: Path,
    nr_percent: dict[str, float],
    run_date: date | None = None,
) -> AutomaticCutoverResult:
    """Calculate Cutover from today's automatic export and maintain File-4 history."""
    run_date = run_date or date.today()
    history_dir.mkdir(parents=True, exist_ok=True)
    shipped_path = _find_downloaded_report(download_dir, 3)
    qpqa_path = _find_downloaded_report(download_dir, 4)
    snapshot_path = history_dir / f"QPQA_{run_date.isoformat()}{qpqa_path.suffix.lower()}"
    previous_candidates = sorted(
        (p for p in history_dir.glob("QPQA_20*") if p.is_file() and p.name < f"QPQA_{run_date.isoformat()}"),
        key=lambda p: p.name,
    )
    if not previous_candidates:
        shutil.copy2(qpqa_path, snapshot_path)
        return AutomaticCutoverResult(
            status="seeded",
            message="Today’s QPQA report was saved as the first T-1 snapshot. Cutover will be produced on the next daily run.",
            current_snapshot=snapshot_path,
        )

    previous_path = previous_candidates[-1]
    result = build_cutover(
        read_report_path(previous_path),
        read_report_path(qpqa_path),
        read_report_path(shipped_path),
        mapping_path=mapping_path,
        rules_path=rules_path,
        nr_percent=nr_percent,
    )
    if result.unmapped_groups:
        return AutomaticCutoverResult(
            status="unmapped",
            message="Cutover requires mappings for: " + ", ".join(result.unmapped_groups),
            result=result,
            previous_snapshot=previous_path,
        )
    workbook_path = history_dir / f"TE_Cutover_{run_date.isoformat()}.xlsx"
    workbook_path.write_bytes(cutover_workbook_bytes(result))
    # Snapshot only after a successful calculation so a failed run cannot corrupt tomorrow's baseline.
    shutil.copy2(qpqa_path, snapshot_path)
    return AutomaticCutoverResult(
        status="complete",
        message=f"Automatic Cutover completed using {previous_path.name} and today’s downloaded reports.",
        result=result,
        workbook_path=workbook_path,
        previous_snapshot=previous_path,
        current_snapshot=snapshot_path,
    )


def _column_map(df: pd.DataFrame) -> dict[str, str]:
    normalized = {_key(column): str(column) for column in df.columns}
    found: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases | {canonical}:
            match = normalized.get(_key(alias))
            if match is not None:
                found[canonical] = match
                break
    missing = [x for x in ("order_id", "product_id", "order_status", "quantity", "amount") if x not in found]
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(missing) + ". Available columns: " + ", ".join(map(str, df.columns))
        )
    return found


def _prepare(df: pd.DataFrame, mapping: dict[str, str], rules: dict) -> tuple[pd.DataFrame, int]:
    columns = _column_map(df)
    out = pd.DataFrame(index=df.index)
    for canonical in COLUMN_ALIASES:
        source = columns.get(canonical)
        out[canonical] = df[source] if source else ""
    for text_col in ("order_id", "product_id", "product_name", "customer_name", "customer_group", "order_status"):
        out[text_col] = out[text_col].fillna("").astype(str).str.strip()
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").fillna(0.0)
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)
    out["order_status"] = out["order_status"].map(lambda x: STATUS_ALIASES.get(_key(x), x))

    overrides = {
        _key(item.get("customer_name", "")): str(item.get("customer_group", "")).strip()
        for item in rules.get("customer_name_overrides", [])
        if item.get("customer_name") and item.get("customer_group")
    }
    override_values = out["customer_name"].map(lambda x: overrides.get(_key(x)))
    out.loc[override_values.notna(), "customer_group"] = override_values[override_values.notna()]

    # Match the established report-summary pipeline: rows without a usable
    # Customer Group cannot be mapped or aggregated and are removed.
    blank_group = out["customer_group"].map(_key) == ""
    blank_group_count = int(blank_group.sum())
    out = out.loc[~blank_group].copy()

    exact = {_key(x) for x in rules.get("excluded_customer_groups", [])}
    substrings = [_key(x) for x in rules.get("excluded_customer_group_substrings", []) if _key(x)]
    group_keys = out["customer_group"].map(_key)
    excluded = group_keys.isin(exact) | group_keys.map(lambda x: any(part in x for part in substrings))
    excluded_count = blank_group_count + int(excluded.sum())
    out = out.loc[~excluded].copy()

    mapping_normalized = {_key(k): str(v).strip() for k, v in mapping.items()}
    out["business_group"] = out["customer_group"].map(lambda x: mapping_normalized.get(_key(x), ""))
    # The override already contains the canonical reporting group.
    out.loc[out["customer_group"].map(_key) == _key("HOM Sale"), "business_group"] = "HOM Sale"
    out["line_key"] = out["order_id"].map(_key) + "|" + out["product_id"].map(_key)
    out = out[(out["order_id"] != "") & (out["product_id"] != "")]
    return out, excluded_count


def _rollup_lines(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    stable = ["line_key", "order_id", "product_id"]
    text = ["product_name", "customer_name", "customer_group", "business_group", "order_status"]
    aggregations = {column: "first" for column in text}
    aggregations.update({"quantity": "sum", "amount": "sum"})
    return df.groupby(stable, as_index=False, dropna=False).agg(aggregations)


def build_cutover(
    previous_df: pd.DataFrame,
    today_pipeline_df: pd.DataFrame,
    today_shipped_df: pd.DataFrame,
    *,
    mapping_path: Path,
    rules_path: Path,
    nr_percent: dict[str, float],
) -> CutoverResult:
    with mapping_path.open("r", encoding="utf-8") as handle:
        mapping = (yaml.safe_load(handle) or {}).get("mapping", {})
    with rules_path.open("r", encoding="utf-8") as handle:
        rules = yaml.safe_load(handle) or {}

    previous, ex1 = _prepare(previous_df, mapping, rules)
    pipeline, ex2 = _prepare(today_pipeline_df, mapping, rules)
    shipped, ex3 = _prepare(today_shipped_df, mapping, rules)
    previous = _rollup_lines(previous[previous["order_status"].isin(PREVIOUS_PIPELINE | {"Ready To Ship"})])
    pipeline = _rollup_lines(pipeline)
    shipped = _rollup_lines(shipped[shipped["order_status"] == "Shipped"])

    # Shipped wins if a line appears in both current files.
    current = pd.concat([shipped, pipeline[~pipeline["line_key"].isin(set(shipped["line_key"]))]], ignore_index=True)
    current = current.set_index("line_key", drop=False)

    rows: list[dict[str, object]] = []
    for _, old in previous.iterrows():
        new = current.loc[old["line_key"]] if old["line_key"] in current.index else None
        if isinstance(new, pd.DataFrame):
            new = new.iloc[0]
        status_t = str(new["order_status"]) if new is not None else "Cancelled"
        qty_t = float(new["quantity"]) if new is not None else 0.0
        amount_t = float(new["amount"]) if new is not None else 0.0
        transitioned = old["order_status"] in PREVIOUS_PIPELINE and status_t in TARGET_STATUSES
        rows.append(
            {
                "Order ID": old["order_id"],
                "Product ID": old["product_id"],
                "Product Name": old["product_name"],
                "Customer Name": old["customer_name"],
                "Customer Group": old["customer_group"],
                "Business Group": old["business_group"],
                "Status T-1": old["order_status"],
                "Quantity T-1": float(old["quantity"]),
                "Inclusive Tax T-1": float(old["amount"]),
                "Status T": status_t,
                "Quantity T": qty_t,
                "Inclusive Tax T": amount_t,
                "Cutover Diff Quantity (T - T-1)": qty_t - float(old["quantity"]),
                "Cutover Diff Inclusive Tax (T - T-1)": amount_t - float(old["amount"]),
                "Qualifying Transition": transitioned,
                # A status movement often has the same amount on both days, making arithmetic delta zero.
                # Gross cutover is therefore today's value for a genuine QP/QA -> RTS/Shipped transition.
                "Cutover Gross Amount": amount_t if transitioned else 0.0,
                "Unique Key": old["line_key"],
            }
        )
    detail = pd.DataFrame(rows)
    unmapped = tuple(sorted(detail.loc[detail["Business Group"] == "", "Customer Group"].dropna().unique(), key=str.casefold))
    if unmapped:
        return CutoverResult(detail, pd.DataFrame(), unmapped, ex1 + ex2 + ex3)

    qualifying = detail[detail["Qualifying Transition"]].copy()
    if qualifying.empty:
        summary = pd.DataFrame(columns=["Business Group", "Gross Amount", "NR %", "NR"])
    else:
        summary = qualifying.groupby("Business Group", as_index=False)["Cutover Gross Amount"].sum()
        summary = summary.rename(columns={"Cutover Gross Amount": "Gross Amount"})
        nr_keys = {_key(k): float(v) for k, v in nr_percent.items()}
        summary["NR %"] = summary["Business Group"].map(lambda x: nr_keys.get(_key(x), 0.0))
        summary["NR"] = summary["Gross Amount"] * summary["NR %"] / 100.0
        total = pd.DataFrame([{
            "Business Group": "Total",
            "Gross Amount": summary["Gross Amount"].sum(),
            "NR %": pd.NA,
            "NR": summary["NR"].sum(),
        }])
        summary = pd.concat([summary, total], ignore_index=True)
    return CutoverResult(detail, summary, (), ex1 + ex2 + ex3)


def cutover_workbook_bytes(result: CutoverResult) -> bytes:
    output = io.BytesIO()
    audit = pd.DataFrame([
        {"Check": "Source rows excluded", "Value": result.excluded_rows},
        {"Check": "T-1 lines evaluated", "Value": len(result.detail)},
        {"Check": "Qualifying QP/QA to RTS/Shipped", "Value": int(result.detail["Qualifying Transition"].sum())},
        {"Check": "Cancelled/not found today", "Value": int((result.detail["Status T"] == "Cancelled").sum())},
    ])
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.detail.to_excel(writer, sheet_name="Cutover_Detail", index=False)
        result.summary.to_excel(writer, sheet_name="Cutover_Summary", index=False)
        audit.to_excel(writer, sheet_name="Audit", index=False)
        for sheet in writer.book.worksheets:
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="17365D")
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = min(42, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
                sheet.column_dimensions[column[0].column_letter].width = width
    return output.getvalue()
