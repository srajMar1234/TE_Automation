"""Playwright Chromium launch options (e.g. use system Chrome when Playwright browsers cannot download)."""

from __future__ import annotations

import os
from typing import Any


def chromium_launch_kwargs(*, pipeline_config: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"headless": pipeline_config.get("headless", True)}
    # Prefer channel="chrome" (installed Google Chrome) — more stable with Playwright than raw executable_path.
    if os.environ.get("PLAYWRIGHT_USE_INSTALLED_CHROME", "").strip().lower() in ("1", "true", "yes"):
        kwargs["channel"] = "chrome"
        return kwargs
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if exe:
        kwargs["executable_path"] = exe
    return kwargs
