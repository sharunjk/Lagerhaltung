"""Datenbank-Migrationen: Änderungen an bestehenden Tabellen, nummeriert und nachvollziehbar.

Regeln (Schutz der produktiven Lagerdaten):

* Migrationen fügen nur hinzu (neue Tabellen, neue optionale Spalten). Nichts wird umbenannt oder gelöscht. Dadurch
  läuft im Notfall auch die vorherige Programmversion weiter mit der aktualisierten Datenbank.
* Jede Migration prüft selbst, ob ihre Änderung schon da ist (wiederholbar).
* Alle ausstehenden Migrationen laufen in EINER Transaktion: ganz oder gar nicht.
* Beim Programmstart (``vor_start``) laufen sie zuerst an einer Kopie der Datenbank. Nur wenn sich dort Artikel,
  Bestände, Buchungen und Benutzer nicht verändert haben und die Datenbank fehlerfrei ist, wird der aktuelle Stand
  gesichert (``vor_update_….zip``) und die echte Datenbank aktualisiert.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("lagerverwaltung")


class MigrationsFehler(RuntimeError):
    pass


def _spalten(con: Connection, tabelle: str) -> set[str]:
    return {r[1] for r in con.exec_driver_sql(f"PRAGMA table_info({tabelle})")}


def _spalte_ergaenzen(con: Connection, tabelle: str, spalte: str, typ: str) -> None:
    if spalte not in _spalten(con, tabelle):
        con.exec_driver_sql(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")


def _m1_buchungen_preis_auftrag(con: Connection) -> None:
    _spalte_ergaenzen(con, "bewegungen", "preis", "FLOAT")
    _spalte_ergaenzen(con, "bewegungen", "auftrag_id", "INTEGER")
    _spalte_ergaenzen(con, "reservierungen", "auftrag_id", "INTEGER")


def _m2_importart(con: Connection) -> None:
    _spalte_ergaenzen(con, "ih_import_laeufe", "art", "VARCHAR(20)")


def _m3_kampagnen(con: Connection) -> None:
    _spalte_ergaenzen(con, "ih_kampagnen", "rhythmus", "VARCHAR(20)")
    _spalte_ergaenzen(con, "ih_kampagnen", "taetigkeit", "TEXT")
    _spalte_ergaenzen(con, "ih_kampagnen", "eigen", "BOOLEAN")


def _m4_nachtrag(con: Connection) -> None:
    _spalte_ergaenzen(con, "sb_meldungen", "nachgetragen_am", "DATETIME")
    _spalte_ergaenzen(con, "sb_meldungen", "nachgetragen_von", "VARCHAR(100)")


def _m5_sets(con: Connection) -> None:
    _spalte_ergaenzen(con, "artikel", "ist_set", "BOOLEAN")


# (Nummer, Beschreibung, Funktion) – nur anhängen, nie ändern oder entfernen
MIGRATIONEN = [
    (1, "Buchungen: Preis zum Buchungszeitpunkt und Auftragsbezug; Reservierungen: Auftragsbezug", _m1_buchungen_preis_auftrag),
    (2, "Importläufe: Art (Asset-Liste oder Instandhaltungsplan)", _m2_importart),
    (3, "Kampagnen: Rhythmus (fest oder ab letzter Durchführung), Tätigkeit, eigene Kampagnen", _m3_kampagnen),
    (4, "Schichtbuch: Nachträge (nachgetragen am/von)", _m4_nachtrag),
    (5, "Artikel: Sets aus mehreren Artikeln", _m5_sets),
]


def angewendet(con: Connection) -> set[int]:
    tabellen = {r[0] for r in con.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_version" not in tabellen:
        return set()
    return {r[0] for r in con.exec_driver_sql("SELECT version FROM schema_version")}


def anwenden(eng: Engine) -> list[int]:
    """Neue Tabellen anlegen und ausstehende Migrationen ausführen – in einer Schreibtransaktion."""
    from . import db
    from .main import VERSION
    with eng.execution_options(schreiben=True).begin() as con:
        db.md.create_all(con)
        fertig = angewendet(con)
        neu = []
        for nr, name, fn in MIGRATIONEN:
            if nr in fertig:
                continue
            fn(con)
            con.execute(db.schema_version.insert().values(version=nr, name=name, angewendet_am=datetime.now(), programmversion=VERSION))
            neu.append(nr)
    if neu:
        log.info("Datenbank-Migrationen angewendet: %s", neu)
    return neu


# ------------------------------------------------------------------ Probelauf vor dem echten Update
def kennzahlen(con) -> dict:
    """Was eine Migration nie verändern darf: Artikel, Plätze, Bestände (je Artikel und Platz), Buchungen, Benutzer."""
    def eins(sql):
        return con.execute(sql).fetchone()[0]
    h = hashlib.sha256()
    for r in con.execute("SELECT artikel_id, lagerplatz_id, round(menge, 6) FROM bestand ORDER BY artikel_id, lagerplatz_id"):
        h.update(repr(tuple(r)).encode())
    return {"artikel": eins("SELECT count(*) FROM artikel"), "lagerplaetze": eins("SELECT count(*) FROM lagerplaetze"),
            "bestand": h.hexdigest(), "buchungen": eins("SELECT count(*) FROM bewegungen"),
            "buchungen_summe": eins("SELECT round(coalesce(sum(menge), 0), 6) FROM bewegungen"),
            "benutzer": eins("SELECT count(*) FROM users"), "reservierungen": eins("SELECT count(*) FROM reservierungen")}


def _datei_ausstehend(datei: Path) -> list[int] | None:
    """Ausstehende Migrationen einer vorhandenen Lager-Datenbank; None = keine (neue/leere) Datenbank."""
    if not datei.exists() or datei.stat().st_size == 0:
        return None
    con = sqlite3.connect(str(datei), timeout=60)
    try:
        tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "artikel" not in tabellen:
            return None
        fertig = {r[0] for r in con.execute("SELECT version FROM schema_version")} if "schema_version" in tabellen else set()
    finally:
        con.close()
    return [nr for nr, _, _ in MIGRATIONEN if nr not in fertig]


def probelauf(datei: Path) -> dict:
    """Migrationen an einer Kopie ausführen und prüfen. Wirft MigrationsFehler, wenn sich Lagerdaten ändern würden."""
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "probe.db"
        src, dst = sqlite3.connect(str(datei), timeout=60), sqlite3.connect(str(kopie))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        con = sqlite3.connect(str(kopie))
        try:
            vorher = kennzahlen(con)
        finally:
            con.close()
        eng = create_engine("sqlite:///" + str(kopie).replace("\\", "/"))
        try:
            anwenden(eng)
            with eng.connect() as c:
                roh = c.connection.dbapi_connection
                nachher = kennzahlen(roh)
                pruefung = roh.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as e:
            raise MigrationsFehler(f"Probelauf der Datenbank-Aktualisierung fehlgeschlagen: {e}") from e
        finally:
            eng.dispose()
    if pruefung != "ok":
        raise MigrationsFehler(f"Probelauf: Datenbankprüfung meldet „{pruefung}“.")
    if vorher != nachher:
        abw = {k: (vorher[k], nachher[k]) for k in vorher if vorher[k] != nachher[k]}
        raise MigrationsFehler(f"Probelauf: Lagerdaten hätten sich verändert ({abw}). Update abgebrochen, nichts geändert.")
    return vorher


def vor_start(cfg) -> str | None:
    """Beim Programmstart: Stehen Migrationen an, erst Probelauf an einer Kopie, dann Sicherung des aktuellen Stands.

    Die Migration selbst führt danach ``db.init_engine`` aus. Gibt den Namen der Sicherung zurück (oder None)."""
    datei = cfg.path(cfg.daten.datenbank)
    offen = _datei_ausstehend(datei)
    if not offen:
        return None
    log.info("Datenbank-Aktualisierung steht an (Migrationen %s) – Probelauf an einer Kopie …", offen)
    kennz = probelauf(datei)
    log.info("Probelauf in Ordnung (%s Artikel, %s Buchungen unverändert).", kennz["artikel"], kennz["buchungen"])
    try:
        from .services.sicherung import einzel_sicherung
        gesichert = einzel_sicherung(cfg, cfg.path(cfg.backup.ordner), name="vor_update", aufbewahren_tage=365)
    except Exception as e:  # z. B. Sicherungslaufwerk nicht erreichbar: dann wenigstens eine Kopie neben der Datenbank
        gesichert = datei.with_name(f"vor_update_{datetime.now():%Y%m%d_%H%M%S}.db")
        src, dst = sqlite3.connect(str(datei), timeout=60), sqlite3.connect(str(gesichert))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.warning("Sicherung vor dem Update im Sicherungsordner fehlgeschlagen (%s) – Kopie liegt unter %s", e, gesichert)
    log.info("Stand vor dem Update gesichert: %s", gesichert)
    return Path(gesichert).name

