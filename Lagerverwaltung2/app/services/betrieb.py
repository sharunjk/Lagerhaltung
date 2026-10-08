"""Betrieb: Passwörter, E-Mail, Datensicherung, Hintergrund-Zeitplaner."""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import logging
import os
import smtplib
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import insert, select, text, update
from sqlalchemy.engine import Engine

from ..db import settings as lv_settings

log = logging.getLogger("lagerverwaltung")


# ------------------------------------------------------------------ Passwörter (PBKDF2, nur Standardbibliothek)
def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 240_000)
    return f"pbkdf2$240000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        new = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(new, base64.b64decode(dk))
    except Exception:
        return False


# ------------------------------------------------------------------ Einstellungen in der DB
def get_setting(con, key: str, default: str | None = None) -> str | None:
    v = con.execute(select(lv_settings.c.wert).where(lv_settings.c.schluessel == key)).scalar()
    return default if v is None else v


def set_setting(con, key: str, value: str) -> None:
    if con.execute(select(lv_settings.c.schluessel).where(lv_settings.c.schluessel == key)).first():
        con.execute(update(lv_settings).where(lv_settings.c.schluessel == key).values(wert=value))
    else:
        con.execute(insert(lv_settings).values(schluessel=key, wert=value))


# ------------------------------------------------------------------ E-Mail
def mail_senden(mcfg, betreff: str, text_body: str, html_body: str | None = None) -> None:
    if not mcfg.server or not mcfg.empfaenger:
        raise RuntimeError("SMTP-Server oder Empfänger fehlen.")
    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = mcfg.absender or mcfg.benutzer
    msg["To"] = ", ".join(e.strip() for e in mcfg.empfaenger.replace(";", ",").split(",") if e.strip())
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    port = int(mcfg.port or (465 if mcfg.ssl else 587))
    if mcfg.ssl:
        s = smtplib.SMTP_SSL(mcfg.server, port, timeout=20)
    else:
        s = smtplib.SMTP(mcfg.server, port, timeout=20)
        if mcfg.starttls:
            s.starttls()
    try:
        if mcfg.benutzer:
            s.login(mcfg.benutzer, mcfg.passwort)
        s.send_message(msg)
    finally:
        s.quit()


def meldebestand_mail(eng: Engine, cfg, nur_wenn_vorhanden: bool = True) -> int:
    from .queries import artikel_liste
    from .lager import fmt_num
    with eng.connect() as con:
        arts = artikel_liste(con, filter_="melden", sort="status")
    if not arts and nur_wenn_vorhanden:
        return 0
    zeilen = [f"{a['nummer']:<10} {(a['bezeichnung'] or '')[:40]:<40} Bestand {fmt_num(a['bestand']):>5}  "
              f"Melde {fmt_num(a['meldebestand']) or '-':>4}  Mindest {fmt_num(a['mindestbestand']) or '-':>4}  "
              f"{'KRITISCH' if a['status'] == 'kritisch' else ''}" for a in arts]
    rows = "".join(
        f"<tr><td>{a['nummer']}</td><td>{a['bezeichnung'] or ''}</td><td align=right>{fmt_num(a['bestand'])}</td>"
        f"<td align=right>{fmt_num(a['meldebestand'])}</td><td align=right>{fmt_num(a['mindestbestand'])}</td>"
        f"<td style='color:{'#b91c1c' if a['status'] == 'kritisch' else '#b45309'}'>{'kritisch' if a['status'] == 'kritisch' else 'nachbestellen'}</td></tr>"
        for a in arts)
    html = (f"<p>{len(arts)} Artikel haben den Melde- bzw. Mindestbestand erreicht:</p>"
            "<table cellpadding=4 style='border-collapse:collapse;font-family:Arial;font-size:13px'>"
            "<tr style='background:#eee'><th>Nr.</th><th>Bezeichnung</th><th>Bestand</th><th>Melde</th><th>Mindest</th><th>Status</th></tr>"
            f"{rows}</table>")
    mail_senden(cfg.mail, f"Lager: {len(arts)} Artikel unter Meldebestand ({date.today():%d.%m.%Y})",
                "Artikel unter Melde-/Mindestbestand:\n\n" + "\n".join(zeilen), html)
    return len(arts)


# ------------------------------------------------------------------ Datensicherung
def backup_erstellen(cfg, ordner: Path | None = None, aufbewahren_tage: int | None = None, name: str = "lager_backup") -> Path:
    """Sichert Datenbank (konsistent über die SQLite-Backup-Funktion) und Anhänge in eine ZIP-Datei."""
    import sqlite3
    import tempfile
    import zipfile
    ordner = ordner or cfg.path(cfg.backup.ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "lager.db"
        src = sqlite3.connect(str(cfg.path(cfg.daten.datenbank)))
        dst = sqlite3.connect(str(kopie))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        with zipfile.ZipFile(datei, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(kopie, "lager.db")
            anh = cfg.path(cfg.daten.anhaenge)
            if anh.exists():
                for f in anh.rglob("*"):
                    if f.is_file():
                        z.write(f, f"anhaenge/{f.relative_to(anh)}")
            z.writestr("LIESMICH.txt", "Datensicherung Lagerverwaltung\r\n"
                       "Wiederherstellen: Lagerverwaltung beenden, lager.db nach daten\\lager.db kopieren,\r\n"
                       "Ordner anhaenge nach daten\\anhaenge kopieren, Lagerverwaltung starten.\r\n")
    tage = cfg.backup.aufbewahren_tage if aufbewahren_tage is None else aufbewahren_tage
    grenze = time.time() - tage * 86400
    for alt in ordner.glob(f"{name}_*.zip"):
        if alt.stat().st_mtime < grenze:
            alt.unlink(missing_ok=True)
    return datei


# ------------------------------------------------------------------ Zeitplaner
class Zeitplaner(threading.Thread):
    """Prüft minütlich, ob die tägliche Sicherung bzw. Meldebestands-Mail fällig ist."""

    def __init__(self, eng: Engine, cfg_getter):
        super().__init__(daemon=True, name="zeitplaner")
        self.eng = eng
        self.cfg_getter = cfg_getter
        self.stop_event = threading.Event()

    def _faellig(self, key: str, uhrzeit: str) -> bool:
        try:
            h, m = (int(x) for x in uhrzeit.split(":"))
        except ValueError:
            return False
        jetzt = datetime.now()
        if (jetzt.hour, jetzt.minute) < (h, m):
            return False
        with self.eng.execution_options(schreiben=True).begin() as con:
            if get_setting(con, key) == jetzt.strftime("%Y-%m-%d"):
                return False
            set_setting(con, key, jetzt.strftime("%Y-%m-%d"))
        return True

    def run(self):
        while not self.stop_event.wait(60):
            cfg = self.cfg_getter()
            try:
                if cfg.backup.aktiv and self._faellig("letztes_backup", cfg.backup.uhrzeit):
                    p = backup_erstellen(cfg)
                    log.info("Datensicherung erstellt: %s", p)
                if cfg.mail.aktiv and self._faellig("letzte_meldemail", cfg.mail.uhrzeit):
                    n = meldebestand_mail(self.eng, cfg)
                    log.info("Meldebestands-Mail: %s Artikel", n)
            except Exception:  # pragma: no cover
                log.exception("Fehler im Zeitplaner")
