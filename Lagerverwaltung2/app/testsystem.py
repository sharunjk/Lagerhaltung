"""Testsystem: eine zweite Lagerverwaltung auf demselben PC, mit einer Kopie der echten Daten.

Start: windows/TESTSYSTEM_STARTEN.bat (oder ``python -m app.testsystem``). Läuft unter http://localhost:8090 mit eigenem
Ordner ``testsystem`` (Datenbank, Einstellungen, Protokolle). Was dort gebucht, importiert oder gelöscht wird, berührt den
Echtbetrieb nicht. Gedacht zum Ausprobieren neuer Funktionen und zum Proben von Importen und Updates.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROGRAMM = Path(__file__).resolve().parent.parent
TEST = PROGRAMM / "testsystem"
PORT = 8090

KONFIG = f"""# Testsystem – nur auf diesem PC erreichbar, unabhängig vom Echtbetrieb
[server]
host = "127.0.0.1"
port = {PORT}
https_port = 0
firmenname = "TESTSYSTEM"

[backup]
aktiv = false

[mail]
aktiv = false

[cmms]
aktiv = true
"""


def kopieren(quelle: Path, ziel: Path) -> None:
    """Konsistente Kopie der laufenden Datenbank (SQLite-Backup, auch während im Echtbetrieb gebucht wird)."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    for rest in (ziel, ziel.with_name(ziel.name + "-wal"), ziel.with_name(ziel.name + "-shm")):
        rest.unlink(missing_ok=True)
    src, dst = sqlite3.connect(str(quelle), timeout=60), sqlite3.connect(str(ziel))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def vorbereiten(antwort: str | None = None) -> None:
    TEST.mkdir(exist_ok=True)
    konfig = TEST / "config.toml"
    if not konfig.exists():
        konfig.write_text(KONFIG, encoding="utf-8")
    echt = PROGRAMM / "daten" / "lager.db"
    test_db = TEST / "daten" / "lager.db"
    if not echt.exists():
        print("Keine Datenbank im Echtbetrieb gefunden – das Testsystem startet leer.")
        return
    if test_db.exists():
        if antwort is None:
            antwort = input("Testsystem neu aus dem Echtbetrieb kopieren? Bisherige Testdaten gehen verloren. [j/N] ").strip().lower()
        if antwort not in ("j", "ja", "y"):
            print("Weiter mit den bisherigen Testdaten.")
            return
    kopieren(echt, test_db)
    print(f"Daten aus dem Echtbetrieb kopiert ({echt.stat().st_size // 1024} KB). Fotos und Dokumente werden nicht kopiert.")


def main() -> None:
    vorbereiten()
    os.environ["LV_HOME"] = str(TEST)  # vor dem Import der App setzen: bestimmt Konfiguration, Daten und Protokolle
    os.environ.pop("LV_CONFIG", None)
    os.environ.pop("LV_DATENBANK", None)
    print(f"Testsystem läuft: http://localhost:{PORT}  (Echtbetrieb bleibt unberührt). Zum Beenden dieses Fenster schließen.")
    from .main import run
    run()


if __name__ == "__main__":
    sys.exit(main())
