"""Datensicherung: mehrere Speicherorte, mehrere Uhrzeiten am Tag, nur bei Änderungen, Status/Warnungen, Wiederherstellen.

Ablauf einer Sicherung: Datenbank konsistent kopieren (SQLite-Backup-Funktion, Buchungen laufen dabei weiter) →
Fingerabdruck des Inhalts → ZIP einmal bauen → in jeden Speicherort kopieren. Kopiert wird zuerst unter einem
Hilfsnamen (``….zip.teil``), geprüft und erst dann umbenannt: Ein abgezogener USB-Stick oder ein Stromausfall
hinterlässt keine halbe Sicherung unter richtigem Namen. Ein nicht erreichbarer Speicherort hält die anderen nicht auf.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("lagerverwaltung")

NAME = "lager_backup"
MIN_BEHALTEN = 3        # so viele neueste Sicherungen je Speicherort bleiben immer erhalten, egal wie alt
WARN_STUNDEN = 26       # ältere letzte Sicherung -> Warnung auf der Startseite
STATUS = "backup_status"    # Einstellung (JSON): Zustand je Speicherort
TERMIN = "backup_termin"    # Einstellung: zuletzt erledigter Termin "JJJJ-MM-TT HH:MM"
# Einträge, die sich ohne Zutun der Benutzer ändern – zählen nicht als Änderung für "nur bei Änderung"
FLUECHTIG = ("backup_", "letztes_backup", "letzte_meldemail")
ZEIT = "%Y-%m-%d %H:%M:%S"
UPLOAD = "wiederherstellen_upload.zip"

_sperre = threading.Lock()  # nie zwei Sicherungen/Wiederherstellungen gleichzeitig

LIESMICH = ("Datensicherung Lagerverwaltung\r\n\r\n"
            "Einfachster Weg: In der Lagerverwaltung unter Einstellungen -> Datensicherung -> Wiederherstellen\r\n"
            "diese Datei auswaehlen (aus einem Speicherort, per \"Andere Sicherung waehlen\" oder per Hochladen).\r\n\r\n"
            "Von Hand wiederherstellen:\r\n"
            "1. Lagerverwaltung beenden (windows\\4_AUTOSTART_AUS.bat).\r\n"
            "2. Im Ordner daten die Dateien lager.db-wal und lager.db-shm loeschen (falls vorhanden).\r\n"
            "   Wichtig: sonst mischt die Datenbank alte Restdaten in die Sicherung.\r\n"
            "3. lager.db aus dieser Sicherung nach daten\\lager.db kopieren (ueberschreiben).\r\n"
            "4. Ordner anhaenge aus dieser Sicherung nach daten\\anhaenge kopieren.\r\n"
            "5. Lagerverwaltung starten.\r\n")


class WiederherstellFehler(Exception):
    pass


# ------------------------------------------------------------------ Einstellungen lesen
@dataclass
class Ziel:
    ordner: str             # wie eingegeben (relativ zum Programmordner oder absolut)
    pfad: Path
    aufbewahren_tage: int
    haupt: bool = False

    @property
    def schluessel(self) -> str:
        return schluessel(self.pfad)


def schluessel(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _tage(v, standard: int = 30) -> int:
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return standard


def ziele(cfg) -> list[Ziel]:
    """Hauptspeicherort (``[backup] ordner``) plus ``weitere_ziele``; doppelte Ordner zählen einmal."""
    b = cfg.backup
    haupt = (b.ordner or "backups").strip() or "backups"
    out = [Ziel(haupt, cfg.path(haupt), _tage(b.aufbewahren_tage), True)]
    gesehen = {out[0].schluessel}
    for z in b.weitere_ziele or []:
        if not isinstance(z, dict):
            continue
        o = str(z.get("ordner") or "").strip()
        if not o:
            continue
        zi = Ziel(o, cfg.path(o), _tage(z.get("aufbewahren_tage")))
        if zi.schluessel not in gesehen:
            gesehen.add(zi.schluessel)
            out.append(zi)
    return out


def uhrzeiten(text: str) -> list[str]:
    """``"7:00, 12:00; 22.00"`` -> ``["07:00", "12:00", "22:00"]``. ValueError bei ungültiger Angabe."""
    out = set()
    for teil in re.split(r"[,;\s]+", text or ""):
        if not teil:
            continue
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", teil)
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError(f"Ungültige Uhrzeit „{teil}“ – bitte als HH:MM angeben, z. B. 07:00, 12:00, 22:00.")
        out.add(f"{int(m[1]):02d}:{m[2]}")
    if not out:
        raise ValueError("Bitte mindestens eine Uhrzeit angeben.")
    return sorted(out)


def faelliger_termin(text: str, jetzt: datetime) -> str | None:
    """Letzter heutiger Termin, der schon erreicht ist (``"JJJJ-MM-TT HH:MM"``), sonst None.

    Ein verpasster Termin (PC war aus) wird damit beim nächsten Start nachgeholt – aber nur einmal, nicht für jeden
    verpassten Termin einzeln."""
    try:
        zeiten = uhrzeiten(text)
    except ValueError:
        return None
    erreicht = [z for z in zeiten if z <= jetzt.strftime("%H:%M")]
    return f"{jetzt:%Y-%m-%d} {erreicht[-1]}" if erreicht else None


# ------------------------------------------------------------------ Status (in der Tabelle settings)
def status_lesen(con) -> dict:
    from .betrieb import get_setting
    try:
        s = json.loads(get_setting(con, STATUS) or "{}")
        return s if isinstance(s, dict) else {}
    except ValueError:
        return {}


def _status_schreiben(eng, status: dict, extra: dict | None = None) -> None:
    from .betrieb import set_setting
    with eng.execution_options(schreiben=True).begin() as con:
        set_setting(con, STATUS, json.dumps(status, ensure_ascii=False))
        for k, v in (extra or {}).items():
            set_setting(con, k, v)


def _jetzt() -> str:
    return datetime.now().strftime(ZEIT)


def _zeit(s: str | None) -> datetime | None:
    try:
        return datetime.strptime(s, ZEIT) if s else None
    except ValueError:
        return None


# ------------------------------------------------------------------ Bausteine
def db_kopie(cfg, ziel: Path) -> None:
    """Konsistente Kopie der laufenden Datenbank (auch während gebucht wird)."""
    src = sqlite3.connect(str(cfg.path(cfg.daten.datenbank)), timeout=60)
    dst = sqlite3.connect(str(ziel))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def fingerabdruck(db_datei: Path, anh: Path) -> str:
    """Prüfsumme über alle Daten und Anhänge – ohne Einträge, die sich ohne Zutun der Benutzer ändern
    (Sicherungsstatus, letzter Login)."""
    h = hashlib.sha256()
    con = sqlite3.connect(str(db_datei))
    try:
        tabellen = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tabellen:
            cur = con.execute(f'SELECT * FROM "{t}" ORDER BY rowid')
            spalten = [d[0] for d in cur.description]
            h.update(f"\x00{t}:{','.join(spalten)}\n".encode())
            weg = spalten.index("letzter_login") if t == "users" and "letzter_login" in spalten else None
            key = spalten.index("schluessel") if t == "settings" and "schluessel" in spalten else None
            for row in cur:
                if key is not None and str(row[key]).startswith(FLUECHTIG):
                    continue
                if weg is not None:
                    row = row[:weg] + row[weg + 1:]
                h.update(repr(row).encode())
                h.update(b"\n")
    finally:
        con.close()
    if anh.exists():
        for f in sorted(anh.rglob("*")):
            if f.is_file():
                st = f.stat()
                h.update(f"{f.relative_to(anh).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def zip_bauen(cfg, kopie: Path, datei: Path) -> None:
    with zipfile.ZipFile(datei, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(kopie, "lager.db")
        anh = cfg.path(cfg.daten.anhaenge)
        if anh.exists():
            for f in sorted(anh.rglob("*")):
                if f.is_file():
                    z.write(f, f"anhaenge/{f.relative_to(anh).as_posix()}")
        z.writestr("LIESMICH.txt", LIESMICH)


def ablegen(quelle: Path, ordner: Path, stamm: str) -> Path:
    """ZIP in den Speicherort kopieren: erst als ``.teil``, auf die Platte schreiben lassen, prüfen, dann umbenennen."""
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{stamm}.zip"
    n = 1
    while datei.exists():  # zwei Sicherungen in derselben Sekunde nicht überschreiben
        n += 1
        datei = ordner / f"{stamm}_{n}.zip"
    teil = datei.with_name(datei.name + ".teil")
    try:
        with open(quelle, "rb") as a, open(teil, "wb") as b:
            shutil.copyfileobj(a, b, 1024 * 1024)
            b.flush()
            os.fsync(b.fileno())
        with zipfile.ZipFile(teil) as z:
            if z.testzip() is not None:
                raise OSError("Die Kopie ist beschädigt (Prüfsumme stimmt nicht).")
        os.replace(teil, datei)
    finally:
        teil.unlink(missing_ok=True)
    return datei


def aufraeumen(ordner: Path, tage: int, name: str = NAME) -> int:
    """Sicherungen älter als ``tage`` löschen – die neuesten ``MIN_BEHALTEN`` bleiben immer.

    Wichtig bei "nur bei Änderung": Ändert sich wochenlang nichts, entstehen keine neuen Sicherungen; ohne diese
    Untergrenze würde die Aufbewahrungsfrist irgendwann alle löschen."""
    if not ordner.exists():
        return 0
    dateien = sorted(ordner.glob(f"{name}_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    grenze = time.time() - tage * 86400
    n = 0
    for alt in dateien[MIN_BEHALTEN:]:
        if alt.stat().st_mtime < grenze:
            alt.unlink(missing_ok=True)
            n += 1
    for teil in ordner.glob(f"{name}_*.zip.teil"):  # Reste eines abgebrochenen Kopiervorgangs
        if teil.stat().st_mtime < time.time() - 3600:
            teil.unlink(missing_ok=True)
    return n


def _laufwerk_fehlt(p: Path) -> str:
    """Laufwerksbuchstabe (z. B. ``S:``) nicht vorhanden -> Klartext, sonst ""."""
    drive = os.path.splitdrive(str(p))[0]
    if os.name == "nt" and re.fullmatch(r"[A-Za-z]:", drive or "") and not os.path.exists(drive + "\\"):
        return (f"Laufwerk {drive.upper()} ist nicht vorhanden – ist die externe Festplatte bzw. der USB-Stick angeschlossen "
                f"und hat er noch denselben Laufwerksbuchstaben?")
    return ""


def fehlertext(p: Path, e: Exception) -> str:
    if t := _laufwerk_fehlt(p):
        return t
    if isinstance(e, PermissionError):
        return f"Keine Schreibberechtigung für {p}."
    if isinstance(e, (FileExistsError, NotADirectoryError)):
        return f"{p} ist kein Ordner (dort liegt eine Datei)."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return f"Kein Speicherplatz mehr frei in {p}."
    if isinstance(e, OSError) and e.strerror:  # ohne "[WinError 53]"-Vorspann; Windows liefert den Text auf Deutsch
        return f"{e.strerror}: {e.filename or p}"
    return f"{type(e).__name__}: {e}"


def einzel_sicherung(cfg, ordner: Path, name: str = NAME, aufbewahren_tage: int | None = None) -> Path:
    """Eine Sicherung in genau einen Ordner (z. B. ``vor_uebernahme`` vor einer Datenübernahme)."""
    with tempfile.TemporaryDirectory() as tmp:
        kopie, zipdatei = Path(tmp) / "lager.db", Path(tmp) / "sicherung.zip"
        db_kopie(cfg, kopie)
        zip_bauen(cfg, kopie, zipdatei)
        datei = ablegen(zipdatei, ordner, f"{name}_{datetime.now():%Y%m%d_%H%M%S}")
    aufraeumen(ordner, cfg.backup.aufbewahren_tage if aufbewahren_tage is None else aufbewahren_tage, name)
    return datei


# ------------------------------------------------------------------ Sicherung in alle Speicherorte
@dataclass
class Ergebnis:
    ziel: Ziel
    ok: bool
    datei: Path | None = None
    unveraendert: bool = False
    fehler: str = ""
    uebersprungen: bool = False


def sichern(cfg, eng, erzwingen: bool = False, nur: set[str] | None = None, melden: bool = False) -> list[Ergebnis]:
    """Sichert in alle Speicherorte (bzw. nur die in ``nur`` genannten).

    ``erzwingen``: auch ohne Änderung eine neue Datei schreiben ("Jetzt sichern").
    ``melden``: bei Fehlern eine E-Mail schicken (höchstens eine je Speicherort und Tag), falls E-Mail eingerichtet ist.
    """
    with _sperre:
        return _sichern(cfg, eng, erzwingen, nur, melden)


def _sichern(cfg, eng, erzwingen, nur, melden) -> list[Ergebnis]:
    alle = ziele(cfg)
    with eng.connect() as con:
        status = status_lesen(con)
    ergebnisse: list[Ergebnis] = []
    jetzt = datetime.now()
    stamm = f"{NAME}_{jetzt:%Y%m%d_%H%M%S}"
    nur_aenderung = bool(cfg.backup.nur_bei_aenderung) and not erzwingen
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "lager.db"
        db_kopie(cfg, kopie)
        fp = fingerabdruck(kopie, cfg.path(cfg.daten.anhaenge))
        zipdatei: Path | None = None
        for z in alle:
            st = dict(status.get(z.schluessel) or {})
            st["ordner"] = z.ordner
            if nur is not None and z.schluessel not in nur:
                ergebnisse.append(Ergebnis(z, True, uebersprungen=True))
                status[z.schluessel] = st
                continue
            try:
                vorhanden = st.get("datei") and Path(st["datei"]).is_file()
                if nur_aenderung and st.get("fingerabdruck") == fp and vorhanden:
                    st.update(ok_am=_jetzt(), unveraendert=True)
                    aufraeumen(z.pfad, z.aufbewahren_tage)
                    ergebnisse.append(Ergebnis(z, True, Path(st["datei"]), unveraendert=True))
                else:
                    if zipdatei is None:
                        zipdatei = Path(tmp) / "sicherung.zip"
                        zip_bauen(cfg, kopie, zipdatei)
                    datei = ablegen(zipdatei, z.pfad, stamm)
                    aufraeumen(z.pfad, z.aufbewahren_tage)
                    st.update(ok_am=_jetzt(), gesichert_am=_jetzt(), datei=str(datei), groesse=datei.stat().st_size,
                              fingerabdruck=fp, unveraendert=False)
                    ergebnisse.append(Ergebnis(z, True, datei))
            except Exception as e:
                text = fehlertext(z.pfad, e)
                st.update(fehler=text, fehler_am=_jetzt())
                ergebnisse.append(Ergebnis(z, False, fehler=text))
                log.warning("Datensicherung nach %s fehlgeschlagen: %s", z.pfad, text)
            try:
                st["frei"] = shutil.disk_usage(z.pfad).free
            except OSError:
                st.pop("frei", None)
            status[z.schluessel] = st
    if melden:
        _fehler_melden(cfg, ergebnisse, status)
    # nur noch eingestellte Speicherorte merken (entfernte fallen heraus)
    status = {z.schluessel: status[z.schluessel] for z in alle if z.schluessel in status}
    extra = {"letztes_backup": jetzt.strftime("%Y-%m-%d %H:%M")} if any(e.ok and not e.uebersprungen for e in ergebnisse) else {}
    _status_schreiben(eng, status, extra)
    return ergebnisse


def _fehler_melden(cfg, ergebnisse: list[Ergebnis], status: dict) -> None:
    if not (cfg.mail.aktiv and cfg.mail.server and cfg.mail.empfaenger):
        return
    heute = datetime.now().strftime("%Y-%m-%d")
    neu = [e for e in ergebnisse if not e.ok and status[e.ziel.schluessel].get("gemeldet") != heute]
    if not neu:
        return
    from .betrieb import mail_senden
    text = ("Die Datensicherung der Lagerverwaltung konnte nicht in alle Speicherorte schreiben:\n\n"
            + "\n".join(f"- {e.ziel.pfad}: {e.fehler}" for e in neu)
            + "\n\nBitte prüfen (Einstellungen -> Datensicherung). Diese Meldung kommt höchstens einmal am Tag je Speicherort.")
    try:
        mail_senden(cfg.mail, "Lagerverwaltung: Datensicherung fehlgeschlagen", text)
        for e in neu:
            status[e.ziel.schluessel]["gemeldet"] = heute
    except Exception:
        log.exception("Warn-Mail zur Datensicherung konnte nicht gesendet werden")


# ------------------------------------------------------------------ Übersicht und Warnungen
def _neueste(ordner: Path) -> Path | None:
    try:
        dateien = list(ordner.glob(f"{NAME}_*.zip"))
    except OSError:
        return None
    return max(dateien, key=lambda p: p.stat().st_mtime) if dateien else None


def _gleiches_laufwerk(p: Path) -> bool:
    from ..config import BASE_DIR
    a, b = os.path.splitdrive(os.path.abspath(str(p)))[0], os.path.splitdrive(os.path.abspath(str(BASE_DIR)))[0]
    return bool(a) and a.lower() == b.lower()


def uebersicht(cfg, con, jetzt: datetime | None = None) -> list[dict]:
    """Zustand je Speicherort für die Einstellungsseite und die Startseite. Greift nur auf den Hauptspeicherort
    im Dateisystem zu (Fallback für Sicherungen aus älteren Versionen) – die Startseite bleibt so auch bei einem
    hängenden Netzlaufwerk schnell."""
    jetzt = jetzt or datetime.now()
    status = status_lesen(con)
    out = []
    for z in ziele(cfg):
        st = dict(status.get(z.schluessel) or {})
        if z.haupt and not st.get("ok_am"):
            neu = _neueste(z.pfad)
            if neu:
                st.update(datei=str(neu), groesse=neu.stat().st_size,
                          ok_am=datetime.fromtimestamp(neu.stat().st_mtime).strftime(ZEIT))
        warnung = ""
        ok_am, fehler_am = _zeit(st.get("ok_am")), _zeit(st.get("fehler_am"))
        if st.get("fehler") and fehler_am and (not ok_am or fehler_am > ok_am):
            warnung = st["fehler"]
        elif cfg.backup.aktiv and not ok_am:
            warnung = "Hier liegt noch keine Sicherung – „Speichern und jetzt sichern“ ausführen."
        elif cfg.backup.aktiv and ok_am < jetzt - timedelta(hours=WARN_STUNDEN):
            warnung = f"Die letzte Sicherung ist älter als einen Tag ({ok_am:%d.%m.%Y %H:%M})."
        elif st.get("frei") is not None and st.get("groesse") and st["frei"] < 3 * st["groesse"] + 50 * 1024 * 1024:
            warnung = "Fast kein Speicherplatz mehr frei."
        hinweis = ""
        if not z.haupt and _gleiches_laufwerk(z.pfad):
            hinweis = "Liegt auf demselben Laufwerk wie die Lagerverwaltung – schützt nicht, wenn der PC ausfällt."
        out.append({"nr": len(out), "ordner": z.ordner, "pfad": str(z.pfad), "haupt": z.haupt, "aufbewahren_tage": z.aufbewahren_tage,
                    "ok_am": ok_am, "gesichert_am": _zeit(st.get("gesichert_am")), "datei": st.get("datei"),
                    "groesse": st.get("groesse"), "frei": st.get("frei"), "fehler": st.get("fehler") if warnung == st.get("fehler") else "",
                    "unveraendert": st.get("unveraendert"), "warnung": warnung, "hinweis": hinweis})
    return out


def warnungen(cfg, con) -> list[str]:
    if not cfg.backup.aktiv:
        return ["Die automatische Datensicherung ist ausgeschaltet."]
    return [f"{'Hauptspeicherort' if u['haupt'] else u['pfad']}: {u['warnung']}" for u in uebersicht(cfg, con) if u["warnung"]]


def sicherungen_in(ordner: Path, n: int = 15) -> list[Path]:
    """Sicherungen der Lagerverwaltung in einem Ordner, neueste zuerst (auch vor_uebernahme/vor_wiederherstellung)."""
    try:
        dateien = [p for p in ordner.glob("*.zip") if p.is_file() and re.match(r"(lager_backup|vor_\w+)_\d{8}_\d{6}", p.name)]
        return sorted(dateien, key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    except OSError:
        return []


# ------------------------------------------------------------------ Ordnerauswahl und Prüfen
ARTEN = {2: "USB-Stick / Wechseldatenträger", 3: "Festplatte", 4: "Netzlaufwerk", 6: "RAM-Disk"}


def laufwerke() -> list[dict]:
    """Laufwerke, die die Lagerverwaltung sieht. Läuft sie als Dienst, fehlen verbundene Netzlaufwerke (N: usw.) –
    dort den Netzwerkpfad (\\\\server\\freigabe) eintragen."""
    if os.name != "nt":
        return [{"pfad": "/", "name": "/", "art": "", "frei": _frei("/")}]
    import ctypes
    import string
    k = ctypes.windll.kernel32
    alt = k.SetErrorMode(1)  # leere Kartenleser nicht mit "Kein Datenträger"-Fenster melden
    try:
        maske = k.GetLogicalDrives()
        system = (os.environ.get("SystemDrive") or "C:").upper()
        out = []
        for i, b in enumerate(string.ascii_uppercase):
            if not maske & (1 << i):
                continue
            wurzel = f"{b}:\\"
            typ = k.GetDriveTypeW(wurzel)
            if typ not in ARTEN:
                continue
            name = ctypes.create_unicode_buffer(261)
            k.GetVolumeInformationW(wurzel, name, 261, None, None, None, None, 0)
            frei = _frei(wurzel)
            if frei is None:
                continue
            art = ARTEN[typ] + (" (Windows)" if f"{b}:" == system else "")
            out.append({"pfad": wurzel, "name": f"{name.value or 'Laufwerk'} ({b}:)", "art": art, "frei": frei})
        return out
    finally:
        k.SetErrorMode(alt)


def _frei(p) -> int | None:
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


VERSTECKT = {"System Volume Information", "$RECYCLE.BIN", "Recovery", "Config.Msi", "PerfLogs"}


def ordner_inhalt(cfg, pfad: str) -> dict:
    """Unterordner (und Sicherungsdateien) eines Ordners. Existiert er noch nicht, wird der nächste vorhandene
    übergeordnete Ordner gezeigt."""
    if not (pfad or "").strip():
        return {"pfad": "", "eltern": None, "ordner": [], "dateien": [], "laufwerke": laufwerke(), "hinweis": ""}
    p = cfg.path(pfad.strip())
    hinweis = ""
    while not p.is_dir():
        if p.parent == p:
            return {"pfad": "", "eltern": None, "ordner": [], "dateien": [], "laufwerke": laufwerke(),
                    "hinweis": f"{pfad} ist nicht erreichbar."}
        if not hinweis:
            hinweis = f"„{p.name}“ gibt es hier noch nicht – wird beim ersten Sichern angelegt."
        p = p.parent
    ordner = []
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False) or e.name in VERSTECKT or e.name.startswith(("$", ".")):
                        continue
                    if os.name == "nt" and e.stat(follow_symlinks=False).st_file_attributes & 6:  # versteckt | System
                        continue
                except OSError:
                    continue
                ordner.append(e.name)
                if len(ordner) >= 1000:
                    break
    except OSError as e:
        hinweis = fehlertext(p, e)
    dateien = [{"name": d.name, "pfad": str(d), "groesse": d.stat().st_size,
                "zeit": datetime.fromtimestamp(d.stat().st_mtime).strftime("%d.%m.%Y %H:%M")} for d in sicherungen_in(p, 50)]
    return {"pfad": str(p), "eltern": str(p.parent) if p.parent != p else "", "ordner": sorted(ordner, key=str.lower),
            "dateien": dateien, "laufwerke": [], "hinweis": hinweis}


def neuer_ordner(cfg, pfad: str, name: str) -> Path:
    name = (name or "").strip()
    if not name or name in (".", "..") or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or len(name) > 100:
        raise ValueError("Ungültiger Ordnername.")
    p = cfg.path(pfad) / name
    p.mkdir(parents=False, exist_ok=True)
    return p


def ziel_pruefen(cfg, pfad: str) -> str:
    """Schreibt eine Testdatei in den Ordner (legt ihn bei Bedarf an), liest sie zurück und löscht sie wieder.
    Läuft mit den Rechten der Lagerverwaltung (beim Dienst: NETZWERKDIENST) – genau die zählen beim Sichern."""
    if not (pfad or "").strip():
        raise ValueError("Bitte einen Ordner angeben.")
    p = cfg.path(pfad.strip())
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".lager_schreibtest_{os.getpid()}_{time.time_ns()}"
        inhalt = os.urandom(64)
        with open(probe, "wb") as f:
            f.write(inhalt)
            f.flush()
            os.fsync(f.fileno())
        try:
            if probe.read_bytes() != inhalt:
                raise OSError("Gelesene Daten weichen ab.")
        finally:
            probe.unlink(missing_ok=True)
    except OSError as e:
        raise ValueError(fehlertext(p, e)) from e
    frei = _frei(p)
    return f"In Ordnung: {p} ist beschreibbar" + (f", {groesse_text(frei)} frei." if frei is not None else ".")


def groesse_text(n: int | None) -> str:
    if n is None:
        return "–"
    for einheit, f in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= f:
            return f"{n / f:.1f} {einheit}".replace(".", ",")
    return f"{n} Byte"


# ------------------------------------------------------------------ Wiederherstellen
PFLICHT_TABELLEN = {"users", "artikel", "bewegungen", "bestand", "settings"}


def _sicherer_name(name: str) -> bool:
    teile = name.split("/")
    return name.startswith("anhaenge/") and "\\" not in name and ":" not in name and all(t not in ("", ".", "..") for t in teile[1:])


def sicherung_pruefen(datei: Path) -> dict:
    """Prüft eine Sicherungsdatei gründlich, bevor sie den aktuellen Stand ersetzen darf."""
    try:
        z = zipfile.ZipFile(datei)
    except (zipfile.BadZipFile, OSError) as e:
        raise WiederherstellFehler(f"{datei.name} ist keine lesbare ZIP-Datei.") from e
    with z:
        namen = z.namelist()
        if "lager.db" not in namen:
            raise WiederherstellFehler("Die Datei enthält keine Datenbank (lager.db) – ist das eine Sicherung der Lagerverwaltung?")
        anh = [n for n in namen if n.startswith("anhaenge/") and not n.endswith("/")]
        if any(not _sicherer_name(n) for n in anh):
            raise WiederherstellFehler("Die Sicherung enthält ungültige Dateinamen und wird nicht verwendet.")
        try:
            if z.testzip() is not None:
                raise WiederherstellFehler("Die Sicherung ist beschädigt (Prüfsumme stimmt nicht).")
        except (zipfile.BadZipFile, OSError) as e:
            raise WiederherstellFehler("Die Sicherung ist beschädigt.") from e
        erstellt = datetime(*z.getinfo("lager.db").date_time)
        with tempfile.TemporaryDirectory() as tmp:
            db_datei = Path(tmp) / "lager.db"
            with z.open("lager.db") as a, open(db_datei, "wb") as b:
                shutil.copyfileobj(a, b, 1024 * 1024)
            info = _db_info(db_datei)
    return {**info, "anhaenge": len(anh), "erstellt": erstellt, "datei": datei.name, "pfad": str(datei),
            "groesse": datei.stat().st_size}


def _db_info(db_datei: Path) -> dict:
    con = sqlite3.connect(str(db_datei))
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise WiederherstellFehler("Die Datenbank in der Sicherung ist beschädigt.")
        tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if fehlt := PFLICHT_TABELLEN - tabellen:
            raise WiederherstellFehler(f"Die Datenbank in der Sicherung ist unvollständig (fehlt: {', '.join(sorted(fehlt))}).")
        admins = con.execute("SELECT count(*) FROM users WHERE rolle='admin' AND aktiv=1 AND coalesce(pw_hash,'') != ''").fetchone()[0]
        if not admins:
            raise WiederherstellFehler("In der Sicherung gibt es keinen aktiven Administrator – danach könnte sich niemand mehr anmelden.")
        return {"artikel": con.execute("SELECT count(*) FROM artikel").fetchone()[0],
                "buchungen": con.execute("SELECT count(*) FROM bewegungen").fetchone()[0],
                "letzte_buchung": _als_zeit(con.execute("SELECT max(zeit) FROM bewegungen").fetchone()[0]),
                "benutzer": con.execute("SELECT count(*) FROM users").fetchone()[0]}
    except sqlite3.DatabaseError as e:
        raise WiederherstellFehler("Die Datenbank in der Sicherung ist beschädigt oder keine Datenbank der Lagerverwaltung.") from e
    finally:
        con.close()


def _als_zeit(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)[:19]) if v else None
    except ValueError:
        return None


def _ersetzen(quelle: Path, ziel: Path, versuche: int = 10) -> None:
    for i in range(versuche):  # Windows: Ordner kurz gesperrt, z. B. weil gerade ein Foto ausgeliefert wird
        try:
            os.replace(quelle, ziel)
            return
        except PermissionError:
            if i == versuche - 1:
                raise
            time.sleep(0.5)


def wiederherstellen(cfg, eng, datei: Path, benutzer: str) -> dict:
    """Ersetzt Datenbank und Anhänge durch die Sicherung. Vorher wird der aktuelle Stand als
    ``vor_wiederherstellung_….zip`` im Hauptspeicherort gesichert.

    Die Datenbank wird über die SQLite-Backup-Funktion in die laufende Datenbank kopiert: Gleichzeitige Buchungen
    warten kurz, niemand liest einen halben Stand, und es bleiben keine alten -wal-Reste zurück."""
    from .. import db
    from .betrieb import get_setting, set_setting
    from .lager import audit
    with _sperre:
        info = sicherung_pruefen(datei)
        vorher = einzel_sicherung(cfg, cfg.path(cfg.backup.ordner), name="vor_wiederherstellung", aufbewahren_tage=365)
        anh = cfg.path(cfg.daten.anhaenge)
        anh.parent.mkdir(parents=True, exist_ok=True)
        stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        neu, alt = anh.with_name(f".anhaenge_neu_{stempel}"), anh.with_name(f".anhaenge_alt_{stempel}")
        with eng.connect() as con:  # Sicherungsstatus des PCs behalten (gehört nicht zum Datenstand)
            bewahren = {k: get_setting(con, k) for k in (STATUS, TERMIN, "letztes_backup", "letzte_meldemail")}
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(datei) as z:
            db_datei = Path(tmp) / "lager.db"
            with z.open("lager.db") as a, open(db_datei, "wb") as b:
                shutil.copyfileobj(a, b, 1024 * 1024)
            neu.mkdir()
            try:
                for n in z.namelist():
                    if n.startswith("anhaenge/") and not n.endswith("/"):
                        ziel = neu.joinpath(*n.split("/")[1:])
                        if not ziel.resolve().is_relative_to(neu.resolve()):
                            raise WiederherstellFehler("Ungültiger Dateiname in der Sicherung.")
                        ziel.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(n) as a, open(ziel, "wb") as b:
                            shutil.copyfileobj(a, b, 1024 * 1024)
                src = sqlite3.connect(str(db_datei))
                dst = sqlite3.connect(str(cfg.path(cfg.daten.datenbank)), timeout=60)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
            except BaseException:
                shutil.rmtree(neu, ignore_errors=True)
                raise
        eng.dispose()  # offene Verbindungen verwerfen, die neue Datenbank frisch öffnen
        db.md.create_all(eng)  # Sicherung aus älterer Version: neue Tabellen ergänzen
        if anh.exists():
            _ersetzen(anh, alt)
        _ersetzen(neu, anh)
        shutil.rmtree(alt, ignore_errors=True)
        with eng.execution_options(schreiben=True).begin() as con:
            for k, v in bewahren.items():
                if v is not None:
                    set_setting(con, k, v)
            audit(con, benutzer, "Datensicherung wiederhergestellt", datei.name,
                  {"sicherung_vom": info["erstellt"], "artikel": info["artikel"], "buchungen": info["buchungen"],
                   "vorheriger_stand": vorher.name})
        log.warning("Datensicherung %s wiederhergestellt durch %s (vorheriger Stand: %s)", datei, benutzer, vorher)
    return {**info, "vorher": vorher.name}
