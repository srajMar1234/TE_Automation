"""Playwright Chromium launch options for local Chrome and Snowflake/Linux runtimes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_TRUE = ("1", "true", "yes")

_CHROME_CANDIDATES = (
    "/opt/google/chrome/chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def running_in_snowflake() -> bool:
    if os.environ.get("SNOWFLAKE_ACCOUNT") or os.environ.get("SNOWFLAKE_HOST"):
        return True
    return Path("/usr/lib/python_udf").is_dir() or Path("/home/udf").is_dir()


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE


def _chrome_executable() -> str:
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return ""


def _needs_container_chrome_args() -> bool:
    if running_in_snowflake():
        return True
    if Path("/.dockerenv").exists():
        return True
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _container_launch_args() -> list[str]:
    if not _needs_container_chrome_args() and not _env_flag("PLAYWRIGHT_NO_SANDBOX"):
        return []
    return [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-setuid-sandbox",
    ]


def _bundled_chromium_path() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return p.chromium.executable_path or ""
    except Exception:
        return ""


def ensure_playwright_chromium() -> None:
    """Install Playwright's bundled Chromium when system Chrome is not available.

    Snowflake warehouse/Streamlit runtimes do not ship Google Chrome at
    ``/opt/google/chrome/chrome``. Browsers must live in a writable cache
    (``/tmp``) and may need an External Access Integration to download.
    """
    if running_in_snowflake():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/ms-playwright")

    if _chrome_executable():
        return

    bundled = _bundled_chromium_path()
    if bundled and Path(bundled).is_file():
        return

    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return

    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(
        "Playwright Chromium is not installed and could not be downloaded. "
        "Snowflake does not include Google Chrome at /opt/google/chrome/chrome, "
        "so unset PLAYWRIGHT_USE_INSTALLED_CHROME and either allow egress to "
        "download Chromium (External Access Integration) or deploy with the "
        "project Dockerfile / Streamlit container runtime.\n"
        f"{detail}"
    )


def chromium_launch_kwargs(*, pipeline_config: dict[str, Any], playwright: Any | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"headless": pipeline_config.get("headless", True)}
    extra_args = _container_launch_args()
    if extra_args:
        kwargs["args"] = extra_args
        kwargs["chromium_sandbox"] = False

    # channel="chrome" only works when Google Chrome is actually installed.
    # Snowflake Linux images do not have /opt/google/chrome/chrome.
    want_channel = _env_flag("PLAYWRIGHT_USE_INSTALLED_CHROME") and not running_in_snowflake()
    chrome = _chrome_executable()
    if want_channel and chrome:
        kwargs["channel"] = "chrome"
        return kwargs

    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if exe and Path(exe).is_file():
        kwargs["executable_path"] = exe
        return kwargs

    if chrome and not want_channel:
        bundled = ""
        if playwright is not None:
            bundled = getattr(playwright.chromium, "executable_path", "") or ""
        if not bundled or not Path(bundled).is_file():
            kwargs["executable_path"] = chrome
    return kwargs
