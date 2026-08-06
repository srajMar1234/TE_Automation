from pathlib import Path

from playwright.sync_api import Download, Page


def wait_and_save_download(page: Page, *, target_path: Path, timeout_ms: int = 120000) -> Path:
    with page.expect_download(timeout=timeout_ms) as download_info:
        page.click('button:has-text("Export")')
    download: Download = download_info.value
    target_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(target_path))
    return target_path
