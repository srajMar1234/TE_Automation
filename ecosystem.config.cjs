/**
 * PM2 process file for TE Report Studio (Streamlit).
 *
 * Usage (from project root):
 *   pm2 start ecosystem.config.cjs
 *   pm2 save
 *
 * Windows VM reboot persistence: see scripts/windows/install-autostart.ps1
 * and DEPLOY_WINDOWS.md
 */
const path = require("path");
const fs = require("fs");

const root = __dirname;
const isWin = process.platform === "win32";

function resolvePython() {
  const fromEnv = process.env.TE_PYTHON;
  if (fromEnv && fs.existsSync(fromEnv)) {
    return fromEnv;
  }
  const candidates = isWin
    ? [
        path.join(root, ".venv", "Scripts", "python.exe"),
        path.join(root, ".venv-win", "Scripts", "python.exe"),
      ]
    : [
        path.join(root, ".venv", "bin", "python"),
        path.join(root, ".venv-mac", "bin", "python"),
      ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return p;
    }
  }
  // Fall back to PATH python (less ideal on VMs).
  return isWin ? "python" : "python3";
}

const python = resolvePython();
const port = process.env.TE_PORT || "8501";

module.exports = {
  apps: [
    {
      name: "te-report-studio",
      cwd: root,
      script: python,
      args: [
        "-m",
        "streamlit",
        "run",
        "app/studio.py",
        "--server.port",
        String(port),
        "--server.address",
        "0.0.0.0",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
      ].join(" "),
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_restarts: 20,
      min_uptime: "10s",
      max_memory_restart: "1500M",
      kill_timeout: 10000,
      env: {
        PYTHONUNBUFFERED: "1",
        // Prefer installed Google Chrome on Windows VMs (see .env.example).
        PLAYWRIGHT_USE_INSTALLED_CHROME: process.env.PLAYWRIGHT_USE_INSTALLED_CHROME || "1",
      },
      error_file: path.join(root, "logs", "pm2-error.log"),
      out_file: path.join(root, "logs", "pm2-out.log"),
      merge_logs: true,
      time: true,
    },
  ],
};
