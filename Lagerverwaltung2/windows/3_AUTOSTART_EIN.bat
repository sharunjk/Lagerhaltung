@echo off
rem Startet die Lagerverwaltung unsichtbar bei jeder Anmeldung dieses Windows-Benutzers (keine Adminrechte noetig).
cd /d "%~dp0\.."
set "ZIEL=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs"
> "%ZIEL%" echo Set sh = CreateObject("WScript.Shell")
>> "%ZIEL%" echo sh.CurrentDirectory = "%CD%"
>> "%ZIEL%" echo sh.Run """%CD%\python\pythonw.exe"" -m app.main", 0, False
echo Autostart eingerichtet.
wscript "%ZIEL%"
timeout /t 4 >nul
start "" http://localhost:8080
pause
