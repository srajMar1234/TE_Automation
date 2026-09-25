@echo off
REM Start / resurrect TE Report Studio via PM2 (Windows).
setlocal
cd /d "%~dp0..\.."

if not exist "logs" mkdir logs
if not exist "data\cutover_history" mkdir data\cutover_history
if not exist "downloads\exports" mkdir downloads\exports
if not exist "output" mkdir output

where pm2 >nul 2>&1
if errorlevel 1 (
  echo ERROR: pm2 not found. Install Node.js then: npm install -g pm2
  exit /b 1
)

REM Prefer resurrecting a previously saved process list (survives reboot when this script is scheduled).
pm2 ping >nul 2>&1
if errorlevel 1 (
  echo PM2 daemon not running — starting ecosystem...
  pm2 start ecosystem.config.cjs
) else (
  pm2 describe te-report-studio >nul 2>&1
  if errorlevel 1 (
    echo Process missing — starting ecosystem...
    pm2 start ecosystem.config.cjs
  ) else (
    echo Resurrecting / ensuring te-report-studio is online...
    pm2 resurrect
    pm2 start te-report-studio --update-env >nul 2>&1
  )
)

pm2 save
pm2 status
endlocal
