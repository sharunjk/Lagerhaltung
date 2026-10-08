@echo off
rem Optional: Start beim Hochfahren des PCs, auch ohne angemeldeten Benutzer. Rechtsklick -> "Als Administrator ausfuehren".
net session >nul 2>&1
if errorlevel 1 (
  echo FEHLER: Keine Administratorrechte.
  echo Bitte Rechtsklick auf diese Datei - "Als Administrator ausfuehren".
  if not "%1"=="nopause" pause
  exit /b 1
)
cd /d "%~dp0\.."
schtasks /Create /F /TN "Lagerverwaltung" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"%CD%\python\pythonw.exe\" -m app.main" /DELAY 0001:00
if errorlevel 1 ( echo FEHLER: Aufgabe konnte nicht angelegt werden. & pause & exit /b 1 )
powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName 'Lagerverwaltung'; $t.Actions[0].WorkingDirectory = '%CD%'; $t.Settings.ExecutionTimeLimit = 'PT0S'; Set-ScheduledTask -InputObject $t | Out-Null"
rem Laeuft die Lagerverwaltung schon ueber den Autostart des Benutzers, diesen entfernen (sonst zwei Instanzen)
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs" 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*app.main*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
call "%~dp0FIREWALL_FREIGEBEN_als_Admin.bat" nopause
schtasks /Run /TN "Lagerverwaltung"
echo Aufgabe "Lagerverwaltung" angelegt und gestartet.
pause
