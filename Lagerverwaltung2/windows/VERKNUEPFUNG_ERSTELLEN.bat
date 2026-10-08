@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verknuepfung.ps1"
if "%1"=="nopause" exit /b 0
pause
