# TE Reporting Automation (Phase 1)

Phase-1 pipeline automates:
- 4 report exports from website `Reports` section with shared filters
- 1 report extraction from inline screenshot in email body
- normalization and consolidation of all 5 reports into one Excel workbook

## Project Structure

- `src/pipeline`: run orchestration, contracts, retry behavior
- `src/web`: login, filters, report export, download save
- `src/mail`: provider abstraction, inline image extraction, OCR
- `src/transform`: normalization and validations
- `src/output`: Excel compilation
- `config`: report and pipeline configs

## Setup

1. Create virtual environment and install dependencies:
   - `pip install -r requirements.txt`
   - `playwright install chromium` (optional if you use system Chrome; see below)
2. Copy `.env.example` to `.env` and fill values:
   - `REPORTS_USERNAME`
   - `REPORTS_PASSWORD`
   - `MAIL_PROVIDER` as `stub`, `graph`, or `imap`
   - If `playwright install chromium` fails with certificate errors, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to your installed Chrome, e.g. `C:\Program Files\Google\Chrome\Application\chrome.exe`
3. Update selectors and filter values in `config/reports.yaml`.

## Run

- Full pipeline: `python main.py`
- Web exports only (no mail): `python web_smoke_test.py`

Output workbook is created in `output/<run_id>/`.

## Mail Providers

- `stub`: local development fallback
- `graph`: placeholder implementation for Microsoft Graph
- `imap`: placeholder implementation for IMAP

The provider abstraction is ready; concrete authentication/query integration can be added next without changing pipeline orchestration.
