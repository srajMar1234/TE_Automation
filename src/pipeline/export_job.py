"""Export all configured All Orders reports via Playwright (no mail)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from src.web.launch import chromium_launch_kwargs
from src.web.login import build_authenticated_page
from src.web.reports import export_report


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def export_all_order_reports(
    base_dir: Path,
    *,
    download_dir: Path | None = None,
) -> Path:
    """
    Log in and export every report in ``config/reports.yaml``.
    Files go to ``download_dir`` or ``base_dir/downloads/exports``.
    Returns the download directory path.
    """
    load_dotenv(base_dir / ".env")
    cfg = _load_yaml(base_dir / "config" / "reports.yaml")
    pipe = _load_yaml(base_dir / "config" / "pipeline.yaml")

    username = os.environ["REPORTS_USERNAME"]
    password = os.environ["REPORTS_PASSWORD"]

    out_dir = download_dir or (base_dir / "downloads" / "exports")
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_kwargs(pipeline_config=pipe))
        context = browser.new_context(accept_downloads=True)
        page = build_authenticated_page(
            context,
            base_url=cfg["base_url"],
            username=username,
            password=password,
        )

        try:
            for report in cfg["reports"]:
                out_name = report.get("output_name", report["name"])
                out_path = out_dir / out_name
                print(f"Exporting: {out_name}")
                saved = export_report(
                    page,
                    reports_url=cfg["reports_url"],
                    report_name=report["name"],
                    base_filters=cfg.get("base_filters", {}),
                    report_filters=report.get("filters", {}),
                    output_path=out_path,
                )
                print(f"Saved: {saved}")
        except Exception as exc:
            if "TargetClosed" in type(exc).__name__ or "Target closed" in str(exc).lower():
                print(
                    "\nBrowser window was closed during the run. "
                    "Do not close Chrome while the script is working. "
                    "Or set headless: true in config/pipeline.yaml.\n"
                )
            raise
        finally:
            browser.close()

    return out_dir
