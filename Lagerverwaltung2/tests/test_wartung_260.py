"""2.6.0: Wartungsplanung nach dem Instandhaltungsplan, Aufträge mit Protokollen, Anlagen von Hand, genaue Filter.

Der Instandhaltungsplan ist erfunden und bildet nur den Aufbau der echten Datei nach (Blätter und Spalten).
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import anzahl, client, schreib

HEUTE = date.today()
MO = HEUTE - timedelta(days=HEUTE.weekday())


def _plan_xlsx(erster: dict | None = None, intervall_s_pumpe: int = 3) -> bytes:
    from openpyxl import Workbook
    erster = erster or {}
    wb = Workbook()
    wb.active.title = "Anleitung"
    wb.active.append(["Thema", "Erläuterung"])
    wb.active.append(["Was ist das?", "Testplan"])
    m = wb.create_sheet("Maßnahmen")
    m.append(["Symbol", "Code", "Maßnahme", "Was ist zu tun", "Wer macht es", "Nachweis"])
    m.append(["●", "S", "Sichtprüfung", "Äußerlich erkennbare Mängel feststellen.", "Instandhaltung", "Wartungsprotokoll"])
    m.append(["▲", "W", "Wartung", "Nach Wartungsanweisung.", "Instandhaltung", "Wartungsprotokoll"])
    m.append(["■", "F", "Funktionsprüfung", "Funktion im Anforderungsfall nachweisen.", "Instandhaltung / Fachfirma", "Prüfprotokoll"])
    m.append(["◆", "Za", "Äußere Prüfung Druckgerät", "Äußere Prüfung durch ZÜS.", "ZÜS / befähigte Person", "Prüfbescheinigung"])
    m.append(["○", "B", "Ständige Beobachtung", "Prozessgrößen beobachten.", "Betrieb / Schicht", "Schichtbuch"])
    i = wb.create_sheet("Intervalle je Klasse")
    i.append(["ID", "Art", "Maßnahme", "Bauteilklasse", "Intervall", "Einheit", "Bauteile", "Grundlage", "Achtung"])
    i.append(["S-Pumpe", "S", "Sichtprüfung", "Pumpe", intervall_s_pumpe, "Monate", 2, "Betriebspraxis - Leckage", None])
    i.append(["W-Pumpe", "W", "Wartung", "Pumpe", 12, "Monate", 2, "Herstellerpraxis", "Nur freigegebene Schmierstoffe."])
    i.append(["B-Pumpe", "B", "Ständige Beobachtung", "Pumpe", "laufend", None, 2, "Schichtbetrieb", None])
    i.append(["F-PLTS-Sensor", "F", "Funktionsprüfung", "PLTS-Sensor", 12, "Monate", 1, "SR 4 Kap. 7.1.3", "Überbrückung nur mit Beiblatt 4."])
    i.append(["Za-Behälter", "Za", "Äußere Prüfung Druckgerät", "Behälter", 2, "Jahre", 1, "BetrSichV", None])
    k = wb.create_sheet("Kampagnen")
    k.append(["GruppenID", "Art", "Maßnahme", "Bauteilklasse", "Intervall (Monate)", "Erster Termin", "Bauteile", "Aufwand (Tage)",
              "Dauer (Wochen)", "Bauteile/Tag", "Grundlage", "Aktiv", "Verantwortlich"])
    k.append(["S-Pumpe", "S", "Sichtprüfung", "Pumpe", intervall_s_pumpe, erster.get("S-Pumpe", datetime.combine(MO, datetime.min.time())),
              2, 1, 1, 20, "Betriebspraxis", "Ja", "Meister"])
    k.append(["W-Pumpe", "W", "Wartung", "Pumpe", 12, erster.get("W-Pumpe", datetime.combine(MO + timedelta(weeks=10), datetime.min.time())),
              2, 4, 2, 3, "Herstellerpraxis", "Ja", None])
    k.append(["F-PLTS-Sensor", "F", "Funktionsprüfung", "PLTS-Sensor", 12, erster.get("F-PLTS-Sensor", datetime.combine(MO, datetime.min.time())),
              1, 2, 1, 3, "SR 4", "Ja", None])
    k.append(["Za-Behälter", "Za", "Äußere Prüfung Druckgerät", "Behälter", 24, erster.get("Za-Behälter", datetime.combine(MO + timedelta(weeks=8), datetime.min.time())),
              1, 1, 1, 4, "BetrSichV", "Ja", None])
    k.append(["ZE", "ZE", "Prüfung Ex-Anlage", "Anlage", 36, datetime.combine(MO - timedelta(weeks=10), datetime.min.time()), 1, 5, 2, 0.2,
              "BetrSichV § 15", "Ja", None])
    p = wb.create_sheet("Pflichtprüfungen")
    p.append(["ID", "Prüfung", "Gegenstand", "Intervall (Monate)", "Rechtsgrundlage", "Durchführung", "Nachweis", "Hinweis"])
    p.append(["ZE", "Wiederkehrende Prüfung der Anlage in explosionsgefährdeten Bereichen", "Ex-Anlage", 36, "BetrSichV § 15 Abs. 15",
              "ZÜS oder befähigte Person", "Prüfbescheinigung", "Zonenplan ist Voraussetzung."])
    p.append(["Za-Behälter", "Äußere Prüfung Druckgerät", "1 x Behälter", 24, "BetrSichV Anh. 2", "ZÜS / befähigte Person", "Prüfbescheinigung", None])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _anlagen(eng):
    from app.db import ih_plaetze
    rows = [("1040", "unit", None, None, None, None), ("P -10401 A", "platz", "Pumpe", False, "P", 1),
            ("P -10401 B", "platz", "Pumpe", False, "P", 1), ("P -10402 A", "platz", "Pumpe", False, "P", 1),
            ("TIZ 1040 01-01", "platz", "PLTS-Sensor", True, "TIZ", 1), ("B -10401", "platz", "Behälter", False, "B", 1),
            ("CAP01-13030", "platz", None, None, "CAP01", None), ("VV 1040 01", "platz", "Absperrarmatur", False, "VV", 1)]
    with schreib(eng) as con:
        for i, (code, art, klasse, sicher, kuerzel, eltern) in enumerate(rows, start=1):
            con.execute(insert(ih_plaetze).values(id=i, code=code, schluessel=code.replace(" ", "").lower(), art=art, bauteilklasse=klasse,
                                                  sicherheitsgerichtet=sicher, kuerzel=kuerzel, eltern_id=eltern, aktiv=True,
                                                  bezeichnung=f"Bauteil {code}"))
        con.execute(ih_plaetze.update().where(ih_plaetze.c.code == "P -10402 A").values(aktiv=False))  # archiviert


def _plan_uebernehmen(c, daten=None) -> int:
    r = c.post("/ih/wartung/import", files={"datei": ("Instandhaltungsplan_Test.xlsx", daten or _plan_xlsx())})
    assert r.status_code == 303, r.text[:400]
    lid = int(r.headers["location"].rsplit("/", 1)[1])
    r = c.post(f"/ih/wartung/import/{lid}/uebernehmen", data={"bestaetigt": "ja"}, follow_redirects=True)
    assert "Instandhaltungsplan übernommen" in r.text
    return lid


def _kid(eng, schluessel):
    from app.db import ih_kampagnen
    with eng.connect() as con:
        return con.execute(select(ih_kampagnen.c.id).where(ih_kampagnen.c.schluessel == schluessel)).scalar()


# ------------------------------------------------------------------ Plan übernehmen und Fälligkeiten
def test_plan_uebernehmen_vergleich_und_erneut(env):
    from app.db import ih_kampagnen, ih_klassen_intervalle, ih_massnahmen
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, "admin")
    r = c.post("/ih/wartung/import", files={"datei": ("plan.xlsx", _plan_xlsx())})
    seite = c.get(r.headers["location"]).text
    assert "5 neu" in seite and "Zonenplan" not in seite  # Vergleich vor Übernahme
    assert anzahl(eng, "SELECT count(*) FROM ih_kampagnen") == 0
    c.post(r.headers["location"] + "/uebernehmen", data={"bestaetigt": "ja"})
    assert list((cfg.path(cfg.backup.ordner)).glob("vor_import_*.zip"))
    with eng.connect() as con:
        mass = {m["code"]: m for m in con.execute(select(ih_massnahmen)).mappings()}
        kamp = {k["schluessel"]: k for k in con.execute(select(ih_kampagnen)).mappings()}
        inter = {k["schluessel"]: k for k in con.execute(select(ih_klassen_intervalle)).mappings()}
    assert set(mass) == {"S", "W", "F", "Za", "B", "ZE"} and mass["ZE"]["pflicht"] and not mass["S"]["pflicht"]  # ZE aus „Pflichtprüfungen“
    assert kamp["ZE"]["durchfuehrung"] == "ZÜS oder befähigte Person" and kamp["ZE"]["hinweis"] == "Zonenplan ist Voraussetzung."
    assert kamp["S-Pumpe"]["erster_termin"] == MO and kamp["S-Pumpe"]["verantwortlich"] == "Meister"
    assert inter["B-Pumpe"]["intervall_monate"] is None and inter["Za-Behälter"]["intervall_monate"] == 24  # „laufend“, Jahre -> Monate
    # zweite Fassung: Intervall geändert -> wird als Änderung gezeigt und übernommen, nichts gelöscht
    r = c.post("/ih/wartung/import", files={"datei": ("plan_v2.xlsx", _plan_xlsx(intervall_s_pumpe=6))})
    seite = c.get(r.headers["location"]).text
    assert "intervall_monate" in seite and "1 geändert" in seite
    c.post(r.headers["location"] + "/uebernehmen", data={"bestaetigt": "ja"})
    assert anzahl(eng, "SELECT intervall_monate FROM ih_kampagnen WHERE schluessel='S-Pumpe'") == 6
    assert anzahl(eng, "SELECT count(*) FROM ih_kampagnen") == 5
    # Planläufe erscheinen nicht beim Asset-Import und lassen sich dort nicht öffnen
    assert "plan_v2.xlsx" not in c.get("/ih/import").text and "plan_v2.xlsx" in c.get("/ih/wartung/import").text
    plan_lid = int(r.headers["location"].rsplit("/", 1)[1])
    assert c.get(f"/ih/import/{plan_lid}").headers["location"] == "/ih/import"
    assert c.post(f"/ih/import/{plan_lid}/verwerfen").status_code == 303 and anzahl(eng, f"SELECT count(*) FROM ih_import_laeufe WHERE id={plan_lid}") == 1
    # falsche Datei
    r = c.post("/ih/wartung/import", files={"datei": ("x.xlsx", b"PK kaputt")}, follow_redirects=True)
    assert "nicht als Excel-Datei lesen" in r.text


def test_termine_und_lage():
    from app.services import wartung as w
    assert w.plus_monate(date(2027, 1, 31), 1) == date(2027, 2, 28) and w.plus_monate(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert w.plus_monate(date(2026, 11, 2), 24) == date(2028, 11, 2)
    k = {"erster_termin": date(2026, 11, 2), "intervall_monate": 3}
    assert w.termine(k, date(2027, 6, 1)) == [date(2026, 11, 2), date(2027, 2, 2), date(2027, 5, 2)]
    assert w.kw(date(2026, 11, 2)) == "KW 45/2026"
    assert w.formular("S", False) == "WP-02" and w.formular("S", True) == "WP-01" and w.formular("W", False) == "WP-01"
    assert w.formular("Za", False) == "Z"
    assert w.vorlauf({"massnahme": "Zi"}) == 26 and w.vorlauf({"massnahme": "ZE"}) == 12 and w.vorlauf({"massnahme": "S"}) == 2
    assert w.vorlauf({"massnahme": "S", "vorlauf_wochen": 5}) == 5
    last = w.wochenlast([{"aktiv": True, "aufwand_tage": 4, "dauer_wochen": 2, "erster_termin": date(2026, 11, 2), "intervall_monate": 12,
                          "massnahme": "W"}], [date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)])
    assert last == {date(2026, 11, 2): 2.0, date(2026, 11, 9): 2.0, date(2026, 11, 16): 0.0}


def test_wartungsplan_kalender_wochenliste(env):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    c = client(cfg, "admin")
    _plan_uebernehmen(c)
    seite = c.get("/ih/wartung").text
    assert "Sichtprüfung" in seite and "überfällig" in seite and "läuft jetzt" in seite  # ZE vor 10 Wochen: überfällig
    from app.services import wartung as w
    with eng.connect() as con:
        lage = {k["schluessel"]: k for k in w.lage(con)}
    assert lage["ZE"]["lage"] == "ueberfaellig" and lage["S-Pumpe"]["lage"] == "laeuft" and lage["Za-Behälter"]["lage"] == "bald"
    assert lage["W-Pumpe"]["lage"] == "geplant" and lage["S-Pumpe"]["bauteile"] == 2  # archivierte Pumpe zählt nicht
    assert "Pflichtprüfung" in c.get("/ih/wartung?art=pflicht").text
    kal = c.get("/ih/wartung/kalender?wochen=52").text
    assert "Techniker-Tage je Woche" in kal and "Pumpe" in kal and "PLTS-Sensor" in kal
    wl = c.get("/ih/wartung/wochen").text
    assert "KW" in wl and "Start" in wl
    assert "Überfällig (1)" in c.get("/ih").text


# ------------------------------------------------------------------ Aufträge und Protokolle
def test_auftrag_ablauf_mit_protokollen_und_vier_augen(env):
    from app.db import ih_auftrag_positionen
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    for name, rolle in (("tech", "techniker"), ("ing", "ingenieur"), ("ing2", "ingenieur"), ("op", "operator")):
        ih_benutzer(eng, name, rolle)
    admin = client(cfg, "admin")
    _plan_uebernehmen(admin)

    def als(name):
        c = client(cfg)
        c.post("/login", data={"username": name, "passwort": "Lager-Test-2026"})
        return c
    tech, ing, ing2, op = als("tech"), als("ing"), als("ing2"), als("op")
    # Aufträge anlegen: nur Planer; „fällige anlegen“ legt S-Pumpe, F-PLTS-Sensor, Za-Behälter, ZE an (W-Pumpe noch nicht im Vorlauf)
    assert tech.post("/ih/wartung/auftraege-anlegen").status_code == 403
    ing.post("/ih/wartung/auftraege-anlegen")
    assert anzahl(eng, "SELECT count(*) FROM ih_auftraege") == 4
    ing.post("/ih/wartung/auftraege-anlegen")
    assert anzahl(eng, "SELECT count(*) FROM ih_auftraege") == 4  # keine Doppelten
    with eng.connect() as con:
        auftr = {r.massnahme: r.id for r in con.execute(select(__import__("app.db", fromlist=["x"]).ih_auftraege))}
        pos = con.execute(select(ih_auftrag_positionen.c.platz_id, ih_auftrag_positionen.c.formular)
                          .where(ih_auftrag_positionen.c.auftrag_id == auftr["S"])).all()
    assert sorted(pos) == [(2, "WP-02"), (3, "WP-02")]  # zwei aktive Pumpen, Sichtprüfung ohne Sicherheitsfunktion -> Sammelprotokoll
    s, f, z = auftr["S"], auftr["F"], auftr["Za"]
    # vor Freigabe kein Protokoll; Techniker darf nicht freigeben
    r = tech.post(f"/ih/auftraege/{s}/sammel", data={"p1_ergebnis": "ohne_befund"}, follow_redirects=True)
    assert anzahl(eng, f"SELECT count(ergebnis) FROM ih_auftrag_positionen WHERE auftrag_id={s}") == 0
    assert tech.post(f"/ih/auftraege/{s}/status", data={"aktion": "freigeben"}).status_code == 403
    ing.post(f"/ih/auftraege/{s}/status", data={"aktion": "freigeben"})
    # Sammelprotokoll WP-02: Befund braucht Text; Operator darf nicht
    pids = {p: i for i, p in con_execute(eng, f"SELECT id, platz_id FROM ih_auftrag_positionen WHERE auftrag_id={s}")}
    assert op.post(f"/ih/auftraege/{s}/sammel", data={}).status_code == 403
    r = tech.post(f"/ih/auftraege/{s}/sammel", data={f"p{pids[2]}_ergebnis": "ohne_befund", f"p{pids[3]}_ergebnis": "mit_befund"},
                  follow_redirects=True)
    assert "1 Bauteile gespeichert" in r.text and "Befundmeldung-Nr. oder eine Beschreibung" in r.text
    assert "Noch 1 Bauteile ohne Protokoll" in tech.post(f"/ih/auftraege/{s}/status", data={"aktion": "erledigt"}, follow_redirects=True).text
    tech.post(f"/ih/auftraege/{s}/sammel", data={f"p{pids[3]}_ergebnis": "mit_befund", f"p{pids[3]}_befund_text": "Leckage Gleitring",
                                                 f"p{pids[3]}_befund_nr": "BM-17"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={s}") == "in_arbeit"
    tech.post(f"/ih/auftraege/{s}/status", data={"aktion": "erledigt"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={s}") == "erledigt"
    assert tech.post(f"/ih/auftraege/{s}/status", data={"aktion": "abschliessen"}).status_code == 403
    ing.post(f"/ih/auftraege/{s}/status", data={"aktion": "abschliessen"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={s}") == "abgeschlossen"
    # Historie und letzter Termin an der Anlage
    seite = admin.get("/ih/anlagen/3").text
    assert "Historie" in seite and "Leckage Gleitring" in seite and "Wartung und Prüfungen" in seite
    # WP-01 an PLT-Sicherheitseinrichtung: Zustand, Abschlusskontrolle Pflicht, Vier-Augen-Prinzip
    ing.post(f"/ih/auftraege/{f}/status", data={"aktion": "freigeben"})
    pid = con_execute(eng, f"SELECT id FROM ih_auftrag_positionen WHERE auftrag_id={f}")[0][0]
    form = tech.get(f"/ih/auftraege/{f}/position/{pid}").text
    assert "Zustand bei Beginn" in form and "Überbrückung nur mit Beiblatt 4" in form and "PLT-Sicherheitseinrichtung" in form
    r = tech.post(f"/ih/auftraege/{f}/position/{pid}", data={"ergebnis": "ohne_befund", "zustand_beginn": "unauffaellig"}, follow_redirects=True)
    assert "Abschlusskontrolle vollständig bestätigen" in r.text
    r = tech.post(f"/ih/auftraege/{f}/position/{pid}", data={"ergebnis": "ohne_befund"}, follow_redirects=True)
    assert "Zustand bei Beginn" in r.text and "SR 4 verlangt" in r.text
    daten = {"ergebnis": "ohne_befund", "zustand_beginn": "unauffaellig", "sil": "2", "schritt": ["Grenzwert anfahren", ""],
             "soll": ["120 °C ± 2", ""], "ist": ["119,5 °C", ""], "io": ["ja", ""], "bemerkung": ["", ""],
             **{f"ab_{k}": "on" for k in ("brueckung", "kennzeichnung", "grenzwerte", "betrieb")}}
    ing.post(f"/ih/auftraege/{f}/position/{pid}", data=daten)  # der Ingenieur prüft selbst …
    with eng.connect() as con:
        p = con.execute(select(ih_auftrag_positionen).where(ih_auftrag_positionen.c.id == pid)).mappings().one()
    assert json.loads(p["schritte"]) == [{"schritt": "Grenzwert anfahren", "soll": "120 °C ± 2", "ist": "119,5 °C", "io": "ja", "bemerkung": ""}]
    assert p["durchgefuehrt_von"] == "ing" and p["sil"] == "2"
    ing.post(f"/ih/auftraege/{f}/status", data={"aktion": "erledigt"})
    r = ing.post(f"/ih/auftraege/{f}/status", data={"aktion": "abschliessen"}, follow_redirects=True)
    assert "Vier-Augen-Prinzip" in r.text and anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={f}") == "erledigt"
    r = ing2.post(f"/ih/auftraege/{f}/status", data={"aktion": "zurueckweisen", "text": ""}, follow_redirects=True)
    assert "Grund" in r.text
    ing2.post(f"/ih/auftraege/{f}/status", data={"aktion": "zurueckweisen", "text": "Messwert dokumentieren"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={f}") == "in_arbeit"
    ing.post(f"/ih/auftraege/{f}/status", data={"aktion": "erledigt"})
    ing2.post(f"/ih/auftraege/{f}/status", data={"aktion": "abschliessen"})
    assert anzahl(eng, f"SELECT abgeschlossen_von FROM ih_auftraege WHERE id={f}") == "ing2"
    assert anzahl(eng, f"SELECT count(*) FROM ih_statuslog WHERE auftrag_id={f}") == 7
    # Pflichtprüfung: ohne Nachweis kein „erledigt“; Nachweis hochladen und ansehen
    ing.post(f"/ih/auftraege/{z}/status", data={"aktion": "freigeben"})
    zp = con_execute(eng, f"SELECT id FROM ih_auftrag_positionen WHERE auftrag_id={z}")[0][0]
    tech.post(f"/ih/auftraege/{z}/sammel", data={f"p{zp}_ergebnis": "ohne_befund"})
    assert "Nachweis" in tech.post(f"/ih/auftraege/{z}/status", data={"aktion": "erledigt"}, follow_redirects=True).text
    tech.post(f"/ih/auftraege/{z}/dokument", files=[("datei", ("Pruefbescheinigung.pdf", b"%PDF-1.4 test", "application/pdf")),
                                                    ("datei", ("bericht.html", b"<script>x</script>", "text/html"))])
    did = con_execute(eng, f"SELECT id FROM ih_dokumente WHERE auftrag_id={z} ORDER BY id")
    d1 = op.get(f"/ih/dokumente/{did[0][0]}")
    assert d1.status_code == 200 and "inline" in d1.headers["content-disposition"]
    d2 = op.get(f"/ih/dokumente/{did[1][0]}")
    assert "attachment" in d2.headers["content-disposition"] and d2.headers["content-type"] == "application/octet-stream"
    tech.post(f"/ih/auftraege/{z}/status", data={"aktion": "erledigt"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={z}") == "erledigt"
    # stornieren: nur Planer, mit Grund, nur vor Arbeitsbeginn
    ze = auftr["ZE"]
    assert "Grund" in ing.post(f"/ih/auftraege/{ze}/status", data={"aktion": "stornieren"}, follow_redirects=True).text
    ing.post(f"/ih/auftraege/{ze}/status", data={"aktion": "stornieren", "text": "Zonenplan fehlt noch"})
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={ze}") == "storniert"
    assert "Storniert" in op.get("/ih/auftraege?status=storniert").text
    assert op.get(f"/ih/auftraege/{s}").status_code == 200  # Operator darf ansehen


def con_execute(eng, sql):
    with eng.connect() as con:
        return con.exec_driver_sql(sql).all()


def test_auftrag_von_hand_und_kampagne_bearbeiten(env):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    c = client(cfg, "admin")
    _plan_uebernehmen(c)
    kid = _kid(eng, "W-Pumpe")
    seite = c.get(f"/ih/wartung/kampagne/{kid}").text
    assert "Nur freigegebene Schmierstoffe" in seite and "P -10401 A" in seite and "P -10402 A" not in seite  # archiviert
    termin = MO + timedelta(weeks=10)
    r = c.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": termin.isoformat()})
    assert r.headers["location"].startswith("/ih/auftraege/")
    r = c.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": termin.isoformat()}, follow_redirects=True)
    assert "schon einen Auftrag" in r.text
    r = c.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": (termin + timedelta(days=1)).isoformat()}, follow_redirects=True)
    assert "kein Termin dieser Kampagne" in r.text
    c.post(f"/ih/wartung/kampagne/{kid}/bearbeiten", data={"intervall_monate": "6", "erster_termin": termin.isoformat(), "dauer_wochen": "3",
                                                         "aufwand_tage": "4,5", "vorlauf_wochen": "", "verantwortlich": "Team B", "aktiv": "on"})
    assert con_execute(eng, f"SELECT intervall_monate, dauer_wochen, aufwand_tage, verantwortlich FROM ih_kampagnen WHERE id={kid}")[0] == \
        (6, 3, 4.5, "Team B")
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Kampagne geändert'") == 1
    ih_benutzer(eng, "tech", "techniker")
    t = client(cfg)
    t.post("/login", data={"username": "tech", "passwort": "Lager-Test-2026"})
    assert t.post(f"/ih/wartung/kampagne/{kid}/bearbeiten", data={}).status_code == 403
    assert t.get("/ih/wartung/import").status_code == 403


# ------------------------------------------------------------------ Anlagen: von Hand, archivieren, Filter
def test_anlage_von_hand_anlegen_und_archivieren(env):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    c = client(cfg, "admin")
    assert "Neue Anlage" in c.get("/ih/anlagen").text
    r = c.post("/ih/anlagen/neu", data={"code": "  P -10403   A ", "art": "platz", "bezeichnung": "Reservepumpe", "eltern_id": "1",
                                        "bauteilklasse": "Pumpe", "sicherheitsgerichtet": "nein"})
    neu = int(r.headers["location"].rsplit("/", 1)[1])
    assert con_execute(eng, f"SELECT code, eltern_id, bauteilklasse FROM ih_plaetze WHERE id={neu}")[0] == ("P -10403 A", 1, "Pumpe")
    r = c.post("/ih/anlagen/neu", data={"code": "p-10403a", "art": "platz"}, follow_redirects=True)
    assert "gibt es schon: P -10403 A" in r.text
    assert "Bitte eine Tag-Nr." in c.post("/ih/anlagen/neu", data={"code": " "}, follow_redirects=True).text
    assert 'href="/ih/anlagen/neu?eltern=1"' in c.get("/ih/anlagen/1").text  # „Bauteil hier anlegen“ an der Unit
    # Unit mit aktiven Bauteilen lässt sich nicht archivieren; Bauteil schon – und es fällt aus Kampagnen heraus
    assert "noch aktive Anlagen" in c.post("/ih/anlagen/1/archivieren", follow_redirects=True).text
    c.post(f"/ih/anlagen/{neu}/archivieren")
    assert con_execute(eng, f"SELECT aktiv FROM ih_plaetze WHERE id={neu}")[0][0] == 0
    assert ">P -10403 A</a>" not in c.get("/ih/anlagen").text and ">P -10403 A</a>" in c.get("/ih/anlagen?archiv=1").text
    c.post(f"/ih/anlagen/{neu}/archivieren")
    assert con_execute(eng, f"SELECT aktiv FROM ih_plaetze WHERE id={neu}")[0][0] == 1
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion IN ('Anlage angelegt', 'Anlage archiviert', 'Anlage reaktiviert')") == 3
    ih_benutzer(eng, "tech", "techniker")
    t = client(cfg)
    t.post("/login", data={"username": "tech", "passwort": "Lager-Test-2026"})
    assert t.post("/ih/anlagen/neu", data={"code": "X"}).status_code == 403 and t.post(f"/ih/anlagen/{neu}/archivieren").status_code == 403


@pytest.mark.parametrize("bed,erwartet", [
    ([("kuerzel", "ist_nicht", "cap01")], {"P -10401 A", "P -10401 B", "TIZ 1040 01-01", "B -10401", "VV 1040 01"}),
    ([("code", "beginnt", "p -")], {"P -10401 A", "P -10401 B"}),
    ([("code", "nicht_beginnt", "P"), ("bauteilklasse", "nicht_leer", "")], {"TIZ 1040 01-01", "B -10401", "VV 1040 01"}),
    ([("bauteilklasse", "leer", "")], {"CAP01-13030"}),
    ([("bezeichnung", "enthaelt", "10401")], {"P -10401 A", "P -10401 B", "B -10401"}),
    ([("bezeichnung", "nicht_enthaelt", "10401"), ("kuerzel", "ist", "TIZ")], {"TIZ 1040 01-01"}),
    ([("unit", "ist", "1040")], {"P -10401 A", "P -10401 B", "TIZ 1040 01-01", "B -10401", "VV 1040 01"}),
    ([("code", "enthaelt", "%")], set()),  # Platzhalterzeichen werden wörtlich gesucht
])
def test_genaue_filter(env, bed, erwartet):
    import re
    from urllib.parse import urlencode
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    c = client(cfg, "admin")
    q = urlencode([x for f, o, v in bed for x in (("bf", f), ("bo", o), ("bv", v))])
    seite = c.get(f"/ih/anlagen?{q}").text
    gefunden = set(re.findall(r'class="font-semibold hover:underline" href="/ih/anlagen/\d+">([^<]+)</a>', seite))
    assert gefunden == erwartet
    # Excel-Export zeigt genau dieselbe Auswahl
    from openpyxl import load_workbook
    x = c.get(f"/ih/anlagen/export.xlsx?{q}")
    ws = load_workbook(io.BytesIO(x.content)).active
    assert {r[0].value for r in ws.iter_rows(min_row=2)} == erwartet


def test_migration_2_von_2_5(env):
    """2.5.0-Datenbank: ih_import_laeufe ohne Spalte „art“ -> Migration 2 ergänzt sie (mit Probelauf und Sicherung)."""
    from app import db, migrationen
    cfg, eng = env
    eng.dispose()
    datei = cfg.path(cfg.daten.datenbank)
    con = sqlite3.connect(str(datei))
    con.execute("ALTER TABLE ih_import_laeufe DROP COLUMN art")
    con.execute("DELETE FROM schema_version WHERE version = 2")
    con.commit()
    con.close()
    assert migrationen._datei_ausstehend(datei) == [2]
    assert migrationen.vor_start(cfg).startswith("vor_update_")
    db.init_engine(cfg.db_url)
    con = sqlite3.connect(str(datei))
    assert "art" in {r[1] for r in con.execute("PRAGMA table_info(ih_import_laeufe)")}
    con.close()
