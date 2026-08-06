"""Build full product workbook: summaries, NR%, manual fields, custom YAML views."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.product.workbook import write_product_workbook


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Build TE product Excel from combined_reports.xlsx.")
    p.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=root / "downloads" / "exports" / "combined_reports.xlsx",
        help="Combined multi-tab workbook from merge_reports.py",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=root / "output" / "te_product_report.xlsx",
        help="Output workbook path",
    )
    p.add_argument("--nr-percent", type=Path, default=None, help="Override config/inputs/nr_percent.yaml")
    p.add_argument("--manual-context", type=Path, default=None, help="Override config/inputs/manual_context.yaml")
    p.add_argument("--daily", type=Path, default=None, help="Override config/inputs/daily.yaml")
    p.add_argument("--views-dir", type=Path, default=None, help="Override config/report_views/")
    args = p.parse_args()

    out = write_product_workbook(
        args.input,
        args.output,
        nr_percent_path=args.nr_percent,
        manual_context_path=args.manual_context,
        daily_inputs_path=args.daily,
        report_views_dir=args.views_dir,
    )
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
