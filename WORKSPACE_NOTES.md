# TE_Automation — quick reference

## Paths
- **Local project:** `/Users/anujbhardwaj/Downloads/TE_Automation`
- **GitHub:** https://github.com/AB1710-M/TE_Automation

## Setup (new machine)
```bash
git clone https://github.com/AB1710-M/TE_Automation.git
cd TE_Automation
python3 -m venv .venv-mac
./.venv-mac/bin/pip install -r requirements.txt
cp .env.example .env   # then fill credentials
```

## Run Streamlit (Report Studio)
```bash
cd TE_Automation
./.venv-mac/bin/streamlit run app/studio.py --server.port 8501
```
Open http://localhost:8501

## Run full CLI pipeline
```bash
python main.py
```

## What we changed (high level)
- **Studio (`app/studio.py`):** Step 0 = one button **Run export & build combined workbook** (browser export → merge to `combined_reports.xlsx` in a **session temp folder**, not `downloads/exports`). No separate unzip button; no manual Excel upload/path — combined file drives preview/build.
- **NR% / GC% / SD%:** Third column SD%; `config/inputs/nr_percent.yaml` has `sd_percent_by_group`; `apply_sd_percent` in `src/product/group_rollup.py`.
- **Custom pivot “Generate” bugfix:** Use `data_editor` **return values**, not `st.session_state[...]` (that holds edit metadata dicts).
- **`.gitignore`:** `.env`, `.venv/`, `.venv-mac/`, `downloads/`, `output/`, etc.

## Secrets
- **Never commit `.env`.** It stays local; use `.env.example` as a template.
