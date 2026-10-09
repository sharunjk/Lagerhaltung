"""Pakete der Lagerverwaltung bauen.

    python3 werkzeuge/pakete.py voll   <version>                     -> ausgabe/Lagerverwaltung_v<version>.zip
    python3 werkzeuge/pakete.py update <basis-commit> <alt> <neu>   -> ausgabe/Lagerverwaltung_Update_<alt>_auf_<neu>.zip

Inhalt immer aus dem letzten Commit (HEAD), nie aus ungespeicherten Änderungen. Das vollständige Paket enthält alle
Dateien unter Lagerverwaltung2/ aus Git plus den Ordner lib/ (Python-Pakete, nicht in Git). Das Update-Paket enthält
nur die seit <basis-commit> geänderten oder neuen Dateien – nie daten/, backups/, logs/, python/, lib/, config.toml
oder .secret_key – und eine UPDATE_LIESMICH.txt. Hinweise zur Version stehen in werkzeuge/update_hinweise/<neu>.txt.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
APP = "Lagerverwaltung2"
AUSGABE = WURZEL / "ausgabe"
NIE = ("lib/", "daten/", "backups/", "logs/", "python/", "druckausgabe/", "config.toml", ".secret_key")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=WURZEL, check=True, capture_output=True, text=True).stdout


def inhalt(pfad: str) -> bytes:
    return subprocess.run(["git", "show", f"HEAD:{pfad}"], cwd=WURZEL, check=True, capture_output=True).stdout


def pruefen_sauber() -> None:
    if git("status", "--porcelain", "--", APP).strip():
        sys.exit(f"Ungespeicherte Änderungen unter {APP}/ – erst committen.")


def voll(version: str) -> Path:
    pruefen_sauber()
    ziel = AUSGABE / f"Lagerverwaltung_v{version}.zip"
    dateien = git("ls-tree", "-r", "--name-only", "HEAD", APP).split()
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
        z.writestr(f"{APP}/", "")
        for d in dateien:
            z.writestr(d, inhalt(d))
        lib = WURZEL / APP / "lib"
        for f in sorted(lib.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(WURZEL).as_posix())
    return ziel


def update(basis: str, alt: str, neu: str) -> Path:
    pruefen_sauber()
    geaendert, geloescht = [], []
    for zeile in git("diff", "--name-status", "--no-renames", basis, "HEAD", "--", APP).splitlines():
        art, pfad = zeile.split("\t", 1)
        rel = pfad[len(APP) + 1:]
        if rel.startswith(NIE) or rel in NIE:
            sys.exit(f"{rel} gehört nie in ein Update-Paket.")
        (geloescht if art == "D" else geaendert).append(pfad)
    ziel = AUSGABE / f"Lagerverwaltung_Update_{alt}_auf_{neu}.zip"
    h = WURZEL / "werkzeuge" / "update_hinweise" / f"{neu}.txt"
    hinweise = h.read_text(encoding="utf-8").strip().replace("\r\n", "\n").replace("\n", "\r\n") if h.exists() else ""
    liste = "\r\n".join(f"  {p[len(APP) + 1:]}" for p in geaendert)
    weg = "\r\n".join(f"  {p[len(APP) + 1:]}" for p in geloescht)
    liesmich = (f"Lagerverwaltung - Update {alt} auf {neu} ({date.today():%d.%m.%Y})\r\n"
                f"=============================================================\r\n\r\n"
                f"Nur fuer eine eingerichtete Lagerverwaltung {alt}. Fuer eine neue Installation das vollstaendige\r\n"
                f"Paket Lagerverwaltung_v{neu}.zip verwenden.\r\n\r\n"
                f"Dieses Paket enthaelt nur geaenderte Programmdateien. Daten, Einstellungen (config.toml),\r\n"
                f"Benutzer, Sicherungen und Zertifikate bleiben unveraendert.\r\n\r\n"
                f"So geht's:\r\n"
                f"1. Lagerverwaltung beenden: windows\\4_AUTOSTART_AUS.bat\r\n"
                f"   (laeuft sie als Dienst: Rechtsklick -> Als Administrator ausfuehren).\r\n"
                f"   Das Programmfenster zu schliessen genuegt NICHT.\r\n"
                f"2. Zur Sicherheit: in der Lagerverwaltung vorher \"Speichern und jetzt sichern\"\r\n"
                f"   oder den Ordner daten an eine andere Stelle kopieren.\r\n"
                f"3. Den Ordner Lagerverwaltung2 in diesem Paket oeffnen, alles markieren (Strg+A)\r\n"
                f"   und in den Programmordner (z. B. C:\\Lagerverwaltung2) ziehen -> \"Dateien im Ziel ersetzen\".\r\n"
                + (f"4. Diese Dateien im Programmordner loeschen (gibt es nicht mehr):\r\n{weg}\r\n" if geloescht else "")
                + f"{5 if geloescht else 4}. Wieder starten: Dienst -> PC neu starten oder als Administrator\r\n"
                f"   schtasks /Run /TN Lagerverwaltung ; sonst windows\\3_AUTOSTART_EIN.bat und Symbol Lagerverwaltung.\r\n"
                f"   Unten in der Seitenleiste steht danach \"Version {neu}\".\r\n\r\n"
                + (f"Was ist neu / was ist zu tun:\r\n{hinweise}\r\n\r\n" if hinweise else "")
                + f"Geaenderte bzw. neue Dateien ({len(geaendert)}):\r\n{liste}\r\n")
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("UPDATE_LIESMICH.txt", liesmich.encode("cp1252"))
        for p in geaendert:
            z.writestr(p, inhalt(p))
    return ziel


if __name__ == "__main__":
    AUSGABE.mkdir(exist_ok=True)
    if len(sys.argv) == 3 and sys.argv[1] == "voll":
        print(voll(sys.argv[2]))
    elif len(sys.argv) == 5 and sys.argv[1] == "update":
        print(update(*sys.argv[2:]))
    else:
        sys.exit(__doc__)
