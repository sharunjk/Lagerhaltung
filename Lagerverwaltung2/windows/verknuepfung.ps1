# Legt Desktop- und Startmenue-Verknuepfung an (fuer den Lager-PC, auf dem die Software laeuft).
# Name = Programmname aus config.toml ([server] programmname, Einstellungen -> Allgemein), sonst "Lagerverwaltung".
$ordner = Split-Path -Parent $PSScriptRoot
$name = 'Lagerverwaltung'
$cfg = Join-Path $ordner 'config.toml'
if (Test-Path $cfg) {
  $abschnitt = ''
  foreach ($z in Get-Content $cfg -Encoding UTF8) {
    $t = $z.Trim()
    if ($t -match '^\[([^\]]+)\]') { $abschnitt = $matches[1].Trim().ToLower(); continue }
    if ($abschnitt -eq 'server' -and $t -match '^programmname\s*=\s*"(.*)"') { $name = $matches[1] }
  }
}
$name = ($name -replace '[\\/:*?"<>|]', '').Trim()
if (-not $name) { $name = 'Lagerverwaltung' }
$sh = New-Object -ComObject WScript.Shell
foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  if ($name -ne 'Lagerverwaltung') { Remove-Item (Join-Path $d 'Lagerverwaltung.lnk') -ErrorAction SilentlyContinue }
  $l = $sh.CreateShortcut((Join-Path $d ($name + '.lnk')))
  $l.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
  $l.Arguments = '"' + (Join-Path $ordner 'windows\Lagerverwaltung_oeffnen.vbs') + '"'
  $l.WorkingDirectory = $ordner
  $l.IconLocation = (Join-Path $ordner 'app\static\lager.ico')
  $l.Description = $name + ' oeffnen'
  $l.Save()
}
Write-Host ('Verknuepfung "' + $name + '" auf dem Desktop und im Startmenue angelegt.')
