# A-stock Analysis Platform - Stop Services
# Dev mode: frontend(5173) + backend(5174)
# Prod mode: single service(5173)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp.com 65001 > $null 2>&1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stopping services..." -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan

$stopped = $false

foreach ($port in @(5173, 5174)) {
    Write-Host "`n[Check] Port $port ..." -ForegroundColor Yellow

    $netStat = netstat -ano | Select-String ":$port\b.*LISTENING"
    if ($netStat) {
        $pidMatches = [regex]::Matches($netStat.Line, '\s+(\d+)\s*$')
        foreach ($m in $pidMatches) {
            $processId = $m.Groups[1].Value
            try {
                Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" | ForEach-Object {
                    Write-Host "    [Stop] Child PID=$($_.ProcessId), Name=$($_.Name)" -ForegroundColor DarkGray
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }

                $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "  [Stop] PID=$processId, Name=$($proc.ProcessName)" -ForegroundColor Gray
                    Stop-Process -Id $processId -Force
                    $stopped = $true
                }
            } catch {
                Write-Host "  [Skip] PID=$processId (already exited or no permission)" -ForegroundColor DarkGray
            }
        }
    } else {
        Write-Host "  [OK] Port $port is free" -ForegroundColor Green
    }
}

Start-Sleep -Seconds 1

# Second pass: kill remaining processes
foreach ($port in @(5173, 5174)) {
    $stillUp = netstat -ano | Select-String ":$port\b.*LISTENING"
    if ($stillUp) {
        Write-Host "`n[Cleanup] Port $port still in use, retrying..." -ForegroundColor Yellow
        $pidMatches2 = [regex]::Matches($stillUp.Line, '\s+(\d+)\s*$')
        foreach ($m in $pidMatches2) {
            $processId = $m.Groups[1].Value
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Host "  [Force stop] PID=$processId" -ForegroundColor Gray
        }
    }
}

Start-Sleep -Seconds 1

# Verify
$stillRunning = $false
foreach ($port in @(5173, 5174)) {
    if (netstat -ano | Select-String ":$port\b.*LISTENING") {
        Write-Host "`n[WARN] Port $port still in use, may need admin rights" -ForegroundColor Red
        $stillRunning = $true
    }
}

if (-not $stillRunning) {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  All services stopped." -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
} else {
    Write-Host "`n[HINT] Run stop.bat as Administrator to force kill" -ForegroundColor Yellow
}
