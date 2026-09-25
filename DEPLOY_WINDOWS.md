# Deploy TE Report Studio on a private Windows VM (PM2)

This guide deploys the **Streamlit Report Studio** (`app/studio.py`) with **PM2**, including **automatic restart after VM reboot**.

## What you are deploying

| Piece | Role |
|--------|------|
| Streamlit UI | Daily operator app (export → cutover → combined workbook → Excel build) |
| Playwright + Chrome | Headless browser login/export from admin reports |
| PM2 | Keeps Streamlit running, restarts on crash |
| Windows Scheduled Task | Restarts PM2 after reboot |

Default URL: `http://<VM-IP>:8501`

---

## Prerequisites on the VM

1. **Windows Server / Windows 10/11** (private VM), with outbound HTTPS to the admin reports site.
2. **Administrator** account for install steps.
3. Install:
   - [Python 3.11+](https://www.python.org/downloads/windows/) — check **Add python.exe to PATH**
   - [Node.js LTS](https://nodejs.org/) (includes npm; needed for PM2)
   - [Google Chrome](https://www.google.com/chrome/) (recommended for Playwright on Windows)
4. Open **firewall** inbound TCP **8501** (private network only).

---

## Step-by-step deploy

### 1) Copy the project onto the VM

Example paths — pick one:

```text
C:\apps\TE_Automation
```

Options:

- `git clone <your-private-repo-url> C:\apps\TE_Automation`
- Or copy a ZIP / shared folder and extract there

Open **Command Prompt** or **PowerShell** as Administrator:

```bat
cd C:\apps\TE_Automation
```

### 2) Create Python venv and install dependencies

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

If `playwright install chromium` fails (corporate SSL), skip it and use installed Chrome (next step).

### 3) Configure secrets and Chrome

```bat
copy .env.example .env
notepad .env
```

Set at least:

```env
REPORTS_USERNAME=your_real_username
REPORTS_PASSWORD=your_real_password
PLAYWRIGHT_USE_INSTALLED_CHROME=1
```

Optional if needed:

```env
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
```

Confirm `config\pipeline.yaml` has:

```yaml
headless: true
```

### 4) Create runtime folders

```bat
mkdir logs
mkdir data\cutover_history
mkdir downloads\exports
mkdir output
```

**Cutover note:** The first successful daily run only *seeds* QPQA history. A cutover Excel file appears from the **second** day onward (needs yesterday’s QPQA snapshot under `data\cutover_history`).

### 5) Quick smoke test (before PM2)

```bat
.venv\Scripts\python.exe -m streamlit run app\studio.py --server.port 8501 --server.address 0.0.0.0
```

Open on the VM: `http://127.0.0.1:8501`  
From your laptop (same private network): `http://<VM-IP>:8501`

Stop with `Ctrl+C` once the UI loads.

Optional CLI checks:

```bat
scripts\windows\smoke-check.cmd
```

### 6) Install PM2 and start the app

```bat
npm install -g pm2
cd C:\apps\TE_Automation
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs te-report-studio --lines 50
pm2 save
```

Useful commands:

```bat
pm2 restart te-report-studio
pm2 stop te-report-studio
pm2 delete te-report-studio
pm2 save
```

### 7) Auto-start after VM reboot (required)

PM2 alone does **not** reliably come back on Windows reboot. Register a Scheduled Task:

```powershell
cd C:\apps\TE_Automation
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-autostart.ps1
```

This:

1. Ensures PM2 has `te-report-studio` registered and runs `pm2 save`
2. Creates task **`TE-Report-Studio-PM2`** that runs `scripts\windows\pm2-start.cmd` **at startup**

Verify:

```powershell
Get-ScheduledTask -TaskName "TE-Report-Studio-PM2"
schtasks /Run /TN "TE-Report-Studio-PM2"
pm2 status
```

### 8) Reboot test (do this once)

1. `pm2 status` — confirm `online`
2. Restart the VM
3. After boot, wait ~30–60 seconds
4. `pm2 status` — should show `te-report-studio` **online**
5. Open `http://<VM-IP>:8501`

### 9) Daily use

1. Open the Studio URL
2. Click **Run export & build combined workbook** (Step 0)
3. Continue NR% / exclusions / Build Excel as usual
4. Download combined / cutover / product workbooks from the UI

---

## Firewall (Windows)

Allow inbound port 8501 on the private network:

```powershell
New-NetFirewallRule -DisplayName "TE Report Studio 8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow -Profile Private
```

Restrict to your office/VPN subnet if possible (do not expose 8501 to the public internet).

---

## Updating the app later

```bat
cd C:\apps\TE_Automation
git pull
.venv\Scripts\activate
pip install -r requirements.txt
pm2 restart te-report-studio
pm2 save
```

---

## Uninstall autostart

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\uninstall-autostart.ps1
pm2 delete te-report-studio
pm2 save --force
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `pm2` not found | Re-open terminal after Node install; or reinstall Node LTS |
| Studio URL blank / refused | `pm2 logs te-report-studio`; check firewall 8501 |
| Export fails / browser errors | Install Chrome; set `PLAYWRIGHT_USE_INSTALLED_CHROME=1`; keep `headless: true` |
| Cutover status “seeded” / no Excel | Normal on first day; need prior `QPQA_YYYY-MM-DD` in `data\cutover_history` |
| Unmapped customer groups | Add mappings in `config\customer_group_mapping.yaml`, then re-run |
| After reboot PM2 empty | Re-run `install-autostart.ps1`; confirm task exists; run `pm2 save` after any process change |
| Wrong Python used by PM2 | Set `TE_PYTHON=C:\apps\TE_Automation\.venv\Scripts\python.exe` then `pm2 restart te-report-studio --update-env` |

---

## Files added for PM2 / Windows

| Path | Purpose |
|------|---------|
| `ecosystem.config.cjs` | PM2 app definition (Streamlit on `:8501`) |
| `.streamlit/config.toml` | Bind `0.0.0.0`, headless, no usage stats |
| `scripts/windows/pm2-start.cmd` | Start/resurrect after boot |
| `scripts/windows/install-autostart.ps1` | Register reboot Scheduled Task |
| `scripts/windows/uninstall-autostart.ps1` | Remove that task |
| `scripts/windows/smoke-check.cmd` | Quick post-deploy check |
