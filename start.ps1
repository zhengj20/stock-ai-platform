# A-stock Analysis Platform - Dev mode startup (PowerShell)
# Dual services: Vite frontend(5173) + FastAPI backend(5174)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp.com 65001 > $null 2>&1
$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  A-stock Analysis Platform - Dev Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "[INFO] Project: $ROOT_DIR" -ForegroundColor Yellow

# Check dependencies
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found, install Python 3.11+" -ForegroundColor Red
    pause; exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Node.js not found, install Node.js 18+" -ForegroundColor Red
    pause; exit 1
}

# Cleanup old services
Write-Host "`n[Cleanup] Stopping old services..." -ForegroundColor Yellow
$stopScript = Join-Path $ROOT_DIR "stop.ps1"
if (Test-Path $stopScript) {
    powershell -ExecutionPolicy Bypass -NoProfile -Command "chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '$stopScript'"
} else {
    Get-Process -Name python,node,uvicorn -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }
    Start-Sleep -Seconds 2
}

# ===== Backend deps =====
$backendPath = Join-Path $ROOT_DIR "backend"
Set-Location -LiteralPath $backendPath

$venvScripts = Join-Path $backendPath ".venv\Scripts"
if (Test-Path $venvScripts) {
    & "$venvScripts\Activate.ps1"
} else {
    Write-Host "[INFO] Creating Python venv..." -ForegroundColor Yellow
    python -m venv .venv
    & "$venvScripts\Activate.ps1"
}

if (-not (Test-Path (Join-Path $backendPath ".venv\Scripts\uvicorn.exe"))) {
    Write-Host "[INFO] Installing backend deps..." -ForegroundColor Yellow
    pip install -r requirements.txt -q --upgrade
}

# ===== Start backend (port 5174, hot reload) =====
Write-Host "`n[Start] Backend service (port: 5174, hot reload)..." -ForegroundColor Green
$uvicornExe = Join-Path $backendPath ".venv\Scripts\uvicorn.exe"

$logsDir = Join-Path $ROOT_DIR "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$cmdArgs = "/k title Backend && `"$uvicornExe`" app.main:app --reload --host 0.0.0.0 --port 5174"
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WorkingDirectory $backendPath

# Wait for backend
Write-Host "[Wait] Backend starting..." -ForegroundColor Yellow
$backendReady = $false
for ($i = 1; $i -le 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5174/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $backendReady = $true
            break
        }
    } catch {}
    Write-Host "$($i)s.." -NoNewline
}

if ($backendReady) {
    Write-Host "`n[OK] Backend started (5174)" -ForegroundColor Green
} else {
    Write-Host "`n[WARN] Backend slow to start, please wait" -ForegroundColor Yellow
}

# ===== Start frontend (port 5173, HMR) =====
Write-Host "`n[Start] Frontend service (port: 5173, HMR)..." -ForegroundColor Green
$frontendPath = Join-Path $ROOT_DIR "frontend"

if (-not (Test-Path (Join-Path $frontendPath "node_modules"))) {
    Write-Host "[INFO] Installing Node deps..." -ForegroundColor Yellow
    Set-Location -LiteralPath $frontendPath
    npm install 2>&1 | Out-Null
}

Set-Location -LiteralPath $frontendPath
$cmdArgs = "/k title Frontend && npx vite --host"
Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WorkingDirectory $frontendPath

# Wait for frontend
Write-Host "[Wait] Frontend starting..." -ForegroundColor Yellow
$frontendReady = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {}
    Write-Host "$($i)s.." -NoNewline
}

if ($frontendReady) {
    Write-Host "`n[OK] Frontend started (5173)" -ForegroundColor Green
} else {
    Write-Host "`n[WARN] Frontend slow to start, please wait" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Dev mode started!" -ForegroundColor Cyan
Write-Host ""
Write-Host "  URL:  http://localhost:5173" -ForegroundColor Green
Write-Host "  API:  http://localhost:5174/docs" -ForegroundColor Green
Write-Host ""
Write-Host "  Hot reload enabled for both frontend & backend" -ForegroundColor Yellow
Write-Host "  For production use: start-prod.bat (single port)" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Stop:  stop.bat" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"
