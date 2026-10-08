@echo off
rem Erlaubt Handscannern, Smartphones und anderen PCs im Firmennetz den Zugriff. Rechtsklick -> "Als Administrator ausfuehren".
net session >nul 2>&1
if errorlevel 1 (
  echo FEHLER: Keine Administratorrechte.
  echo Bitte Rechtsklick auf diese Datei - "Als Administrator ausfuehren".
  if not "%1"=="nopause" pause
  exit /b 1
)
cd /d "%~dp0\.."
rem Ports aus config.toml. Standard: nur der verschluesselte Port 8443 - http (8080) ist nur am Lager-PC selbst erreichbar.
set "PORTS=8443"
if exist "python\python.exe" for /f "usebackq delims=" %%p in (`python\python.exe -c "from app.config import load_config;c=load_config().server;print(','.join(str(int(x)) for x in ((c.https_port,) if (c.http_nur_lokal and int(c.https_port)) else (c.port,c.https_port)) if int(x)))"`) do set "PORTS=%%p"
netsh advfirewall firewall delete rule name="Lagerverwaltung" >nul 2>&1
netsh advfirewall firewall add rule name="Lagerverwaltung" dir=in action=allow protocol=TCP localport=%PORTS% profile=domain,private
if errorlevel 1 (
  echo FEHLER: Firewall-Regel konnte nicht angelegt werden.
  if not "%1"=="nopause" pause
  exit /b 1
)
echo Firewall-Regel "Lagerverwaltung" fuer TCP-Port(s) %PORTS% angelegt (Netzwerkprofile Domaene und Privat).
if "%1"=="nopause" exit /b 0
pause
