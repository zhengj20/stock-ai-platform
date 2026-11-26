# A股智能分析平台 - 生产环境一键启动 (PowerShell)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp.com 65001 > $null 2>&1
$ErrorActionPreference = "SilentlyContinue"

$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found, install Python 3.11+" -ForegroundColor Red
    pause; exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Node.js not found, install Node.js 18+" -ForegroundColor Red
    pause; exit 1
}

$hasUv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null

$envPath = "$ROOT_DIR\backend\.env"
if (-not (Test-Path $envPath)) {
    Write-Host "[ERROR] Missing backend\.env" -ForegroundColor Red
    Write-Host "  Create backend\.env with:"
    Write-Host "  SECRET_KEY=<random key>"
    pause; exit 1
}

Write-Host "[INFO] Project: $ROOT_DIR" -ForegroundColor Yellow

# --- stop old services ---
Write-Host "[CLEANUP] Stopping old services..." -ForegroundColor Yellow
$stopScript = Join-Path $ROOT_DIR "stop.ps1"
if (Test-Path $stopScript) {
    powershell -ExecutionPolicy Bypass -NoProfile -Command "chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '$stopScript'"
} else {
    Get-Process -Name python,node,uvicorn -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }
    Start-Sleep -Seconds 2
}

# --- [1/3] backend deps ---
Write-Host "--- [1/3] Installing backend ---" -ForegroundColor Green
$backendPath = Join-Path $ROOT_DIR "backend"
Set-Location -LiteralPath $backendPath

$venvPython = "$backendPath\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[INFO] Creating venv..." -ForegroundColor Yellow
    python -m venv .venv
}

if ($hasUv) {
    uv pip install -r requirements.txt -q
} else {
    & $venvPython -m pip install -r requirements.txt -q
}

# --- [2/3] frontend build ---
Write-Host "--- [2/3] Building frontend ---" -ForegroundColor Green
$frontendPath = Join-Path $ROOT_DIR "frontend"
Set-Location -LiteralPath $frontendPath

if (-not (Test-Path (Join-Path $frontendPath "node_modules"))) {
    npm install 2>&1 | Out-Null
}

npm run build --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Frontend build failed" -ForegroundColor Red
    pause; exit 1
}
if (-not (Test-Path (Join-Path $frontendPath "dist"))) {
    Write-Host "[ERROR] dist/ not found" -ForegroundColor Red
    pause; exit 1
}
Write-Host "[OK] Frontend built" -ForegroundColor Green

# --- [3/3] start backend ---
Write-Host "--- [3/3] Starting backend ---" -ForegroundColor Green
Set-Location -LiteralPath $backendPath

$logsDir = Join-Path $ROOT_DIR "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

# Windows 不支持 uvicorn 多进程 socket 继承，固定单 worker
Write-Host "[INFO] Starting backend on port 5173 (single worker, Windows)..." -ForegroundColor Yellow

# 后台启动 uvicorn（独立控制台窗口，关闭 BAT 不影响）
Start-Process -FilePath $venvPython `
    -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 5173" `
    -WorkingDirectory $backendPath

Write-Host "[WAIT] Waiting for service..." -ForegroundColor Yellow
$serviceReady = $false
for ($i = 1; $i -le 90; $i++) {
    Start-Sleep -Seconds 1
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("localhost", 5173)
        $tcp.Close()
        $serviceReady = $true
        break
    } catch {}
    if ($i % 10 -eq 0) { Write-Host "${i}s..." -NoNewline }
}

Write-Host ""
if (-not $serviceReady) {
    Write-Host "[WARN] Service slow to start, check logs: $errFile" -ForegroundColor Yellow
    Write-Host "  Manual: cd $backendPath ; python -m uvicorn app.main:app --host 0.0.0.0 --port 5173"
} else {
    Write-Host "[OK] Production environment started!" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Visit: http://localhost:5173"
Write-Host "  API:   http://localhost:5173/docs"
Write-Host "  Workers: $workers"

Write-Host "  Stop:   stop.ps1"
Write-Host "  Logs:   $logFile"
Write-Host "========================================" -ForegroundColor Cyan

if ($serviceReady) {
    Start-Sleep -Seconds 1
    Start-Process "http://localhost:5173/login"
}