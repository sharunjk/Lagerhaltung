@echo off
rem Beendet die Lagerverwaltung und entfernt den Benutzer-Autostart.
rem Ist sie als Dienst eingerichtet: Rechtsklick -> "Als Administrator ausfuehren".
cd /d "%~dp0\.."
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs" 2>nul
schtasks /End /TN "Lagerverwaltung" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*app.main*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
timeout /t 3 /nobreak >nul
rem Pruefen, ob sie wirklich beendet ist: antwortet sie noch auf ihrem Port? (Ohne Adminrechte sieht man die Prozesse des Dienstes nicht.)
set "PORT=8080"
if exist "python\python.exe" for /f "usebackq delims=" %%p in (`python\python.exe -c "from app.config import load_config;print(int(load_config().server.port))"`) do set "PORT=%%p"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 ('http://127.0.0.1:' + $env:PORT + '/m/ping') | Out-Null; exit 1 } catch { exit 0 }"
if errorlevel 1 (
  echo.
  echo FEHLER: Die Lagerverwaltung laeuft noch - vermutlich ist sie als Dienst eingerichtet.
  echo Bitte Rechtsklick auf diese Datei - "Als Administrator ausfuehren".
  echo Alternativ einfach den PC neu starten.
  echo.
  if not "%1"=="nopause" pause
  exit /b 1
)
echo Autostart entfernt und Lagerverwaltung beendet.
if not "%1"=="nopause" pause
