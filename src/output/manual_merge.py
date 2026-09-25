"""Merge report ZIP (or CSV/XLSX) exports into one multi-sheet Excel workbook."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.pipeline.download_io import read_downloaded_report

# Preferred sheet order matches Studio / historical combined_reports.xlsx
SHEET_ORDER = (
    "Expired Report",
    "Returned Report",
    "Shipped Report",
    "QPQA Report",
)


def _sheet_name_for(path: Path) -> str:
    return path.stem


def merge_report_zips_to_excel(input_dir: Path, output_path: Path) -> Path:
    """
    Read each Expired/Returned/Shipped/QPQA export under ``input_dir`` and write
    one sheet per report into ``output_path``.
    """
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    supported = {".zip", ".csv", ".xlsx", ".xls"}
    files = [
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported and not p.name.startswith(".")
    ]
    if not files:
        raise FileNotFoundError(f"No report exports found in {input_dir}")

    by_stem = {_sheet_name_for(p): p for p in files}
    ordered_names = [name for name in SHEET_ORDER if name in by_stem]
    extras = sorted(name for name in by_stem if name not in SHEET_ORDER)
    sheet_names = ordered_names + extras

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for name in sheet_names:
            df = read_downloaded_report(by_stem[name])
            # Excel sheet names max 31 chars
            safe = name[:31]
            df.to_excel(writer, sheet_name=safe, index=False)
    return output_path.resolve()
