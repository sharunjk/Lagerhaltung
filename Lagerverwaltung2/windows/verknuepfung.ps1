# Legt Desktop- und Startmenue-Verknuepfung "Lagerverwaltung" an (fuer den Lager-PC, auf dem die Software laeuft).
$ordner = Split-Path -Parent $PSScriptRoot
$sh = New-Object -ComObject WScript.Shell
foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  $l = $sh.CreateShortcut((Join-Path $d 'Lagerverwaltung.lnk'))
  $l.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
  $l.Arguments = '"' + (Join-Path $ordner 'windows\Lagerverwaltung_oeffnen.vbs') + '"'
  $l.WorkingDirectory = $ordner
  $l.IconLocation = (Join-Path $ordner 'app\static\lager.ico')
  $l.Description = 'Lagerverwaltung oeffnen'
  $l.Save()
}
Write-Host 'Verknuepfung "Lagerverwaltung" auf dem Desktop und im Startmenue angelegt.'
