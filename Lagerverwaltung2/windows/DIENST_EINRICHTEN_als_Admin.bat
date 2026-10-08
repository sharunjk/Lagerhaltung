@echo off
rem Optional: Start beim Hochfahren des PCs, auch ohne angemeldeten Benutzer. Rechtsklick -> "Als Administrator ausfuehren".
rem Die Lagerverwaltung laeuft dabei unter dem eingeschraenkten Windows-Konto NETZWERKDIENST (nicht SYSTEM):
rem keine Administratorrechte, Schreibzugriff nur auf die Ordner daten, logs, backups, druckausgabe und auf config.toml.
net session >nul 2>&1
if errorlevel 1 (
  echo FEHLER: Keine Administratorrechte.
  echo Bitte Rechtsklick auf diese Datei - "Als Administrator ausfuehren".
  if not "%1"=="nopause" pause
  exit /b 1
)
cd /d "%~dp0\.."
if not exist "python\pythonw.exe" (
  echo FEHLER: Zuerst windows\1_EINRICHTEN.bat ausfuehren.
  pause
  exit /b 1
)
rem Laeuft die Lagerverwaltung schon ueber den Autostart des Benutzers, diesen entfernen (sonst zwei Instanzen)
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs" 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*app.main*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
rem Schluessel und Ordner vorab anlegen, dann Rechte fuer NETZWERKDIENST (SID S-1-5-20, unabhaengig von der Windows-Sprache)
python\python.exe -c "from app.config import load_config; load_config()"
if not exist "config.toml" copy /Y "config.example.toml" "config.toml" >nul
for %%d in (daten logs backups druckausgabe) do if not exist "%%d" mkdir "%%d"
icacls "%CD%" /grant *S-1-5-20:(OI)(CI)RX >nul
if errorlevel 1 (
  echo FEHLER: Rechte konnten nicht gesetzt werden.
  pause
  exit /b 1
)
for %%d in (daten logs backups druckausgabe) do icacls "%CD%\%%d" /grant *S-1-5-20:(OI)(CI)M >nul
icacls "%CD%\config.toml" /grant *S-1-5-20:M >nul
icacls "%CD%\.secret_key" /grant *S-1-5-20:R >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$a = New-ScheduledTaskAction -Execute '%CD%\python\pythonw.exe' -Argument '-m app.main' -WorkingDirectory '%CD%'; $t = New-ScheduledTaskTrigger -AtStartup; $t.Delay = 'PT1M'; $p = New-ScheduledTaskPrincipal -UserId 'S-1-5-20' -LogonType ServiceAccount -RunLevel Limited; $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Register-ScheduledTask -TaskName 'Lagerverwaltung' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null"
if errorlevel 1 (
  echo FEHLER: Aufgabe konnte nicht angelegt werden.
  pause
  exit /b 1
)
call "%~dp0FIREWALL_FREIGEBEN_als_Admin.bat" nopause
schtasks /Run /TN "Lagerverwaltung" >nul
echo Aufgabe "Lagerverwaltung" angelegt (Konto NETZWERKDIENST, Start beim Hochfahren) und gestartet.
pause
