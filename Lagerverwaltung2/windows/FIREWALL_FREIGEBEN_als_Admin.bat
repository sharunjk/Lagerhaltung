@echo off
rem Erlaubt Handscannern, Smartphones und anderen PCs im Firmennetz den Zugriff. Rechtsklick -> "Als Administrator ausfuehren".
netsh advfirewall firewall delete rule name="Lagerverwaltung" >nul 2>&1
netsh advfirewall firewall add rule name="Lagerverwaltung" dir=in action=allow protocol=TCP localport=8080,8443 profile=domain,private
if "%1"=="nopause" exit /b 0
pause
