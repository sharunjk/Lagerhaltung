@echo off
cd /d "%~dp0\.."
title Lagerverwaltung (Fenster offen lassen)
echo Lagerverwaltung laeuft. Im Browser oeffnen: http://localhost:8080
echo Zum Beenden dieses Fenster schliessen.
start "" http://localhost:8080
python\python.exe -m app.main
pause
