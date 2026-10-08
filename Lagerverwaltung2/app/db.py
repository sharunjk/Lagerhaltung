"""Eigene Datenbank (SQLite) – unabhängig von der Casper-Software."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, func, text,
)
from sqlalchemy.engine import Engine

md = MetaData()

users = Table(
    "users", md,
    Column("id", Integer, primary_key=True),
    Column("username", String(100), nullable=False, unique=True),
    Column("anzeigename", String(200)),
    Column("pw_hash", String(300)),
    Column("rolle", String(20), nullable=False, default="lager"),  # admin | lager | lesen
    Column("aktiv", Boolean, nullable=False, default=True),
    Column("api_token", String(100), unique=True),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("letzter_login", DateTime),
)

lieferanten = Table(
    "lieferanten", md,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False, unique=True),
    Column("ansprechpartner", String(200)),
    Column("email", String(200)),
    Column("telefon", String(100)),
    Column("kundennummer", String(100)),
    Column("webseite", String(300)),
    Column("notiz", Text),
)

lagerplaetze = Table(
    "lagerplaetze", md,
    Column("id", Integer, primary_key=True),
    Column("code", String(60), nullable=False, unique=True),
    Column("bereich", String(60)),
    Column("beschreibung", String(300)),
    Column("aktiv", Boolean, nullable=False, default=True),
)

artikel = Table(
    "artikel", md,
    Column("id", Integer, primary_key=True),
    Column("nummer", String(60), nullable=False, unique=True),
    Column("bezeichnung", String(300), nullable=False),
    Column("typ", String(200)),            # Typenbezeichnung
    Column("kategorie", String(100)),      # Gruppe
    Column("hersteller", String(200)),
    Column("hersteller_nr", String(200)),
    Column("lieferant_id", Integer, ForeignKey("lieferanten.id", ondelete="SET NULL")),
    Column("lieferant_artnr", String(200)),
    Column("preis", Float),
    Column("einheit", String(20), nullable=False, default="Stk"),
    Column("meldebestand", Float),
    Column("mindestbestand", Float),
    Column("bestellmenge", Float),
    Column("kritisch", Boolean, nullable=False, default=False),
    Column("verwendung", Text),            # Anlage / Equipment / Tag-Nummer
    Column("notiz", Text),
    Column("aktiv", Boolean, nullable=False, default=True),  # archivierte Artikel bleiben für die Historie erhalten
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("geaendert_am", DateTime, server_default=func.current_timestamp()),
)

bestand = Table(
    "bestand", md,
    Column("id", Integer, primary_key=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False),
    Column("lagerplatz_id", Integer, ForeignKey("lagerplaetze.id"), nullable=False),
    Column("menge", Float, nullable=False, default=0),
    UniqueConstraint("artikel_id", "lagerplatz_id"),
)

bewegungen = Table(
    "bewegungen", md,
    Column("id", Integer, primary_key=True),
    Column("zeit", DateTime, nullable=False, index=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="SET NULL"), index=True),
    Column("artikel_nr", String(60)),       # Momentaufnahme (auch für gelöschte Artikel aus Altdaten)
    Column("lagerplatz_id", Integer, ForeignKey("lagerplaetze.id")),
    Column("lagerplatz", String(60)),       # Momentaufnahme Code
    Column("typ", String(20), nullable=False),  # eingang|ausgang|umbuchung|inventur|anlage|ausleihe|rueckgabe|info
    Column("menge", Float, nullable=False, default=0),  # vorzeichenbehaftet
    Column("bestand_nachher", Float),       # Bestand am Platz nach der Buchung
    Column("benutzer", String(100)),
    Column("empfaenger", String(200)),
    Column("kostenstelle", String(100)),
    Column("zweck", String(300)),
    Column("text", String(300)),            # Klartext (z. B. aus Altsystem)
    Column("bestellung_id", Integer),
    Column("bezug_id", Integer),            # Rückgabe -> Ausleihe, Umbuchung-Gegenzeile
    Column("rueckgabe_bis", Date),
    Column("storno_von", Integer),
    Column("storniert_durch", Integer),
    Column("quelle", String(20)),           # pc | mobil | api | import
)
Index("ix_bew_typ", bewegungen.c.typ)

reservierungen = Table(
    "reservierungen", md,
    Column("id", Integer, primary_key=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False),
    Column("menge", Float, nullable=False),
    Column("fuer", String(300), nullable=False),    # Auftrag / Zweck
    Column("person", String(200)),
    Column("bis", Date),
    Column("status", String(20), nullable=False, default="offen"),  # offen | entnommen | storniert
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("erstellt_von", String(100)),
)

bestellungen = Table(
    "bestellungen", md,
    Column("id", Integer, primary_key=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False),
    Column("menge", Float, nullable=False),
    Column("geliefert", Float, nullable=False, default=0),
    Column("lieferant_id", Integer, ForeignKey("lieferanten.id", ondelete="SET NULL")),
    Column("status", String(20), nullable=False, default="offen"),  # offen | bestellt | teilgeliefert | geliefert | storniert
    Column("bestellnummer", String(100)),
    Column("notiz", String(500)),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("erstellt_von", String(100)),
    Column("bestellt_am", DateTime),
    Column("geliefert_am", DateTime),
)

inventuren = Table(
    "inventuren", md,
    Column("id", Integer, primary_key=True),
    Column("name", String(200), nullable=False),
    Column("bereich", String(60)),
    Column("status", String(20), nullable=False, default="offen"),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("erstellt_von", String(100)),
    Column("abgeschlossen_am", DateTime),
)

inventur_pos = Table(
    "inventur_pos", md,
    Column("id", Integer, primary_key=True),
    Column("inventur_id", Integer, ForeignKey("inventuren.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False),
    Column("lagerplatz_id", Integer, ForeignKey("lagerplaetze.id"), nullable=False),
    Column("soll", Float),
    Column("ist", Float),
    Column("gezaehlt_von", String(100)),
    Column("gezaehlt_am", DateTime),
)

anhaenge = Table(
    "anhaenge", md,
    Column("id", Integer, primary_key=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("dateiname", String(300), nullable=False),
    Column("speichername", String(300), nullable=False),
    Column("typ", String(100)),
    Column("groesse", Integer),
    Column("ist_bild", Boolean, default=False),
    Column("hochgeladen_am", DateTime, server_default=func.current_timestamp()),
    Column("hochgeladen_von", String(100)),
)

audit = Table(
    "audit", md,
    Column("id", Integer, primary_key=True),
    Column("zeit", DateTime, server_default=func.current_timestamp(), index=True),
    Column("benutzer", String(100)),
    Column("aktion", String(100)),
    Column("objekt", String(255)),
    Column("details", Text),
)

sync_log = Table(
    "sync_log", md,  # Offline erfasste Buchungen vom Handheld: verhindert doppelte Übertragung
    Column("uuid", String(64), primary_key=True),
    Column("benutzer", String(100)),
    Column("erfasst_am", String(40)),
    Column("uebertragen_am", DateTime, server_default=func.current_timestamp()),
    Column("meldung", String(300)),
)

settings = Table(
    "settings", md,
    Column("schluessel", String(100), primary_key=True),
    Column("wert", Text),
)

_engine: Engine | None = None


def init_engine(url: str) -> Engine:
    global _engine
    if url.startswith("sqlite:///"):
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15}, future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_con, _rec):
        dbapi_con.isolation_level = None  # Transaktionen steuern wir selbst
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @event.listens_for(eng, "begin")
    def _begin(conn):
        # Schreibtransaktionen holen die Sperre sofort: parallele Buchungen (PC + Handscanner) laufen sauber nacheinander.
        # Reine Lesezugriffe blockieren niemanden (WAL-Modus).
        conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get("schreiben") else "BEGIN")

    md.create_all(eng)
    _engine = eng
    return eng


def engine() -> Engine:
    assert _engine is not None, "Datenbank nicht initialisiert"
    return _engine


def schreiben():
    """Schreibtransaktion: ``with db.schreiben() as con: ...``"""
    return engine().execution_options(schreiben=True).begin()
