"""Merge report ZIP exports into one multi-sheet Excel workbook."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.output.manual_merge import merge_report_zips_to_excel


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Merge report ZIPs into combined_reports.xlsx.")
    parser.add_argument(
        "--input",
        type=Path,
        default=root / "downloads" / "exports",
        help="Folder containing *.zip report exports",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .xlsx path (default: <input>/combined_reports.xlsx)",
    )
    args = parser.parse_args()
    input_dir = args.input
    out = args.output or (input_dir / "combined_reports.xlsx")
    path = merge_report_zips_to_excel(input_dir, out)
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
