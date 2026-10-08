@echo off
setlocal
cd /d "%~dp0\.."
echo ============================================================
echo  Lagerverwaltung - Einrichtung
echo ============================================================
echo.
if exist "python\python.exe" goto :python_ok
set "PYZIP="
for %%f in (python-3.12*-embed-amd64.zip) do set "PYZIP=%%f"
if "%PYZIP%"=="" (
  echo FEHLER: Python fehlt.
  echo Bitte "python-3.12.10-embed-amd64.zip" von python.org herunterladen
  echo ^(Windows embeddable package, 64-bit^) und ungeoeffnet in diesen Ordner legen:
  echo   %CD%
  echo Dann dieses Skript erneut starten.
  pause
  exit /b 1
)
echo Entpacke %PYZIP% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -Path '%PYZIP%' -DestinationPath 'python'"
if not exist "python\python.exe" ( echo FEHLER beim Entpacken. & pause & exit /b 1 )
:python_ok
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-ChildItem 'python\python3*._pth' | Select-Object -First 1; Set-Content -Encoding ASCII $p.FullName ('python312.zip','.','..\lib','..','import site')"
if not exist "config.toml" copy /Y "config.example.toml" "config.toml" >nul
if not exist "daten\anhaenge" mkdir "daten\anhaenge"
if not exist "backups" mkdir "backups"
echo Pruefe die Installation ...
python\python.exe -c "import app.main, cryptography; print('OK: Lagerverwaltung ist startbereit.')"
if errorlevel 1 ( echo FEHLER: siehe Meldung oben. & pause & exit /b 1 )
call "%~dp0VERKNUEPFUNG_ERSTELLEN.bat" nopause
echo.
echo Fertig. Die Lagerverwaltung jetzt ueber das Symbol "Lagerverwaltung" auf dem Desktop oeffnen.
echo Fuer Handscanner/Smartphones und andere PCs
echo bitte einmal "FIREWALL_FREIGEBEN_als_Admin.bat" (Rechtsklick - Als Administrator) ausfuehren.
pause
