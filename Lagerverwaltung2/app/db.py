"""Eigene Datenbank (SQLite) – unabhängig von der Casper-Software."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, func,
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
    Column("ist_set", Boolean),  # ab 2.12.0: Set aus mehreren Artikeln (Inhalt in artikel_set_inhalt)
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
    Column("preis", Float),                 # Artikelpreis zum Buchungszeitpunkt (ab 2.5.0, Migration 1)
    Column("auftrag_id", Integer),          # Instandhaltungsauftrag (ab 2.5.0, Migration 1; Aufträge folgen in Phase 1)
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
    Column("auftrag_id", Integer),          # ab 2.5.0, Migration 1
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

schema_version = Table(
    "schema_version", md,  # angewendete Datenbank-Migrationen (app/migrationen.py)
    Column("version", Integer, primary_key=True),
    Column("name", String(200)),
    Column("angewendet_am", DateTime, server_default=func.current_timestamp()),
    Column("programmversion", String(20)),
)

benutzer_rollen = Table(
    "benutzer_rollen", md,  # Rolle je Modul (Lager-Rolle steht weiter in users.rolle)
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("modul", String(20), primary_key=True),  # ih
    Column("rolle", String(30), nullable=False),
)

# ------------------------------------------------------------------ Instandhaltung (CMMS)
ih_plaetze = Table(
    "ih_plaetze", md,  # technischer Platz: Bereich, Unit oder Tag-Nummer (Position in der Anlage)
    Column("id", Integer, primary_key=True),
    Column("code", String(120), nullable=False, unique=True),
    Column("schluessel", String(120), nullable=False, unique=True),  # Code ohne Leerzeichen, klein: findet Doppelte
    Column("art", String(20), nullable=False, default="platz"),       # bereich | unit | platz
    Column("eltern_id", Integer, ForeignKey("ih_plaetze.id"), index=True),
    Column("bezeichnung", String(300)),
    Column("kategorie", String(200)),
    Column("kuerzel", String(30)),
    Column("hersteller", String(200)),
    Column("modell", String(300)),
    Column("seriennummer", String(200)),
    Column("lieferant", String(200)),
    Column("bauteilklasse", String(100)),  # z. B. Absperrarmatur, Messstelle, PLTS-Sensor – bestimmt später die Wartungsintervalle
    Column("sicherheitsgerichtet", Boolean),  # PLT-Sicherheitseinrichtung (SR 4)
    Column("kritikalitaet", String(1)),   # A | B | C
    Column("status", String(30)),
    Column("inbetriebnahme", Date),
    Column("anschaffung", Date),
    Column("bestellnummer", String(100)),
    Column("leistungsnummer", String(100)),
    Column("kosten", Float),
    Column("nebenkosten", Float),
    Column("doku_url", String(1000)),
    Column("notiz", Text),
    Column("zusatz", Text),               # weitere Spalten aus dem Import (JSON: Spaltenname -> Wert)
    Column("aktiv", Boolean, nullable=False, default=True),
    Column("import_lauf_id", Integer),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("geaendert_am", DateTime, server_default=func.current_timestamp()),
)

ih_import_laeufe = Table(
    "ih_import_laeufe", md,
    Column("id", Integer, primary_key=True),
    Column("dateiname", String(300)),
    Column("zeit", DateTime, server_default=func.current_timestamp()),
    Column("benutzer", String(100)),
    Column("status", String(20), nullable=False, default="neu"),  # neu | geprueft | uebernommen
    Column("spalten", Text),       # JSON: Spaltenüberschriften
    Column("zuordnung", Text),     # JSON: Feld je Spalte
    Column("optionen", Text),      # JSON
    Column("ergebnis", Text),      # JSON: Zusammenfassung von Prüfung/Testlauf/Übernahme
    Column("pruef_kennung", String(64)),  # Zuordnung + Optionen + Datenstand der letzten erfolgreichen Prüfung
    Column("art", String(20)),     # assets (leer) | plan – ab 2.6.0, Migration 2
    Column("zeilen", Integer),
    Column("uebernommen_am", DateTime),
)

ih_import_zeilen = Table(
    "ih_import_zeilen", md,
    Column("id", Integer, primary_key=True),
    Column("lauf_id", Integer, ForeignKey("ih_import_laeufe.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("nr", Integer, nullable=False),  # Zeilennummer in der Datei
    Column("werte", Text, nullable=False),  # JSON-Liste, eine Zelle je Spalte
    Column("ergebnis", String(20)),         # neu | geaendert | unveraendert | fehler
    Column("meldungen", Text),              # JSON-Liste
    Column("aenderungen", Text),            # JSON: Feld -> [alt, neu]
)

# ------------------------------------------------------------------ Wartungsplanung (Instandhaltungsplan, ab 2.6.0)
ih_massnahmen = Table(
    "ih_massnahmen", md,  # S, W, F, B, Za, Zi, Zf, Zv, ZE, ZD, ZK, ZW, ZP
    Column("code", String(10), primary_key=True),
    Column("symbol", String(4)),
    Column("name", String(200), nullable=False),
    Column("beschreibung", Text),     # Was ist zu tun
    Column("wer", String(200)),       # Wer macht es
    Column("nachweis", String(200)),
    Column("pflicht", Boolean, nullable=False, default=False),  # gesetzliche Pflichtprüfung (extern)
    Column("reihenfolge", Integer),
)

ih_klassen_intervalle = Table(
    "ih_klassen_intervalle", md,  # Intervall je Bauteilklasse und Maßnahme – gilt für alle Bauteile der Klasse
    Column("id", Integer, primary_key=True),
    Column("schluessel", String(120), nullable=False, unique=True),  # z. B. F-PLTS-Sensor
    Column("bauteilklasse", String(100), nullable=False, index=True),
    Column("massnahme", String(10), nullable=False),
    Column("intervall_monate", Integer),  # leer = laufend (ständige Beobachtung)
    Column("grundlage", Text),
    Column("achtung", Text),
)

ih_kampagnen = Table(
    "ih_kampagnen", md,  # bündelt gleichartige Bauteile zu einem wiederkehrenden Arbeitspaket (auch Pflichtprüfungen)
    Column("id", Integer, primary_key=True),
    Column("schluessel", String(120), nullable=False, unique=True),  # GruppenID, z. B. W-Absperrarmatur, ZE
    Column("massnahme", String(10), nullable=False),
    Column("bauteilklasse", String(100)),  # „Anlage“ = ohne Bauteilliste (z. B. Ex-Prüfung der Gesamtanlage)
    Column("intervall_monate", Integer, nullable=False),
    Column("erster_termin", Date, nullable=False),
    Column("aufwand_tage", Float),
    Column("dauer_wochen", Integer),
    Column("bauteile_pro_tag", Float),
    Column("grundlage", Text),
    Column("aktiv", Boolean, nullable=False, default=True),
    Column("verantwortlich", String(200)),
    Column("gegenstand", String(300)),      # Pflichtprüfung: Gegenstand
    Column("rechtsgrundlage", Text),
    Column("durchfuehrung", String(200)),   # z. B. ZÜS / befähigte Person
    Column("nachweis", String(200)),
    Column("hinweis", Text),
    Column("vorlauf_wochen", Integer),      # so früh beauftragen/vorbereiten
    Column("geaendert_am", DateTime, server_default=func.current_timestamp()),
    Column("rhythmus", String(20)),          # fest (ab erstem Termin, Standard) | ab_erledigung (ab letzter Durchführung) – ab 2.7.0
    Column("taetigkeit", Text),              # eigene Kampagne: was genau zu tun ist – ab 2.7.0
    Column("eigen", Boolean),                # im Programm angelegt (nicht aus dem Instandhaltungsplan)
)

ih_kampagne_bauteile = Table(
    "ih_kampagne_bauteile", md,  # Kampagne für einzelne Bauteile statt für eine ganze Bauteilklasse (ab 2.7.0)
    Column("kampagne_id", Integer, ForeignKey("ih_kampagnen.id", ondelete="CASCADE"), primary_key=True),
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id", ondelete="CASCADE"), primary_key=True),
)

ih_stueckliste = Table(
    "ih_stueckliste", md,  # Ersatzteile je Bauteil: Lagerartikel <-> Tag-Nr. (n:m, ab 2.7.0)
    Column("id", Integer, primary_key=True),
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("menge", Float),                  # Stück je Bauteil (optional)
    Column("bemerkung", String(300)),
    Column("erstellt_von", String(100)),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    UniqueConstraint("platz_id", "artikel_id"),
)

ih_auftraege = Table(
    "ih_auftraege", md,  # Wartungs-/Prüfauftrag: ein Durchgang einer Kampagne zu einem Termin
    Column("id", Integer, primary_key=True),
    Column("kampagne_id", Integer, ForeignKey("ih_kampagnen.id"), index=True),
    Column("termin", Date, nullable=False),       # geplanter Start (Montag der Startwoche)
    Column("massnahme", String(10), nullable=False),
    Column("titel", String(300), nullable=False),
    Column("status", String(20), nullable=False, default="angelegt"),  # angelegt | freigegeben | in_arbeit | erledigt | abgeschlossen | storniert
    Column("verantwortlich", String(200)),
    Column("pruefer", String(200)),               # Pflichtprüfung: prüfende Stelle / Person
    Column("bemerkung", Text),
    Column("erstellt_von", String(100)),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("freigegeben_von", String(100)),
    Column("freigegeben_am", DateTime),
    Column("erledigt_am", DateTime),
    Column("abgeschlossen_von", String(100)),
    Column("abgeschlossen_am", DateTime),
    Column("storno_grund", String(300)),
    UniqueConstraint("kampagne_id", "termin"),
)
Index("ix_ih_auftraege_status", ih_auftraege.c.status)

ih_auftrag_positionen = Table(
    "ih_auftrag_positionen", md,  # ein Bauteil im Auftrag = ein Protokoll (WP-01 je Bauteil bzw. Zeile im WP-02-Sammelprotokoll)
    Column("id", Integer, primary_key=True),
    Column("auftrag_id", Integer, ForeignKey("ih_auftraege.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id"), nullable=False, index=True),
    Column("formular", String(10), nullable=False, default="WP-01"),  # WP-01 | WP-02
    Column("zustand_beginn", String(20)),    # unauffaellig | auffaellig | gestoert
    Column("zustand_text", Text),
    Column("schritte", Text),                # JSON: [{schritt, soll, ist, io, bemerkung}]
    Column("ergebnis", String(25)),          # ohne_befund | mit_befund | nicht_durchfuehrbar (leer = offen)
    Column("befund_nr", String(60)),
    Column("befund_text", Text),
    Column("abschluss", Text),               # JSON: Abschlusskontrolle (Brückungen entfernt, …)
    Column("sil", String(10)),
    Column("durchgefuehrt_von", String(100)),
    Column("durchgefuehrt_am", DateTime),
    UniqueConstraint("auftrag_id", "platz_id"),
)

ih_statuslog = Table(
    "ih_statuslog", md,
    Column("id", Integer, primary_key=True),
    Column("auftrag_id", Integer, ForeignKey("ih_auftraege.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("zeit", DateTime, nullable=False),
    Column("benutzer", String(100)),
    Column("von", String(20)),
    Column("nach", String(20)),
    Column("text", String(500)),
)

ih_dokumente = Table(
    "ih_dokumente", md,  # Nachweise (Prüfbescheinigungen, Protokolle, Fotos) zu Aufträgen; Dateien unter daten/anhaenge
    Column("id", Integer, primary_key=True),
    Column("auftrag_id", Integer, ForeignKey("ih_auftraege.id"), index=True),
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id"), index=True),
    Column("art", String(30), nullable=False, default="nachweis"),
    Column("dateiname", String(300), nullable=False),
    Column("speichername", String(300), nullable=False),
    Column("typ", String(100)),
    Column("groesse", Integer),
    Column("hochgeladen_von", String(100)),
    Column("hochgeladen_am", DateTime, server_default=func.current_timestamp()),
)

# ------------------------------------------------------------------ Schichtbuch (ab 2.8.0)
sb_teams = Table(
    "sb_teams", md,  # Schichtteams, z. B. Grün, Blau, Gelb, Rot (Anzahl einstellbar)
    Column("id", Integer, primary_key=True),
    Column("name", String(60), nullable=False, unique=True),
    Column("farbe", String(9), nullable=False, default="#5B6773"),
    Column("reihenfolge", Integer, nullable=False, default=0),
    Column("aktiv", Boolean, nullable=False, default=True),
)

sb_zeiten = Table(
    "sb_zeiten", md,  # Schichtzeiten, z. B. Tag 06:00–18:00, Nacht 18:00–06:00
    Column("id", Integer, primary_key=True),
    Column("name", String(40), nullable=False, unique=True),
    Column("beginn", String(5), nullable=False),   # HH:MM
    Column("ende", String(5), nullable=False),     # HH:MM, kleiner/gleich Beginn = am Folgetag
    Column("reihenfolge", Integer, nullable=False, default=0),
    Column("aktiv", Boolean, nullable=False, default=True),
)

sb_mitglieder = Table(
    "sb_mitglieder", md,  # Benutzer -> Schichtteam
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("team_id", Integer, ForeignKey("sb_teams.id", ondelete="CASCADE"), nullable=False, index=True),
)

sb_schichten = Table(
    "sb_schichten", md,  # eine gelaufene Schicht (Datum = Tag des Schichtbeginns)
    Column("id", Integer, primary_key=True),
    Column("datum", Date, nullable=False),
    Column("zeit_id", Integer, ForeignKey("sb_zeiten.id"), nullable=False),
    Column("team_id", Integer, ForeignKey("sb_teams.id")),
    Column("schichtfuehrer", String(200)),
    Column("begonnen_am", DateTime),
    Column("begonnen_von", String(100)),
    Column("beendet_am", DateTime),
    Column("beendet_von", String(100)),
    Column("uebergabe_notiz", Text),
    UniqueConstraint("datum", "zeit_id", name="uq_sb_schicht"),
)

sb_meldungen = Table(
    "sb_meldungen", md,  # Schichtbuch-Eintrag (Felder wie die bisherige SharePoint-Liste)
    Column("id", Integer, primary_key=True),
    Column("schicht_id", Integer, ForeignKey("sb_schichten.id"), index=True),
    Column("titel", String(200), nullable=False),
    Column("ereignistyp", String(60)),
    Column("beschreibung", Text),
    Column("massnahme", Text),
    Column("status", String(20), nullable=False, default="offen"),      # offen | in_arbeit | erledigt
    Column("prioritaet", String(10), nullable=False, default="mittel"), # hoch | mittel | niedrig
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id", ondelete="SET NULL"), index=True),
    Column("asset", String(120)),                 # Tag-Nr. (Momentaufnahme oder Freitext)
    Column("functional_location", String(200)),
    Column("work_order", String(60)),
    Column("auftrag_id", Integer, ForeignKey("ih_auftraege.id", ondelete="SET NULL")),
    Column("sicherheitsrelevant", Boolean, nullable=False, default=False),
    Column("stillstand", Boolean, nullable=False, default=False),
    Column("stillstand_h", Float),
    Column("uebergabe", Boolean, nullable=False, default=False),   # an die nächste Schicht übergeben (noch nicht übernommen)
    Column("uebergabe_text", Text),
    Column("uebergeben_schicht_id", Integer),
    Column("uebernommen_am", DateTime),
    Column("uebernommen_von", String(100)),
    Column("uebernommen_schicht_id", Integer),
    Column("erledigt_am", DateTime),
    Column("erledigt_von", String(100)),
    Column("erledigt_schicht_id", Integer),
    Column("erstellt_am", DateTime, nullable=False),   # Zeitpunkt des Ereignisses (bei Nachträgen der nachgetragene Zeitpunkt)
    Column("erstellt_von", String(100)),
    Column("geaendert_am", DateTime),
    Column("geaendert_von", String(100)),
    Column("nachgetragen_am", DateTime),               # ab 2.9.0: Nachtrag (z. B. vom Papierformular nach Systemausfall)
    Column("nachgetragen_von", String(100)),
)

sb_verlauf = Table(
    "sb_verlauf", md,  # Ergänzungen, Statuswechsel, Übergaben und Übernahmen je Meldung
    Column("id", Integer, primary_key=True),
    Column("meldung_id", Integer, ForeignKey("sb_meldungen.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("schicht_id", Integer),
    Column("zeit", DateTime, nullable=False),
    Column("benutzer", String(100)),
    Column("art", String(20), nullable=False),    # angelegt | ergaenzung | status | uebergabe | uebernahme | geaendert
    Column("text", Text),
    Column("status", String(20)),
)

# ------------------------------------------------------------------ Sets (ab 2.12.0)
artikel_set_inhalt = Table(
    "artikel_set_inhalt", md,  # Inhalt eines Sets: jedes Teil mit eigener Artikelnummer und Menge je Set
    Column("id", Integer, primary_key=True),
    Column("set_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("teil_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("menge", Float, nullable=False, default=1),
    Column("reihenfolge", Integer, nullable=False, default=0),
    UniqueConstraint("set_id", "teil_id"),
)

set_fehlteile = Table(
    "set_fehlteile", md,  # einzeln aus einem Set entnommene Teile: das Set ist unvollständig, bis erledigt
    Column("id", Integer, primary_key=True),
    Column("set_id", Integer, ForeignKey("artikel.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("teil_id", Integer, ForeignKey("artikel.id", ondelete="SET NULL")),
    Column("teil_nr", String(60), nullable=False),          # Momentaufnahme (bleibt lesbar, auch wenn das Teil gelöscht wird)
    Column("teil_bezeichnung", String(300)),
    Column("menge", Float, nullable=False),
    Column("lagerplatz", String(60)),                        # wo das unvollständige Set liegt
    Column("empfaenger", String(200)),
    Column("zweck", String(300)),
    Column("entnommen_am", DateTime, nullable=False),
    Column("entnommen_von", String(100)),
    Column("erledigt_am", DateTime),
    Column("erledigt_von", String(100)),
    Column("erledigt_art", String(20)),                      # nachgelegt | aus_lager | set_entnommen | kein_bestand
)

# ------------------------------------------------------------------ Montageunterstützung (ab 2.12.0)
mt_stutzen = Table(
    "mt_stutzen", md,  # Stutzenübersicht: Soll-Werte je Stutzen/Flansch
    Column("id", Integer, primary_key=True),
    Column("gruppe", String(100)),                 # z. B. Reaktor, WHRU Stutzen, Verlängerung 1, Torch
    Column("kuerzel", String(40), nullable=False), # Stutzen, z. B. RL 1, RO, WR
    Column("bezeichnung", String(200)),            # z. B. Laser-Stutzen
    Column("anlage", String(200)),                 # Vorschlag für „Anlage / Reaktor“ im Protokoll
    Column("platz_id", Integer, ForeignKey("ih_plaetze.id", ondelete="SET NULL")),
    Column("schrauben_anzahl", Integer),
    Column("gewinde", String(40)),                 # Größe / Gewinde, z. B. M20
    Column("schraube_typ", String(100)),           # Typ / Norm
    Column("schraube_laenge", String(40)),         # Länge-Soll [mm] (Text: auch „265?“)
    Column("schraube_werkstoff", String(100)),     # Werkstoff / Klasse
    Column("drehmoment", String(40)),              # Soll [Nm] (Text: auch Spannen wie „35-47“)
    Column("schmiermittel", String(200)),
    Column("bemerkung", Text),
    Column("reihenfolge", Integer, nullable=False, default=0),
    Column("aktiv", Boolean, nullable=False, default=True),
    Column("erstellt_am", DateTime, server_default=func.current_timestamp()),
    Column("erstellt_von", String(100)),
    Column("geaendert_am", DateTime),
    Column("geaendert_von", String(100)),
)

mt_stutzen_dichtungen = Table(
    "mt_stutzen_dichtungen", md,  # bis zu 3 Dichtungen je Stutzen (Dichtung 1–3 im Protokoll)
    Column("id", Integer, primary_key=True),
    Column("stutzen_id", Integer, ForeignKey("mt_stutzen.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("pos", Integer, nullable=False),
    Column("einbauort", String(100)),
    Column("dichtungsart", String(100)),           # z. B. MCR, KPD, VOR, Dichtscheibe
    Column("durchmesser", String(60)),             # z. B. Ø110MM, DN40, 1 Zoll
    Column("artikel_nr", String(200)),             # Bezeichnung/Bestellnummer der Dichtung (Spalte „Auftragsnummer“)
    Column("artikel_id", Integer, ForeignKey("artikel.id", ondelete="SET NULL")),  # Lagerartikel (optional)
    Column("nenndicke", Float),                    # Nenn-/Neudicke [mm]
    Column("menge", Float),
)

mt_protokolle = Table(
    "mt_protokolle", md,  # Montageprotokoll Reaktorstutzen / Dichtungen / Schrauben
    Column("id", Integer, primary_key=True),
    Column("nummer", String(30), nullable=False, unique=True),     # MP-2026-0001
    Column("status", String(20), nullable=False, default="entwurf"),  # entwurf | abgeschlossen
    Column("stutzen_id", Integer, ForeignKey("mt_stutzen.id", ondelete="SET NULL"), index=True),
    Column("stutzen", String(40)),                 # Kürzel (Momentaufnahme)
    Column("stutzen_bez", String(300)),
    Column("anlage", String(200)),
    Column("datum", Date),
    Column("monteur", String(200)),
    Column("pruefer", String(200)),
    Column("arbeitsauftrag", String(200)),
    Column("reinigung", String(300)),
    Column("schmiermittel", String(200)),
    Column("schrauben_anzahl", Integer),
    Column("dichtungen", Text),                    # JSON: Liste mit 3 Einträgen
    Column("schrauben", Text),                     # JSON: Liste je Schraubenposition (Pos. = Reihenfolge des Anziehens)
    Column("reihenfolge", Text),                   # JSON: Loch-Nummer (1..n, im Uhrzeigersinn ab oben) je Pos.
    Column("bemerkung_dichtungen", Text),
    Column("bemerkungen", Text),
    Column("montage_abgeschlossen", String(10)),   # ja | nein
    Column("lecktest", String(10)),                # bestanden | offen | nb
    Column("abschluss_zeit", String(40)),          # Feld „Datum / Uhrzeit“
    Column("erstellt_am", DateTime, nullable=False),
    Column("erstellt_von", String(100)),
    Column("geaendert_am", DateTime),
    Column("geaendert_von", String(100)),
    Column("abgeschlossen_am", DateTime),
    Column("abgeschlossen_von", String(100)),
)

mt_verlauf = Table(
    "mt_verlauf", md,  # Wer hat wann was am Protokoll gemacht (Änderungen an abgeschlossenen Protokollen mit Alt → Neu)
    Column("id", Integer, primary_key=True),
    Column("protokoll_id", Integer, ForeignKey("mt_protokolle.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("zeit", DateTime, nullable=False),
    Column("benutzer", String(100)),
    Column("art", String(20), nullable=False),     # angelegt | gespeichert | abgeschlossen | korrigiert | geoeffnet
    Column("grund", Text),
    Column("aenderungen", Text),                   # JSON: [[Feld, alt, neu], ...]
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

    from .migrationen import anwenden
    anwenden(eng)  # neue Tabellen anlegen, ausstehende Migrationen ausführen (eine Transaktion)
    _engine = eng
    return eng


def engine() -> Engine:
    assert _engine is not None, "Datenbank nicht initialisiert"
    return _engine


def schreiben():
    """Schreibtransaktion: ``with db.schreiben() as con: ...``"""
    return engine().execution_options(schreiben=True).begin()
