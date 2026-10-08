@echo off
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs" 2>nul
schtasks /End /TN "Lagerverwaltung" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*app.main*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
echo Autostart entfernt und Lagerverwaltung beendet.
pause
