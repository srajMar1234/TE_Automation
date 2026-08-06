from __future__ import annotations

import re
from pathlib import Path
from datetime import date
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from src.pipeline.download_io import path_for_export_save

# Reports UI: first "All Orders" row is <tr id="sales-report"> inside <table id="table-report">.
# The name cell text is "ALL ORDERS" in DOM (case differs from visible title case).


def _main_content(page: Page):
    """OpenCart admin puts the page body in #content; avoids matching sidebar/nav duplicates."""
    for sel in ("#content", "#app", "main"):
        loc = page.locator(sel).first
        if loc.count() > 0:
            return loc
    return page.locator("body")


def _all_orders_row(page: Page):
    """First row in #table-report whose report-name cell is exactly 'All Orders' (tr id may be sales-report or sales-report-…)."""
    table = page.locator("#table-report")
    if table.count() == 0:
        return page.locator("tr#sales-report").first
    row = page.locator("#table-report tbody tr").filter(
        has=page.locator("td", has_text=re.compile(r"^\s*all orders\s*$", re.I))
    ).first
    if row.count() > 0:
        return row
    for sel in ("tr#sales-report", "#table-report tr#sales-report"):
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc.first
    return page.locator("#table-report tbody tr").first


def _wait_all_orders_report_row_visible(page: Page) -> None:
    """Wait until the All Orders report row exists (table may load after navigation)."""
    try:
        page.locator("#table-report").first.wait_for(state="attached", timeout=20_000)
    except PlaywrightTimeoutError:
        pass
    _all_orders_row(page).wait_for(state="visible", timeout=60_000)


def apply_filters(page: Page, filters: dict[str, Any]) -> None:
    for selector, value in filters.items():
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        if isinstance(value, bool):
            state = locator.first.is_checked()
            if state != value:
                locator.first.click()
        elif selector.startswith("select") or isinstance(value, dict):
            if isinstance(value, dict):
                locator.first.select_option(**value)
            else:
                locator.first.select_option(label=str(value))
        else:
            locator.first.fill(str(value))


def _merge_admin_token(page: Page, target_url: str) -> str:
    """OpenCart admin links usually need the same `token` as the current session."""
    if "token=" in target_url:
        return target_url
    parsed = urlparse(page.url)
    token = (parse_qs(parsed.query).get("token") or [None])[0]
    if not token:
        return target_url
    base = urlparse(target_url)
    query = dict(parse_qsl(base.query, keep_blank_values=True))
    query["token"] = token
    new_query = urlencode(query)
    return urlunparse((base.scheme, base.netloc, base.path, base.params, new_query, base.fragment))


def _goto_reports_section(page: Page, reports_url: str) -> None:
    url = _merge_admin_token(page, reports_url)
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("load", timeout=30_000)
    except PlaywrightTimeoutError:
        pass

    if _all_orders_row(page).count() > 0:
        try:
            _all_orders_row(page).wait_for(state="visible", timeout=10_000)
            return
        except PlaywrightTimeoutError:
            pass

    report_link = page.locator('a[href*="route=report/report"]').first
    if report_link.count() > 0:
        report_link.click()
        page.wait_for_load_state("domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=30_000)
        except PlaywrightTimeoutError:
            pass

    if _all_orders_row(page).count() == 0:
        tile = page.get_by_role("link", name="Reports").first
        if tile.count() > 0:
            tile.click()
            page.wait_for_load_state("domcontentloaded")
            try:
                page.wait_for_load_state("load", timeout=30_000)
            except PlaywrightTimeoutError:
                pass

    if page.locator('a:has-text("Current Data Reports")').count() > 0:
        page.locator('a:has-text("Current Data Reports")').first.click()
        try:
            page.wait_for_load_state("load", timeout=30_000)
        except PlaywrightTimeoutError:
            pass

    _wait_all_orders_report_row_visible(page)


def _resolve_date_token(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    value = str(raw_value).strip().lower()
    today = date.today()
    if value == "as on date":
        return today.strftime("%Y-%m-%d")
    if value == "1st of month":
        return today.replace(day=1).strftime("%Y-%m-%d")
    if value == "1st of previous month":
        if today.month == 1:
            first_prev = today.replace(year=today.year - 1, month=12, day=1)
        else:
            first_prev = today.replace(month=today.month - 1, day=1)
        return first_prev.strftime("%Y-%m-%d")
    return str(raw_value)


def _deselect_all_native_multiselect(select_locator) -> None:
    """Clear a native <select multiple> (Select2 keeps a hidden select in sync)."""
    if select_locator.count() == 0:
        return
    select_locator.first.evaluate(
        """(el) => {
            for (const o of el.options) o.selected = false;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            const jq = window.jQuery || window.$;
            if (jq) {
                jq(el).trigger('change');
                if (jq(el).data('select2')) jq(el).trigger('change.select2');
            }
        }"""
    )


def _select_multiselect_labels(select_locator, labels: list[str]) -> None:
    """Set native <select multiple> options by text; syncs Select2 (label text often != Playwright label= match)."""
    if select_locator.count() == 0:
        raise ValueError(
            "No matching <select> found in the All Orders row. "
            "DevTools → find the Order Status <select> and share its name= / id; "
            "builds differ (e.g. filter_order_status[], filter_order_status_id[], order_status_id[])."
        )
    if not labels:
        _deselect_all_native_multiselect(select_locator)
        return
    # select_option() often fails with Select2 + slight label differences ("Ready to Ship" vs "Ready To Ship").
    select_locator.first.evaluate(
        """(el, labels) => {
            const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const wanted = labels.map(norm).filter(Boolean);
            for (const o of el.options) o.selected = false;
            for (const w of wanted) {
                let hit = null;
                for (const o of el.options) {
                    if (norm(o.textContent) === w) { hit = o; break; }
                }
                if (!hit) {
                    for (const o of el.options) {
                        const t = norm(o.textContent);
                        if (t.includes(w) || w.includes(t)) { hit = o; break; }
                    }
                }
                if (hit) hit.selected = true;
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
            const jq = window.jQuery || window.$;
            if (jq) {
                jq(el).trigger('change');
                if (jq(el).data('select2')) jq(el).trigger('change.select2');
            }
        }""",
        labels,
    )


def _first_select_matching(row, selectors: list[str]):
    """Return first locator that has a matching <select> in this row (Select2 keeps a hidden native select)."""
    for sel in selectors:
        loc = row.locator(sel)
        if loc.count() > 0:
            return loc
    return row.locator('select[name="__missing__"]')


def _customer_group_select(row):
    return _first_select_matching(
        row,
        [
            'select[name="filter_customer_group[]"]',
            'select[name="filter_customer_group_id[]"]',
            'select[name="customer_group[]"]',
            'select[name="customer_group_id[]"]',
            'select[multiple][name*="customer_group"]',
        ],
    )


def _order_status_select(row):
    return _first_select_matching(
        row,
        [
            'select[name="filter_order_status_id"]',
            'select[name="filter_order_status[]"]',
            'select[name="filter_order_status_id[]"]',
            'select[name="order_status[]"]',
            'select[name="order_status_id[]"]',
            'select#order_status_id',
            'select#filter_order_status_id',
            'select[multiple][name*="order_status"]',
        ],
    )


def _set_datepicker_value(locator, value: str) -> None:
    """jQuery UI date inputs are often readonly; .fill() cannot edit them. Set value in page JS."""
    locator.evaluate(
        """(el, value) => {
            const v = value === null || value === undefined ? '' : String(value);
            el.removeAttribute('readonly');
            el.value = v;
            for (const type of ['input', 'change', 'blur']) {
                el.dispatchEvent(new Event(type, { bubbles: true }));
            }
            const jq = window.jQuery || window.$;
            if (jq && typeof jq(el).datepicker === 'function') {
                try {
                    if (v) {
                        jq(el).datepicker('setDate', v);
                    } else {
                        jq(el).val('');
                        jq(el).datepicker('setDate', null);
                    }
                } catch (e) {
                    /* non-jQuery datepicker or API mismatch */
                }
            }
        }""",
        value,
    )


def _apply_all_orders_filters(page: Page, filters: dict[str, Any]) -> None:
    _wait_all_orders_report_row_visible(page)
    row = _all_orders_row(page)
    if row.count() == 0:
        raise ValueError("Could not locate 'All Orders' row in Reports table")

    date_status_raw = str(filters.get("date_status", "Date Added")).strip().lower()
    # <option> labels in DOM are title case: "Date Added", "Date Shipped" (not "date Added").
    date_status_label = "Date Shipped" if date_status_raw == "date shipped" else "Date Added"
    date_select = row.locator('select[name="filter_date_type"]')
    if date_select.count() == 0:
        date_select = row.locator("select").first
    date_select.select_option(label=date_status_label)

    date_start_input = row.locator('input[name="filter_date_start"]')
    date_end_input = row.locator('input[name="filter_date_end"]')

    # Clear date range + multiselects (avoid carry-over between report exports).
    _set_datepicker_value(date_start_input.first, "")
    _set_datepicker_value(date_end_input.first, "")
    _deselect_all_native_multiselect(_customer_group_select(row))
    _deselect_all_native_multiselect(_order_status_select(row))

    for field, value in filters.items():
        if field == "date_status":
            continue
        if field == "date_start":
            _set_datepicker_value(date_start_input.first, _resolve_date_token(value))
        elif field == "date_end":
            _set_datepicker_value(date_end_input.first, _resolve_date_token(value))
        elif field == "customer_group":
            raw = str(value).strip()
            cg = _customer_group_select(row)
            if not raw:
                _deselect_all_native_multiselect(cg)
            else:
                _select_multiselect_labels(cg, [raw])
        elif field == "order_status":
            if isinstance(value, list):
                values = [str(item).strip() for item in value if str(item).strip()]
            else:
                values = [part.strip() for part in str(value).split(",") if part.strip()]
            _select_multiselect_labels(_order_status_select(row), values)


def export_report(
    page: Page,
    *,
    reports_url: str,
    report_name: str,
    base_filters: dict[str, Any],
    report_filters: dict[str, Any],
    output_path: Path,
) -> Path:
    _goto_reports_section(page, reports_url)

    combined_filters = dict(base_filters)
    combined_filters.update(report_filters)
    _apply_all_orders_filters(page, combined_filters)
    # Let Select2 / datepicker finish updating the DOM before export (avoids partial/corrupt downloads).
    page.wait_for_timeout(800)

    row = _all_orders_row(page)
    export_button = row.locator('a:has-text("Export"), button:has-text("Export")').first
    if export_button.count() == 0:
        raise ValueError(f"Export button for All Orders not found while exporting {report_name}")

    with page.expect_download(timeout=120000) as download_info:
        export_button.click()
    download = download_info.value
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_path = path_for_export_save(output_path, download.suggested_filename)
    download.save_as(str(final_path))
    return final_path
