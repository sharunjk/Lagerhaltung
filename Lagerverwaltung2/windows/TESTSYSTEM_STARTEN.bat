@echo off
cd /d "%~dp0\.."
title Lagerverwaltung TESTSYSTEM (Fenster offen lassen)
echo TESTSYSTEM der Lagerverwaltung - eigene Kopie der Daten, der Echtbetrieb bleibt unberuehrt.
echo Im Browser: http://localhost:8090   Anmelden mit denselben Benutzern wie im Echtbetrieb.
echo.
python\python.exe -m app.testsystem
pause
