"""Export all four All Orders reports to downloads/exports (Playwright)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.pipeline.export_job import export_all_order_reports


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Export TE admin order reports (ZIP/CSV).")
    p.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help="Output folder (default: <project>/downloads/exports)",
    )
    args = p.parse_args()
    out = export_all_order_reports(root, download_dir=args.download_dir)
    print(f"Done. Files in {out}")


if __name__ == "__main__":
    main()
