@echo off
rem Optional: Start beim Hochfahren des PCs, auch ohne angemeldeten Benutzer. Rechtsklick -> "Als Administrator ausfuehren".
cd /d "%~dp0\.."
schtasks /Create /F /TN "Lagerverwaltung" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"%CD%\python\pythonw.exe\" -m app.main" /DELAY 0001:00
powershell -NoProfile -Command "$t = Get-ScheduledTask -TaskName 'Lagerverwaltung'; $t.Actions[0].WorkingDirectory = '%CD%'; $t.Settings.ExecutionTimeLimit = 'PT0S'; Set-ScheduledTask -InputObject $t | Out-Null"
call "%~dp0FIREWALL_FREIGEBEN_als_Admin.bat" nopause
schtasks /Run /TN "Lagerverwaltung"
echo Aufgabe "Lagerverwaltung" angelegt und gestartet.
pause
