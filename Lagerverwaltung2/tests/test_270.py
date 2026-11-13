"""2.7.0: Rhythmus der Kampagnen, eigene Kampagnen für einzelne Bauteile, Ersatzteile fest einer Tag-Nr. zuordnen,
Entnahme von Ersatzteilen für einen Auftrag. Alle Daten sind erfunden."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from sqlalchemy import insert, select

from test_cmms_phase0 import IH_ROUTEN, cmms_an, ih_benutzer
from test_pruefung import L, anzahl, client, schreib
from test_wartung_260 import MO, _anlagen, _kid, _plan_uebernehmen


def _als(cfg, name):
    c = client(cfg)
    assert c.post("/login", data={"username": name, "passwort": "Lager-Test-2026"}).status_code == 303
    return c


# ------------------------------------------------------------------ Rhythmus: fest oder ab letzter Durchführung
def test_startpunkt_und_termine():
    from app.services import wartung as w
    k = {"erster_termin": date(2026, 1, 5), "intervall_monate": 3}
    assert w.startpunkt(k) == date(2026, 1, 5)
    # fest: eine spätere Durchführung verschiebt nichts
    assert w.startpunkt({**k, "rhythmus": "fest", "basis": date(2026, 2, 18)}) == date(2026, 1, 5)
    # ab Durchführung: Intervall ab Datum „erledigt“, auf den Montag der Woche
    assert w.startpunkt({**k, "rhythmus": "ab_erledigung", "basis": date(2026, 2, 18)}) == date(2026, 5, 18)
    assert w.termine({**k, "rhythmus": "ab_erledigung", "basis": date(2026, 2, 18)}, date(2026, 12, 31)) == [
        date(2026, 5, 18), date(2026, 8, 18), date(2026, 11, 18)]
    # noch nie durchgeführt -> wie fest; nie vor dem ersten Termin
    assert w.startpunkt({**k, "rhythmus": "ab_erledigung"}) == date(2026, 1, 5)
    assert w.startpunkt({**k, "erster_termin": date(2027, 1, 4), "rhythmus": "ab_erledigung", "basis": date(2026, 2, 18)}) == date(2027, 1, 4)


def test_rhythmus_ab_erledigung_verschiebt_naechsten_termin(env):
    from app.db import ih_auftraege
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    admin = client(cfg, "admin")
    _plan_uebernehmen(admin)
    kid = _kid(eng, "S-Pumpe")  # erster Termin = diese Woche, alle 3 Monate
    werte = {"intervall_monate": "3", "erster_termin": str(MO - timedelta(weeks=20)), "dauer_wochen": "1", "aufwand_tage": "1",
             "vorlauf_wochen": "", "verantwortlich": "Meister", "aktiv": "on", "rhythmus": "ab_erledigung"}
    r = admin.post(f"/ih/wartung/kampagne/{kid}/bearbeiten", data=werte, follow_redirects=True)
    assert "Kampagne gespeichert" in r.text and "Rhythmus und Tätigkeit bleiben" in r.text
    assert anzahl(eng, f"SELECT rhythmus FROM ih_kampagnen WHERE id={kid}") == "ab_erledigung"
    # Durchführung vor 5 Wochen abgeschlossen -> nächster Termin = Montag der Woche 3 Monate danach (nicht das alte Raster)
    erledigt = datetime.combine(MO - timedelta(weeks=5) + timedelta(days=2), datetime.min.time())
    with schreib(eng) as con:
        con.execute(insert(ih_auftraege).values(kampagne_id=kid, termin=MO - timedelta(weeks=8), massnahme="S", titel="alt", status="abgeschlossen",
                                                erstellt_von="t", erstellt_am=erledigt, erledigt_am=erledigt, abgeschlossen_am=erledigt))
    from app.services import wartung as w
    with eng.connect() as con:
        k = next(x for x in w.lage(con) if x["id"] == kid)
    erwartet = w.montag(w.plus_monate(erledigt.date(), 3))
    assert k["basis"] == erledigt.date() and k["naechster"] == erwartet and k["lage"] in ("geplant", "bald")
    seite = admin.get(f"/ih/wartung/kampagne/{kid}").text
    assert "ab der letzten Durchführung" in seite and erledigt.strftime("%d.%m.%Y") in seite
    # Auftrag nur für einen echten Termin des neuen Rhythmus
    r = admin.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": str(MO - timedelta(weeks=20))}, follow_redirects=True)
    assert "kein Termin dieser Kampagne" in r.text
    admin.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": str(erwartet)})
    assert anzahl(eng, f"SELECT count(*) FROM ih_auftraege WHERE kampagne_id={kid} AND termin='{erwartet}'") == 1
    # zurück auf fest: Raster ab erstem Termin, ein Planimport behält den Rhythmus
    _plan_uebernehmen(admin)
    assert anzahl(eng, f"SELECT rhythmus FROM ih_kampagnen WHERE id={kid}") == "ab_erledigung"
    admin.post(f"/ih/wartung/kampagne/{kid}/bearbeiten", data={**werte, "rhythmus": "fest"})
    assert anzahl(eng, f"SELECT rhythmus FROM ih_kampagnen WHERE id={kid}") == "fest"


# ------------------------------------------------------------------ Eigene Kampagnen
def test_eigene_kampagne_fuer_einzelne_bauteile(env):
    from app.db import ih_auftrag_positionen, ih_auftraege
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    ih_benutzer(eng, "ing", "ingenieur")
    ih_benutzer(eng, "tech", "techniker")
    ing, tech = _als(cfg, "ing"), _als(cfg, "tech")
    # ohne übernommenen Instandhaltungsplan: S, W, F stehen trotzdem zur Wahl
    form = ing.get("/ih/wartung/kampagne/neu?platz=8").text
    assert "Wartung (W)" in form and "VV 1040 01" in form and "ab der letzten Durchführung" in form
    assert tech.get("/ih/wartung/kampagne/neu").status_code == 403
    # Pflichtangaben
    r = ing.post("/ih/wartung/kampagne/neu", data={"massnahme": "W", "ziel": "bauteile", "erster_termin": str(MO), "intervall_monate": "6"})
    assert r.status_code == 200 and "mindestens ein Bauteil" in r.text and "was zu tun ist" in r.text
    r = ing.post("/ih/wartung/kampagne/neu", data={"massnahme": "W", "ziel": "bauteile", "tag": ["VV 1040 01", "XX 9999"], "taetigkeit": "Abschmieren",
                                                   "erster_termin": str(MO), "intervall_monate": "6"})
    assert "XX 9999" in r.text and anzahl(eng, "SELECT count(*) FROM ih_kampagnen") == 0
    # anlegen: zwei Bauteile, Tätigkeit, Hinweis, Rhythmus
    r = ing.post("/ih/wartung/kampagne/neu", data={
        "massnahme": "W", "ziel": "bauteile", "tag": ["VV 1040 01", "B -10401 – Bauteil B -10401"], "taetigkeit": "Spindel fetten, Stopfbuchse nachziehen",
        "hinweis": "Nur drucklos", "erster_termin": str(MO), "intervall_monate": "6", "dauer_wochen": "1", "aufwand_tage": "0,5",
        "rhythmus": "ab_erledigung", "durchfuehrung": "Instandhaltung"}, follow_redirects=True)
    assert "Kampagne E-W-VV 1040 01 angelegt" in r.text and "VV 1040 01 + 1 weitere" in r.text
    kid = _kid(eng, "E-W-VV 1040 01")
    k = anzahl(eng, f"SELECT eigen || '|' || rhythmus || '|' || taetigkeit FROM ih_kampagnen WHERE id={kid}")
    assert k == "1|ab_erledigung|Spindel fetten, Stopfbuchse nachziehen"
    seite = ing.get(f"/ih/wartung/kampagne/{kid}").text
    assert "Spindel fetten" in seite and "einzeln zugeordnet" in seite and "Bauteile (2)" in seite
    assert "eigene" in ing.get("/ih/wartung").text
    # Bauteil-Seite zeigt die eigene Wartung
    assert "Spindel fetten" in ing.get("/ih/anlagen/8").text
    # Bauteile ändern: hinzufügen, entfernen, das letzte bleibt
    ing.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"tag": "P -10401 A"})
    assert anzahl(eng, f"SELECT count(*) FROM ih_kampagne_bauteile WHERE kampagne_id={kid}") == 3
    assert tech.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"entfernen": "2"}).status_code == 403
    ing.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"entfernen": "2"})
    ing.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"entfernen": "6"})
    r = ing.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"entfernen": "8"}, follow_redirects=True)
    assert "letzte Bauteil bleibt" in r.text
    assert anzahl(eng, f"SELECT group_concat(platz_id) FROM ih_kampagne_bauteile WHERE kampagne_id={kid}") == "8"
    ing.post(f"/ih/wartung/kampagne/{kid}/bauteile", data={"tag": "B -10401"})
    # Auftrag: genau die zugeordneten Bauteile, Tätigkeit und Hinweis stehen drin
    ing.post("/ih/wartung/auftraege-anlegen")
    with eng.connect() as con:
        aid = con.execute(select(ih_auftraege.c.id).where(ih_auftraege.c.kampagne_id == kid)).scalar()
        pos = sorted(r[0] for r in con.execute(select(ih_auftrag_positionen.c.platz_id).where(ih_auftrag_positionen.c.auftrag_id == aid)))
    assert pos == [6, 8]
    seite = tech.get(f"/ih/auftraege/{aid}").text
    assert "Spindel fetten" in seite and "Nur drucklos" in seite
    # Kampagne für eine ganze Klasse und für die Anlage ohne Bauteilliste
    ing.post("/ih/wartung/kampagne/neu", data={"massnahme": "F", "ziel": "klasse", "bauteilklasse": "Pumpe", "taetigkeit": "Probelauf",
                                               "erster_termin": str(MO + timedelta(weeks=30)), "intervall_monate": "12"})
    ing.post("/ih/wartung/kampagne/neu", data={"massnahme": "S", "ziel": "anlage", "gegenstand": "Druckluftstation", "taetigkeit": "Rundgang",
                                               "erster_termin": str(MO + timedelta(weeks=30)), "intervall_monate": "1"})
    assert anzahl(eng, "SELECT bauteilklasse FROM ih_kampagnen WHERE schluessel='E-F-Pumpe'") == "Pumpe"
    assert anzahl(eng, "SELECT bauteilklasse FROM ih_kampagnen WHERE schluessel='E-S-Druckluftstation'") == "Anlage"
    # ein späterer Planimport lässt eigene Kampagnen stehen
    admin = client(cfg, "admin")
    _plan_uebernehmen(admin)
    assert anzahl(eng, "SELECT count(*) FROM ih_kampagnen WHERE eigen") == 3


# ------------------------------------------------------------------ Ersatzteile: feste Zuordnung zur Tag-Nr.
def _artikel(eng):
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "4711", "bezeichnung": "Gleitringdichtung", "preis": 80.0, "verwendung": "P-10401 A und P -10401B"}, "C1-R1-1", 5)
        L(con).artikel_anlegen({"nummer": "4712", "bezeichnung": "Spindel", "preis": 10.0, "verwendung": "VV 1040 01"}, "C1-R2-1", 2)
        L(con).artikel_anlegen({"nummer": "4713", "bezeichnung": "Schraube", "verwendung": "VV 1040 011 (andere)"}, "C1-R2-2", 100)


def test_artikel_formular_tag_nr_zuordnen(env):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    _artikel(eng)
    c = client(cfg, "lager")
    form = c.get("/artikel/4711/bearbeiten").text
    assert "Ersatzteil für Tag-Nr." in form and 'value="P -10401 A – Bauteil P -10401 A"' in form
    basis = {"nummer": "4711", "bezeichnung": "Gleitringdichtung", "einheit": "Stk", "tags_bearbeitet": "1"}
    r = c.post("/artikel/4711/bearbeiten", data={**basis, "tag": ["P -10401 A", "p-10401 b – Bauteil"]}, follow_redirects=True)
    assert r.status_code == 200
    assert anzahl(eng, "SELECT group_concat(platz_id) FROM (SELECT platz_id FROM ih_stueckliste ORDER BY platz_id)") == "2,3"
    detail = c.get("/artikel/4711").text
    assert "Ersatzteil für Tag-Nr." in detail and "P -10401 B" in detail
    # unbekannte Tag-Nr. -> Fehler, nichts geändert
    r = c.post("/artikel/4711/bearbeiten", data={**basis, "tag": ["P -10401 A", "ZZ 1"]}, follow_redirects=True)
    assert "ZZ 1" in r.text and anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 2
    # Formular ohne Abschnitt (z. B. CMMS aus) lässt Zuordnungen unberührt
    c.post("/artikel/4711/bearbeiten", data={"nummer": "4711", "bezeichnung": "Gleitringdichtung", "einheit": "Stk"})
    assert anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 2
    # eine entfernen
    c.post("/artikel/4711/bearbeiten", data={**basis, "tag": ["P -10401 B"]})
    assert anzahl(eng, "SELECT group_concat(platz_id) FROM ih_stueckliste") == "3"
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Ersatzteil-Zuordnung geändert'") >= 2
    # neuer Artikel gleich mit Tag-Nr.
    c.post("/artikel/neu", data={"nummer": "4720", "bezeichnung": "Lager", "einheit": "Stk", "tags_bearbeitet": "1", "tag": "VV 1040 01"})
    assert anzahl(eng, "SELECT p.code FROM ih_stueckliste s JOIN artikel a ON a.id=s.artikel_id JOIN ih_plaetze p ON p.id=s.platz_id "
                       "WHERE a.nummer='4720'") == "VV 1040 01"
    # CMMS aus: Abschnitt fehlt
    cfg.cmms.aktiv = False
    assert "Ersatzteil für Tag-Nr." not in c.get("/artikel/4711/bearbeiten").text


def test_anlage_ersatzteile_und_vorschlaege(env):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    _artikel(eng)
    ih_benutzer(eng, "tech", "techniker")
    admin = client(cfg, "admin")
    seite = admin.get("/ih/anlagen/8").text
    assert "Noch keine Ersatzteile zugeordnet" in seite and "Vorschlag aus dem Feld" in seite and "4712" in seite
    # 4713 nennt „VV 1040 011“ -> darf nicht als VV 1040 01 erkannt werden
    from app.services import wartung as w
    with eng.connect() as con:
        v = {x["nummer"]: [t["code"] for t in x["tags"]] for x in w.vorschlaege_aus_verwendung(con)}
    assert v == {"4711": ["P -10401 A", "P -10401 B"], "4712": ["VV 1040 01"]}
    # an der Anlage zuordnen (auch „Nummer – Bezeichnung“ aus der Auswahlliste) und lösen
    admin.post("/ih/anlagen/8/ersatzteile", data={"artikel_nr": "4712 – Spindel", "menge": "1", "bemerkung": "Satz"})
    admin.post("/ih/anlagen/8/ersatzteile", data={"artikel_nr": "4712"})  # doppelt -> nichts
    assert anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 1
    seite = admin.get("/ih/anlagen/8").text.split("<datalist")[0]
    assert "Gleitring" not in seite and "Spindel" in seite and "C1-R2-1 (2)" in seite and "1 je Tausch" in seite
    r = admin.post("/ih/anlagen/8/ersatzteile", data={"artikel_nr": "9999"}, follow_redirects=True)
    assert "Artikel nicht gefunden: 9999" in r.text
    tech = _als(cfg, "tech")
    assert tech.post("/ih/anlagen/8/ersatzteile", data={"artikel_nr": "4711"}).status_code == 403
    assert "Zuordnen" not in tech.get("/ih/anlagen/8").text.split("Ersatzteile im Lager")[1].split("</section>")[0]
    sid = anzahl(eng, "SELECT id FROM ih_stueckliste")
    admin.post("/ih/anlagen/8/ersatzteile", data={"loesen": str(sid)})
    assert anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 0
    # Assistent: alle Vorschläge, Auswahl übernehmen
    seite = admin.get("/ih/ersatzteile/vorschlaege").text
    assert "2 Artikel" in seite and "3 Vorschläge" in seite
    admin.post("/ih/ersatzteile/vorschlaege", data={"paar": ["1:2", "1:3", "2:8", "abc", "1:2"]})
    assert anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 3
    assert "Keine offenen Vorschläge" in admin.get("/ih/ersatzteile/vorschlaege").text
    assert anzahl(eng, "SELECT verwendung FROM artikel WHERE nummer='4712'") == "VV 1040 01"  # Freitext bleibt


# ------------------------------------------------------------------ Entnahme für einen Auftrag
def test_entnahme_fuer_auftrag(env):
    from app.db import ih_auftraege
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    _artikel(eng)
    for name, rolle in (("tech", "techniker"), ("ing", "ingenieur"), ("op", "operator")):
        ih_benutzer(eng, name, rolle)
    admin = client(cfg, "admin")
    _plan_uebernehmen(admin)
    admin.post("/ih/ersatzteile/vorschlaege", data={"paar": ["1:2", "1:3"]})
    with schreib(eng) as con:
        con.execute(__import__("app.db", fromlist=["x"]).ih_stueckliste.update().values(menge=1))
    ing, tech, op = _als(cfg, "ing"), _als(cfg, "tech"), _als(cfg, "op")
    ing.post("/ih/wartung/auftraege-anlegen")
    with eng.connect() as con:
        s = con.execute(select(ih_auftraege.c.id).where(ih_auftraege.c.massnahme == "S")).scalar()
    seite = tech.get(f"/ih/auftraege/{s}").text
    assert "4711" in seite and "P -10401 A</span>, <span class=\"whitespace-nowrap\">P -10401 B" in seite and "C1-R1-1: 5" in seite
    # vor der Freigabe keine Entnahme
    r = tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "2"}, follow_redirects=True)
    assert "nur bei freigegebenen" in r.text and anzahl(eng, "SELECT sum(menge) FROM bestand") == 107
    ing.post(f"/ih/auftraege/{s}/status", data={"aktion": "freigeben"})
    assert op.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "1"}).status_code == 403
    r = tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "2"}, follow_redirects=True)
    assert "Entnommen: 2 × 4711 von C1-R1-1 (Bestand dort jetzt 3)" in r.text
    # zu viel -> Fehler, Bestand bleibt
    r = tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "9"}, follow_redirects=True)
    assert "liegen nur 3" in r.text
    # ein Artikel außerhalb der Stückliste
    tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4712", "platz": "C1-R2-1", "menge": "1"})
    with eng.connect() as con:
        bew = con.exec_driver_sql(f"SELECT artikel_nr, menge, preis, empfaenger, quelle, benutzer FROM bewegungen WHERE auftrag_id={s} ORDER BY id").all()
    assert [tuple(b) for b in bew] == [("4711", -2.0, 80.0, f"Auftrag A-{s:05d}", "ih", "tech"), ("4712", -1.0, 10.0, f"Auftrag A-{s:05d}", "ih", "tech")]
    seite = tech.get(f"/ih/auftraege/{s}").text
    assert "Material bisher 170,00" in seite and "zusätzlich" in seite
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Entnahme für Auftrag'") == 2


# ------------------------------------------------------------------ Rechte und Migration
NEUE_ROUTEN = [("get", "/ih/wartung/kampagne/neu", "ih.wartung.planen"), ("post", "/ih/wartung/kampagne/neu", "ih.wartung.planen"),
               ("post", "/ih/wartung/kampagne/1/bauteile", "ih.wartung.planen"), ("post", "/ih/anlagen/1/ersatzteile", "ih.anlagen.pflegen"),
               ("get", "/ih/ersatzteile/vorschlaege", "ih.anlagen.pflegen"), ("post", "/ih/ersatzteile/vorschlaege", "ih.anlagen.pflegen"),
               ("post", "/ih/auftraege/1/entnahme", "ih.auftrag.ausfuehren")]


def test_rechte_neue_routen(env):
    from app.rechte import IH_ROLLEN, RECHTE
    cfg, eng = env
    cmms_an(cfg)
    with schreib(eng) as con:
        from app.db import ih_plaetze
        con.execute(insert(ih_plaetze).values(id=1, code="P -10401 A", schluessel="p-10401a", art="platz", aktiv=True))
    for r in IH_ROLLEN:
        ih_benutzer(eng, f"ih_{r}", r)
    for r in IH_ROLLEN:
        c = _als(cfg, f"ih_{r}")
        for methode, pfad, recht in NEUE_ROUTEN:
            status = getattr(c, methode)(pfad).status_code
            assert (status != 403) == (r in RECHTE[recht]), (r, pfad, status)
    assert not {p for _, p, _ in NEUE_ROUTEN} & {p for _, p, _ in IH_ROUTEN}


def test_migration_3_von_2_6(env):
    """Datenbank im Stand 2.6.0 (Migrationen 1 und 2): Spalten und Tabellen kommen dazu, Bestand bleibt."""
    from app import db, migrationen
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Kugelhahn"}, "C1", 4)
    db.engine().dispose()
    pfad = cfg.path(cfg.daten.datenbank)
    con = sqlite3.connect(str(pfad))
    con.execute("DELETE FROM schema_version WHERE version=3")
    for s in ("rhythmus", "taetigkeit", "eigen"):
        con.execute(f"ALTER TABLE ih_kampagnen DROP COLUMN {s}")
    con.execute("DROP TABLE ih_stueckliste")
    con.execute("DROP TABLE ih_kampagne_bauteile")
    con.commit()
    con.close()
    migrationen.vor_start(cfg)
    eng2 = db.init_engine(cfg.db_url)
    with eng2.connect() as c2:
        assert [r[0] for r in c2.exec_driver_sql("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5]
        spalten = {r[1] for r in c2.exec_driver_sql("PRAGMA table_info(ih_kampagnen)")}
        tabellen = {r[0] for r in c2.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        assert c2.exec_driver_sql("SELECT sum(menge) FROM bestand").scalar() == 4
    assert {"rhythmus", "taetigkeit", "eigen"} <= spalten and {"ih_stueckliste", "ih_kampagne_bauteile"} <= tabellen
    assert list(cfg.path(cfg.backup.ordner).glob("vor_update_*.zip"))
