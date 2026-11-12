@echo off
rem Nach dem Entpacken eines Umzugspakets auf dem NEUEN PC: Rechtsklick -> "Als Administrator ausfuehren".
rem Richtet Desktop-Verknuepfung, Start beim Hochfahren (Konto NETZWERKDIENST) und Firewall-Freigabe ein und startet das Programm.
rem Daten, Einstellungen, Benutzer und Zertifikate kommen aus dem Paket - es wird nichts installiert oder heruntergeladen.
setlocal
net session >nul 2>&1
if errorlevel 1 (
  echo FEHLER: Keine Administratorrechte.
  echo Bitte Rechtsklick auf diese Datei - "Als Administrator ausfuehren".
  pause
  exit /b 1
)
cd /d "%~dp0\.."
echo ============================================================
echo  Umzug abschliessen
echo ============================================================
if not exist "python\python.exe" (
  echo FEHLER: Der Ordner python fehlt. Wurde das Umzugspaket vollstaendig entpackt?
  pause
  exit /b 1
)
if not exist "daten\lager.db" (
  echo FEHLER: daten\lager.db fehlt. Wurde das Umzugspaket vollstaendig entpackt?
  pause
  exit /b 1
)
echo Schritt 1/3: Pruefe das Programm ...
python\python.exe -c "import app.main, cryptography; print('OK: Programm ist startbereit.')"
if errorlevel 1 ( echo FEHLER: siehe Meldung oben. & pause & exit /b 1 )
echo Schritt 2/3: Desktop-Verknuepfung ...
call "%~dp0VERKNUEPFUNG_ERSTELLEN.bat" nopause
echo Schritt 3/3: Start beim Hochfahren und Firewall-Freigabe ...
call "%~dp0DIENST_EINRICHTEN_als_Admin.bat" nopause
if errorlevel 1 ( echo FEHLER beim Einrichten des Starts. & pause & exit /b 1 )
echo.
echo Fertig. Das Programm laeuft. Bitte jetzt ueber das Desktop-Symbol oeffnen und anmelden.
echo Dann: Einstellungen - Datensicherung pruefen ("Jetzt sichern") und ein Testetikett drucken.
echo Das Umzugspaket danach sicher loeschen (enthaelt alle Daten).
pause
