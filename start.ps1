# Windows version of start.sh: creates the venv, installs deps, builds the web app, runs the server.
# Run it through start.bat (it bypasses PowerShell's script-blocking policy for this one script):
#   start.bat               -> http://localhost:8080
#   start.bat -Port 9000    -> another port
#   start.bat -Lan          -> also reachable from a phone on the same Wi-Fi (Windows Firewall asks once)
param(
  [int]$Port = $(if ($env:PORT) { [int]$env:PORT } else { 8080 }),
  [switch]$Lan
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Pick up tools installed after this window was opened (e.g. `winget install ffmpeg`).
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host 'ffmpeg missing: winget install ffmpeg'; exit 1 }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Host 'Node.js 20+ missing: https://nodejs.org'; exit 1 }

# Python lives in .venv\Scripts on Windows (start.sh uses .venv/bin).
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
  if ($LASTEXITCODE -ne 0) { Write-Host 'Could not create .venv: install Python 3.11+'; exit 1 }
}
& $py -c "import sys; sys.exit(sys.version_info < (3, 11))"
if ($LASTEXITCODE -ne 0) { Write-Host 'Python 3.11+ needed: delete .venv and install a newer Python'; exit 1 }
& $py -m pip install -q --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit 1 }

Push-Location web
try {
  # `npm ci` installs exactly what package-lock.json says and never rewrites it.
  if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { exit 1 } }
  npx vite build
  if ($LASTEXITCODE -ne 0) { exit 1 }
} finally { Pop-Location }

$bindHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }

# Key detection for auto-tune runs in WSL (key-service container). WSL stops idle distros, so hold one
# session open while the site runs. Without it, keys.py falls back to the built-in detector.
$keySvc = $null
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
  $keySvc = Start-Process wsl.exe -ArgumentList '-d', 'Ubuntu', '--', 'bash', '-lc', 'docker start keysvc >/dev/null 2>&1; exec sleep infinity' -WindowStyle Hidden -PassThru
}
Write-Host "VocalPreset -> http://localhost:$Port"
try {
  & $py -m uvicorn app:app --host $bindHost --port $Port
} finally {
  if ($keySvc -and -not $keySvc.HasExited) { Stop-Process -Id $keySvc.Id -ErrorAction SilentlyContinue }
}
