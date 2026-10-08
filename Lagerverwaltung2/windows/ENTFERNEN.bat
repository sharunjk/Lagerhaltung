@echo off
schtasks /Query /TN "Lagerverwaltung" >nul 2>&1
if not errorlevel 1 (
  net session >nul 2>&1
  if errorlevel 1 (
    echo HINWEIS: Die Lagerverwaltung ist als Aufgabe beim Hochfahren eingerichtet.
    echo Zum vollstaendigen Entfernen diese Datei mit Rechtsklick - "Als Administrator ausfuehren" starten.
    pause
    exit /b 1
  )
)
rem Beendet die Lagerverwaltung und entfernt Autostart, Dienst und Firewall-Regel. Danach kann der Ordner geloescht werden.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Lagerverwaltung.vbs" 2>nul
schtasks /End /TN "Lagerverwaltung" >nul 2>&1
schtasks /Delete /F /TN "Lagerverwaltung" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -like '*app.main*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
netsh advfirewall firewall delete rule name="Lagerverwaltung" >nul 2>&1
powershell -NoProfile -Command "foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))){ Remove-Item -ErrorAction SilentlyContinue (Join-Path $d 'Lagerverwaltung.lnk') }"
echo Lagerverwaltung beendet. Jetzt kann der Ordner %~dp0.. geloescht werden.
echo Vorher den Ordner "backups" (und ggf. "daten") sichern, wenn die Daten noch gebraucht werden.
pause
