"""Optional end-to-end export. Mail ingestion was removed; use manual YAML inputs instead."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.export_job import export_all_order_reports


def run_web_export_only(base_dir: Path) -> Path:
    """Export all configured reports to ``downloads/exports``."""
    return export_all_order_reports(base_dir)


# Back-compat name used by older scripts
run_pipeline = run_web_export_only
