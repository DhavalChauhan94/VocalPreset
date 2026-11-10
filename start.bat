@echo off
rem One-command start on Windows (same job as start.sh). Double-click it, or run:
rem   start.bat            -> http://localhost:8080
rem   start.bat -Port 9000 -> another port
rem   start.bat -Lan       -> also reachable from a phone on the same Wi-Fi
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
