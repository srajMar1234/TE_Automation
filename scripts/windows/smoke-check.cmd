@echo off
REM One-shot smoke check after Windows deploy.
setlocal
cd /d "%~dp0..\.."

echo === Python / venv ===
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -c "import streamlit,pandas,playwright,openpyxl,yaml,dotenv; print('deps OK')"
) else (
  echo ERROR: .venv missing. Create it first.
  exit /b 1
)

echo === Folders ===
if not exist "data\cutover_history" mkdir data\cutover_history
if not exist "logs" mkdir logs

echo === .env ===
if not exist ".env" (
  echo WARNING: .env missing — copy .env.example and set credentials.
) else (
  echo .env present
)

echo === PM2 ===
where pm2 >nul 2>&1
if errorlevel 1 (
  echo WARNING: pm2 not installed
) else (
  pm2 status
)

echo === Health (if studio is up) ===
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health).Content } catch { 'Studio not reachable on :8501 yet' }"

echo Done.
endlocal
