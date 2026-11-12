"""Umzugspaket (ab 2.10.0): das ganze System in einer ZIP-Datei – auf dem neuen PC entpacken, Skript ausführen, fertig.

Inhalt: Programm (mit Python und Bibliotheken), eine stimmige Kopie der Datenbank (auch während gebucht wird),
Fotos/Dokumente, config.toml, Sitzungsschlüssel, Zertifikate (Handscanner müssen nichts neu installieren),
auf Wunsch die vorhandenen Sicherungen. Nicht enthalten: Protokolle, Druckausgabe, Testsystem.

Ablauf: Erst wird das alte System auf „nur lesen“ gesetzt (sonst fehlten spätere Buchungen auf dem neuen PC),
dann kopiert und gepackt. Die Sperre steht nicht im Paket. Schlägt das Packen fehl, wird sie wieder aufgehoben.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import tempfile
import threading
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config as cfgmod
from . import sicherung
from .betrieb import get_setting, set_setting

SETTING = "umzug.sperre"
PROGRAMM = Path(__file__).resolve().parent.parent.parent  # Ordner mit app/, python/, lib/, windows/, docs/
NIE_OBEN = {"daten", "logs", "backups", "druckausgabe", "testsystem"}  # oberste Ebene: kommen nicht (oder gesondert) ins Paket
NIE_ORDNER = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", "node_modules"}
NIE_DATEIEN = {"config.toml", ".secret_key", sicherung.UPLOAD}
_laeuft = threading.Lock()


class UmzugFehler(Exception):
    pass


def sperre_lesen(con) -> dict | None:
    wert = get_setting(con, SETTING)
    try:
        return json.loads(wert) if wert else None
    except ValueError:
        return None


def sperre_setzen(eng, info: dict | None) -> None:
    from ..db import settings
    with eng.execution_options(schreiben=True).begin() as con:
        if info is None:
            con.execute(settings.delete().where(settings.c.schluessel == SETTING))
        else:
            set_setting(con, SETTING, json.dumps(info, ensure_ascii=False))


def _ordnername() -> str:
    return cfgmod.BASE_DIR.resolve().name or "Lagerverwaltung2"


def _programmdateien(ausser: set[Path]):
    """(Pfad, Name im Paket) aller Programmdateien – ohne Daten, Protokolle, Caches und das entstehende Paket selbst."""
    for wurzel, ordner, dateien in os.walk(PROGRAMM):
        rel = Path(wurzel).relative_to(PROGRAMM)
        ordner[:] = sorted(o for o in ordner if o not in NIE_ORDNER and not (rel == Path(".") and o in NIE_OBEN))
        for d in sorted(dateien):
            p = Path(wurzel) / d
            if d.endswith((".pyc", ".teil")) or p.resolve() in ausser:
                continue
            if rel == Path(".") and (d in NIE_DATEIEN or (d.lower().endswith(".zip") and d.startswith(("Umzugspaket_", "Lagerverwaltung_")))):
                continue
            yield p, (rel / d).as_posix()


def _datendateien(cfg, db_datei: Path, ausser: set[Path]):
    """Alles unter daten/ (Zertifikate, Fotos/Dokumente …) außer der Datenbankdatei, die als stimmige Kopie dazukommt."""
    daten = cfgmod.BASE_DIR / "daten"
    db_namen = {db_datei.name, db_datei.name + "-wal", db_datei.name + "-shm", db_datei.name + "-journal"}
    gesehen = set()
    if daten.is_dir():
        for wurzel, ordner, dateien in os.walk(daten):
            ordner[:] = sorted(o for o in ordner if o not in NIE_ORDNER)
            for d in sorted(dateien):
                p = Path(wurzel) / d
                if (Path(wurzel) == daten and d in db_namen) or d.endswith(".teil") or d.startswith(".lager_schreibtest") or p.resolve() in ausser:
                    continue
                gesehen.add(p.resolve())
                yield p, "daten/" + p.relative_to(daten).as_posix()
    anh = cfg.path(cfg.daten.anhaenge)
    if anh.is_dir():  # Anhänge außerhalb von daten/ (anders eingestellt): unter daten/anhaenge ins Paket
        for f in sorted(anh.rglob("*")):
            if f.is_file() and f.resolve() not in gesehen:
                yield f, "daten/anhaenge/" + f.relative_to(anh).as_posix()


def _config_text(cfg) -> str:
    """config.toml fürs Paket: die laufenden Einstellungen (wie sie gerade gelten) auf Basis der vorhandenen Datei;
    Datenbank und Anhänge an den Standardorten (so liegen sie im Paket). Der Sitzungsschlüssel bleibt in .secret_key."""
    from dataclasses import asdict
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.toml"
        if cfgmod.CONFIG_PATH.exists():
            text = cfgmod.CONFIG_PATH.read_text(encoding="utf-8")
            tomllib.loads(text)  # muss lesbar sein
            p.write_text(text, encoding="utf-8")
        for abschnitt in cfgmod.SECTIONS:
            werte = asdict(getattr(cfg, abschnitt))
            if abschnitt == "server":
                werte.pop("secret_key", None)
            cfgmod.save_section(abschnitt, werte, path=p)
        cfgmod.save_section("daten", {"datenbank": "daten/lager.db", "anhaenge": "daten/anhaenge"}, path=p)
        return p.read_text(encoding="utf-8")


def _liesmich(cfg, info: dict, oben: str) -> str:
    from ..main import VERSION
    from .zertifikat import lokale_adressen
    ips = ", ".join(a for a in lokale_adressen() if a != "127.0.0.1") or "unbekannt"
    name = cfg.server.programmname
    zeilen = [
        f"UMZUGSPAKET {name} {cfg.server.firmenname}",
        f"Erstellt am {datetime.fromisoformat(info['am']):%d.%m.%Y %H:%M} von {info['von']} auf PC {socket.gethostname()} (IP {ips}), Version {VERSION}.",
        "",
        "VERTRAULICH: Enthaelt alle Daten einschliesslich Passwort-Hashes und Zertifikatsschluessel.",
        "Sicher aufbewahren und nach dem Umzug loeschen.",
        "",
        "Auf dem neuen PC:",
        "1. Den alten PC ausschalten bzw. dort die Software beenden. Das alte System steht seit dem Erstellen",
        "   dieses Pakets auf \"nur lesen\" - es fehlt also keine Buchung.",
        "2. Diese ZIP-Datei auf den neuen PC kopieren. Rechtsklick -> \"Alle extrahieren...\" -> Ziel: C:\\",
        f"   Es entsteht der Ordner C:\\{oben}. (Gibt es den Ordner schon, vorher umbenennen.)",
        f"3. Rechtsklick auf C:\\{oben}\\windows\\UMZUG_ABSCHLIESSEN_als_Admin.bat -> \"Als Administrator ausfuehren\".",
        "   Richtet Desktop-Verknuepfung, Start beim Hochfahren und Firewall-Freigabe ein und startet das Programm.",
        f"4. Desktop-Symbol \"{name}\" oeffnen und wie gewohnt anmelden (gleiche Benutzer und Passwoerter).",
        "5. Einstellungen -> Datensicherung: Speicherorte pruefen (z. B. externe Festplatte anschliessen), \"Jetzt sichern\".",
        "   Etikettendrucker in Windows einrichten (gleicher Name wie bisher) und ein Testetikett drucken.",
        "6. Handscanner und Handys: Bekommt der neue PC dieselbe IP-Adresse wie der alte (IT fragen), laeuft alles",
        "   weiter. Sonst die neue Adresse aus Einstellungen -> Handscanner / Handy oeffnen und die Apps neu",
        "   installieren. Das Sicherheitszertifikat bleibt gueltig und muss nicht neu installiert werden.",
        "",
        "Umzug abgebrochen? Am alten PC: Einstellungen -> Datensicherung -> \"Nur lesen aufheben\".",
    ]
    return "\r\n".join(zeilen) + "\r\n"


def erstellen(cfg, eng, ziel: Path, benutzer: str, mit_backups: bool = False, app_state=None) -> dict:
    """Schreibt Umzugspaket_<Zeit>.zip in ``ziel``. Setzt das System vorher auf „nur lesen“ (bei Fehler wieder aufgehoben)."""
    if not _laeuft.acquire(blocking=False):
        raise UmzugFehler("Es wird gerade schon ein Umzugspaket erstellt.")
    try:
        ziel.mkdir(parents=True, exist_ok=True)
        jetzt = datetime.now().replace(microsecond=0)
        stamm = f"Umzugspaket_{jetzt:%Y%m%d_%H%M%S}"
        datei, teil = ziel / f"{stamm}.zip", ziel / f"{stamm}.zip.teil"
        info = {"am": jetzt.isoformat(), "von": benutzer, "datei": str(datei)}
        with eng.connect() as con:
            vorher = sperre_lesen(con)
        sperre_setzen(eng, info)  # ab jetzt keine Buchungen mehr, die im Paket fehlen würden
        if app_state is not None:
            app_state.umzug_sperre = info
        try:
            oben = _ordnername()
            db_datei = cfg.path(cfg.daten.datenbank)
            ausser = {teil.resolve(), datei.resolve()}
            with tempfile.TemporaryDirectory() as tmp:
                kopie = Path(tmp) / "lager.db"
                sicherung.db_kopie(cfg, kopie)
                k = sqlite3.connect(kopie)
                try:
                    k.execute("DELETE FROM settings WHERE schluessel = ?", (SETTING,))  # neuer PC: nicht gesperrt
                    k.commit()
                finally:
                    k.close()
                anzahl = 0
                with zipfile.ZipFile(teil, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                    for p, name in _programmdateien(ausser):
                        z.write(p, f"{oben}/{name}")
                        anzahl += 1
                    for p, name in _datendateien(cfg, db_datei, ausser):
                        z.write(p, f"{oben}/{name}")
                        anzahl += 1
                    z.write(kopie, f"{oben}/daten/lager.db")
                    z.writestr(f"{oben}/config.toml", _config_text(cfg))
                    sk = cfgmod.BASE_DIR / ".secret_key"
                    if sk.exists():
                        z.write(sk, f"{oben}/.secret_key")
                    for name in ("logs", "druckausgabe", "backups"):
                        z.writestr(f"{oben}/{name}/", "")
                    if mit_backups:
                        for p in sicherung.sicherungen_in(cfg.path(cfg.backup.ordner), n=10_000):
                            if p.resolve() not in ausser:
                                z.write(p, f"{oben}/backups/{p.name}")
                                anzahl += 1
                    z.writestr(f"{oben}/UMZUG_LIESMICH.txt", _liesmich(cfg, info, oben))
                    z.writestr(f"{oben}/daten/umzug.json", json.dumps({**info, "mit_backups": mit_backups, "dateien": anzahl}, ensure_ascii=False, indent=1))
            with zipfile.ZipFile(teil) as z:
                if z.testzip() is not None:
                    raise UmzugFehler("Das Paket ist beschädigt (Prüfung nach dem Schreiben). Bitte anderen Speicherort wählen.")
            teil.replace(datei)
        except Exception:
            teil.unlink(missing_ok=True)
            sperre_setzen(eng, vorher)
            if app_state is not None:
                app_state.umzug_sperre = vorher
            raise
        info["groesse"] = datei.stat().st_size
        sperre_setzen(eng, info)
        if app_state is not None:
            app_state.umzug_sperre = info
        return info
    finally:
        _laeuft.release()
