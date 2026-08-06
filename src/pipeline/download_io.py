"""Load exported report files: direct CSV/XLSX, or ZIP archives containing one or more CSVs."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd


def read_downloaded_report(path: Path) -> pd.DataFrame:
    """Load tabular data from an export path (CSV, Excel, or ZIP of CSVs)."""
    suf = path.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(path)
    if suf == ".zip":
        return _read_zip_csvs(path)
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path)
    # Fallback: try Excel then CSV
    try:
        return pd.read_excel(path)
    except Exception:
        return pd.read_csv(path)


def _read_zip_csvs(path: Path) -> pd.DataFrame:
    """Concatenate all CSV files inside a zip (each file ≈ one logical sheet/tab)."""
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = sorted(
            n
            for n in zf.namelist()
            if n.lower().endswith(".csv") and not Path(n).name.startswith(".") and "__MACOSX" not in n
        )
        if not names:
            raise ValueError(f"No CSV files found in zip: {path}")
        for name in names:
            with zf.open(name) as f:
                df = pd.read_csv(f)
                if len(names) > 1:
                    df["_source_csv"] = Path(name).name
                frames.append(df)
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True, sort=False)


def path_for_export_save(output_path: Path, suggested_filename: str) -> Path:
    """Use output_path stem + extension from browser suggested download name (e.g. .zip, .csv)."""
    stem = output_path.stem
    parent = output_path.parent
    ext = Path(suggested_filename or "").suffix
    if not ext:
        ext = ".zip"
    return parent / f"{stem}{ext}"
