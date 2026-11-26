@echo off
chcp 65001 >nul 2>&1
set "PS1=%~dp0stop.ps1"
powershell.exe -ExecutionPolicy Bypass -NoProfile -Command "chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '%PS1%'"
pause
