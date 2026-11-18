"""2.13.0: Schichtbuch (Fehler „Schicht nach Ende falsch zugeordnet“, Vertretung/Übernahme, EX-Handys mit PIN hinter Passwort,
Aufgaben), Montageprotokoll (Lage der Dichtung i/m/ä), Meine Einstellungen (Startseite, Vorgaben je Rolle). Alle Daten erfunden."""
from __future__ import annotations

import io
import json
from datetime import date, timedelta

from sqlalchemy import text

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import anzahl, client, schreib
from test_schichtbuch_280 import _Uhr, _als


def _team_id(eng, name):
    return anzahl(eng, "SELECT id FROM sb_teams WHERE name=:n", n=name)


def _grund(cfg, eng):
    cmms_an(cfg)
    for name, rolle in (("robert", "schichtfuehrer"), ("roberto", "schichtfuehrer"), ("op", "operator"), ("le", "lesen"), ("mgr", "manager")):
        ih_benutzer(eng, name, rolle)
    admin = client(cfg, "admin")
    admin.get("/ih/schichtbuch")  # Teams und Zeiten anlegen (Tag 06–18, Nacht 18–06)
    return admin


# ------------------------------------------------------------------ Fehlerfall aus dem Betrieb
def test_uebergabe_nach_schichtende_landet_in_der_alten_schicht(env, monkeypatch):
    cfg, eng = env
    _grund(cfg, eng)
    uhr = _Uhr(monkeypatch)
    robert, roberto = _als(cfg, "robert"), _als(cfg, "roberto")
    uhr.stelle(2026, 11, 17, 17, 55)
    robert.post("/ih/schichtbuch/beginnen", data={"naechste": "1", "team_id": _team_id(eng, "Grün"), "schichtfuehrer": "Robert"})
    nacht = anzahl(eng, "SELECT id FROM sb_schichten")
    # 06:03 – Nachtschicht ist planmäßig vorbei, aber noch nicht übergeben: Eintrag gehört noch zur Nacht
    uhr.stelle(2026, 11, 18, 6, 3)
    robert.post("/ih/schichtbuch/neu", data={"titel": "Pumpe nachgestellt"})
    assert anzahl(eng, "SELECT schicht_id FROM sb_meldungen") == nacht
    seite = roberto.get("/ih/schichtbuch").text
    assert "Übergabe steht noch aus" in seite and "Schicht Tag 18.11.2026 beginnen" in seite
    # „Schicht beenden“ ohne Angabe beendet die Nacht – und legt keine Tagschicht mit Team Grün an
    assert "Nacht 17.11.–18.11.2026" in robert.get("/ih/schichtbuch/beenden").text
    robert.post("/ih/schichtbuch/beenden", data={"schicht_id": nacht, "notiz": "alles ruhig"})
    assert anzahl(eng, "SELECT count(*) FROM sb_schichten") == 1 and anzahl(eng, "SELECT beendet_von FROM sb_schichten") == "robert"
    # Roberto beginnt die Tagschicht mit seinem Team
    seite = roberto.get("/ih/schichtbuch").text
    assert "Schicht noch nicht begonnen" in seite
    roberto.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Blau"), "schichtfuehrer": "Roberto"})
    with eng.connect() as con:
        tag = con.execute(text("SELECT s.*, t.name AS team FROM sb_schichten s JOIN sb_teams t ON t.id=s.team_id WHERE s.id != :n"), {"n": nacht}).mappings().first()
    assert (tag["team"], tag["schichtfuehrer"], tag["begonnen_von"]) == ("Blau", "Roberto", "roberto")


def test_naechste_schicht_beginnt_waehrend_alte_noch_nicht_uebergeben(env, monkeypatch):
    cfg, eng = env
    _grund(cfg, eng)
    uhr = _Uhr(monkeypatch)
    robert, roberto = _als(cfg, "robert"), _als(cfg, "roberto")
    uhr.stelle(2026, 11, 17, 18, 2)
    robert.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün"), "schichtfuehrer": "Robert"})
    nacht = anzahl(eng, "SELECT id FROM sb_schichten")
    uhr.stelle(2026, 11, 18, 6, 5)
    roberto.post("/ih/schichtbuch/beginnen", data={"naechste": "1", "team_id": _team_id(eng, "Blau"), "schichtfuehrer": "Roberto"})
    tag = anzahl(eng, "SELECT id FROM sb_schichten WHERE id != :n", n=nacht)
    assert anzahl(eng, "SELECT begonnen_von FROM sb_schichten WHERE id=:t", t=tag) == "roberto"
    roberto.post("/ih/schichtbuch/neu", data={"titel": "Rundgang"})
    assert anzahl(eng, "SELECT schicht_id FROM sb_meldungen") == tag
    seite = robert.get("/ih/schichtbuch").text
    assert "Übergabe nachholen" in seite and "Schicht läuft" in seite
    robert.post("/ih/schichtbuch/beenden", data={"schicht_id": nacht})
    assert anzahl(eng, "SELECT beendet_von FROM sb_schichten WHERE id=:n", n=nacht) == "robert"
    assert anzahl(eng, "SELECT beendet_am FROM sb_schichten WHERE id=:t", t=tag) is None


def test_vertretung_und_schicht_uebernehmen(env, monkeypatch):
    cfg, eng = env
    _grund(cfg, eng)
    uhr = _Uhr(monkeypatch)
    robert, roberto = _als(cfg, "robert"), _als(cfg, "roberto")
    uhr.stelle(2026, 11, 18, 6, 5)
    robert.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün"), "schichtfuehrer": "Robert", "vertretung": "on",
                                                  "vertretung_fuer": "Max Muster"})
    assert anzahl(eng, "SELECT vertretung_fuer FROM sb_schichten") == "Max Muster"
    assert "Vertretung für Max Muster" in robert.get("/ih/schichtbuch").text
    # falsch begonnen: Roberto übernimmt die Schicht für Team Blau
    sid = anzahl(eng, "SELECT id FROM sb_schichten")
    r = roberto.post("/ih/schichtbuch/schicht-uebernehmen", data={"schicht_id": sid, "team_id": _team_id(eng, "Blau"), "schichtfuehrer": "Roberto",
                                                                   "grund": "Robert hat versehentlich begonnen"}, follow_redirects=True)
    assert "übernommen" in r.text
    with eng.connect() as con:
        s = con.execute(text("SELECT s.*, t.name AS team FROM sb_schichten s JOIN sb_teams t ON t.id=s.team_id")).mappings().first()
        w = con.execute(text("SELECT * FROM sb_schicht_wechsel")).mappings().first()
    assert (s["team"], s["schichtfuehrer"], s["vertretung_fuer"]) == ("Blau", "Roberto", None)
    assert w["benutzer"] == "roberto" and "Grün, Robert (Vertretung für Max Muster)" == w["vorher"]
    seite = roberto.get("/ih/schichtbuch").text
    assert "Übernommen" in seite and "Robert hat versehentlich begonnen" in seite
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Schicht übernommen'") == 1
    assert client(cfg, "le").post("/ih/schichtbuch/schicht-uebernehmen", data={"schicht_id": sid}).status_code in (403, 303)


# ------------------------------------------------------------------ EX-Handys
def test_ex_handys_pin_nur_mit_passwort_und_uebergabe(env, monkeypatch):
    cfg, eng = env
    admin = _grund(cfg, eng)
    uhr = _Uhr(monkeypatch)
    robert, op, le = _als(cfg, "robert"), _als(cfg, "op"), _als(cfg, "le")
    assert op.post("/ih/schichtbuch/handys", data={"name": "X"}).status_code == 403
    robert.post("/ih/schichtbuch/handys", data={"name": "EX-Handy 1", "nummer": "+49 151 000000", "pin": "1234", "puk": "87654321"})
    robert.post("/ih/schichtbuch/handys", data={"name": "EX-Handy 2", "nummer": "+49 151 111111", "pin": "5678"})
    assert "Die PIN darf nur Ziffern" in robert.post("/ih/schichtbuch/handys", data={"name": "X", "pin": "12a"}, follow_redirects=True).text
    with eng.connect() as con:
        roh = " ".join(str(v) for r in con.execute(text("SELECT * FROM sb_handys")) for v in r)
    assert "1234" not in roh and "87654321" not in roh  # verschlüsselt gespeichert
    seite = op.get("/ih/schichtbuch/handys").text
    assert "+49 151 000000" in seite and "tel:+49151000000" in seite and "1234" not in seite and "87654321" not in seite
    hid = anzahl(eng, "SELECT id FROM sb_handys WHERE name='EX-Handy 1'")
    r = op.post(f"/ih/schichtbuch/handys/{hid}/anzeigen", data={"passwort": "falsch", "feld": "pin"})
    assert r.status_code == 403 and "1234" not in r.text
    r = op.post(f"/ih/schichtbuch/handys/{hid}/anzeigen", data={"passwort": "Lager-Test-2026", "feld": "pin"})
    assert r.status_code == 200 and r.json() == {"wert": "1234"} and r.headers["cache-control"] == "no-store"
    assert op.post(f"/ih/schichtbuch/handys/{hid}/anzeigen", data={"passwort": "Lager-Test-2026", "feld": "puk"}).json() == {"wert": "87654321"}
    assert le.post(f"/ih/schichtbuch/handys/{hid}/anzeigen", data={"passwort": "Lager-Test-2026"}).status_code == 403
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion LIKE 'EX-Handy: % angezeigt'") == 2
    # PIN ändern lassen: leer = unverändert, neu = ersetzt
    robert.post("/ih/schichtbuch/handys", data={"id": hid, "name": "EX-Handy 1", "nummer": "+49 151 000000", "pin": "", "aktiv": "on"})
    assert op.post(f"/ih/schichtbuch/handys/{hid}/anzeigen", data={"passwort": "Lager-Test-2026"}).json() == {"wert": "1234"}
    # Übergabe bei Schichtende: ohne Name abgelehnt, mit Name gespeichert
    uhr.stelle(2026, 11, 18, 6, 5)
    robert.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün"), "schichtfuehrer": "Robert"})
    sid = anzahl(eng, "SELECT id FROM sb_schichten")
    assert "EX-Handy 1 übergeben" in robert.get("/ih/schichtbuch/beenden").text
    r = robert.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "handy": str(hid)}, follow_redirects=True)
    assert "an wen" in r.text and anzahl(eng, "SELECT beendet_am FROM sb_schichten") is None
    uhr.stelle(2026, 11, 18, 18, 1)
    robert.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "handy": str(hid), f"handy_an_{hid}": "Roberto Demo"})
    assert anzahl(eng, "SELECT an || '|' || von || '|' || schicht_id FROM sb_handy_uebergaben") == f"Roberto Demo|Robert|{sid}"
    seite = op.get("/ih/schichtbuch").text
    assert "bei Roberto Demo" in seite and "übergeben an <b>Roberto Demo</b>" in seite
    assert "zurzeit bei <b class=\"text-ink\">Roberto Demo</b>" in op.get("/ih/schichtbuch/handys").text


def test_handy_pin_mit_anderem_schluessel_nicht_lesbar():
    from app.services import handys as hy
    w = hy.verschluesseln("schluessel-a", "4711")
    assert hy.entschluesseln("schluessel-a", w) == "4711" and hy.entschluesseln("schluessel-b", w) is None and hy.verschluesseln("x", "") is None


# ------------------------------------------------------------------ Aufgaben
def test_aufgaben_team_dashboard_wiederholung_rechte(env, monkeypatch):
    cfg, eng = env
    _grund(cfg, eng)
    robert, op, le = _als(cfg, "robert"), _als(cfg, "op"), _als(cfg, "le")
    blau, gruen = _team_id(eng, "Blau"), _team_id(eng, "Grün")
    assert le.post("/ih/schichtbuch/aufgaben/neu", data={"titel": "x"}).status_code == 403
    gestern = (date.today() - timedelta(days=1)).isoformat()
    r = op.post("/ih/schichtbuch/aufgaben/neu", data={"titel": "Filter Kompressor bestellen", "team_id": blau, "faellig": gestern, "prioritaet": "hoch"})
    assert r.status_code == 303
    op.post("/ih/schichtbuch/aufgaben/neu", data={"titel": "Werkstatt aufräumen", "faellig": date.today().isoformat(), "wiederholen_tage": "7"})
    assert "Fälligkeitsdatum" in op.post("/ih/schichtbuch/aufgaben/neu", data={"titel": "y", "wiederholen_tage": "7"}).text
    assert "Titel" in op.post("/ih/schichtbuch/aufgaben/neu", data={"titel": " "}).text
    blau_seite = op.get(f"/ih/schichtbuch?team={blau}").text.split('id="aufgaben"')[1].split("</section>")[0]
    gruen_seite = op.get(f"/ih/schichtbuch?team={gruen}").text.split('id="aufgaben"')[1].split("</section>")[0]
    assert "Filter Kompressor bestellen" in blau_seite and "überfällig" in blau_seite and "Werkstatt aufräumen" in blau_seite
    assert "Filter Kompressor bestellen" not in gruen_seite and "Werkstatt aufräumen" in gruen_seite
    liste = op.get("/ih/schichtbuch/aufgaben?nur=ueberfaellig").text
    assert "Filter Kompressor bestellen" in liste and "Werkstatt aufräumen" not in liste
    # wiederkehrend erledigen -> neue Aufgabe in 7 Tagen
    wid = anzahl(eng, "SELECT id FROM sb_aufgaben WHERE titel='Werkstatt aufräumen'")
    r = op.post(f"/ih/schichtbuch/aufgaben/{wid}/status", data={"status": "erledigt", "text": "erledigt"}, follow_redirects=True)
    assert "Nächste Wiederholung" in r.text
    assert anzahl(eng, "SELECT faellig FROM sb_aufgaben WHERE titel='Werkstatt aufräumen' AND status='offen'") == (date.today() + timedelta(days=7)).isoformat()
    # neu zuteilen an Grün, Kommentar, Verlauf
    aid = anzahl(eng, "SELECT id FROM sb_aufgaben WHERE titel LIKE 'Filter%'")
    op.post(f"/ih/schichtbuch/aufgaben/{aid}", data={"titel": "Filter Kompressor bestellen", "team_id": gruen, "faellig": gestern, "prioritaet": "hoch"})
    op.post(f"/ih/schichtbuch/aufgaben/{aid}/kommentar", data={"text": "Angebot angefragt"})
    detail = op.get(f"/ih/schichtbuch/aufgaben/{aid}").text
    assert "an Grün" in detail and "Angebot angefragt" in detail
    # löschen: nur Ersteller oder Einrichter
    ih_benutzer(eng, "op2", "operator")
    op2 = _als(cfg, "op2")
    op2.post(f"/ih/schichtbuch/aufgaben/{aid}/loeschen")
    assert anzahl(eng, "SELECT count(*) FROM sb_aufgaben WHERE id=:a", a=aid) == 1
    robert.post(f"/ih/schichtbuch/aufgaben/{aid}/loeschen")
    assert anzahl(eng, "SELECT count(*) FROM sb_aufgaben WHERE id=:a", a=aid) == 0
    ex = op.get("/ih/schichtbuch/aufgaben/export.xlsx?status=alle")
    assert ex.status_code == 200 and ex.content[:2] == b"PK"


# ------------------------------------------------------------------ Montage: Lage der Dichtung
def test_dichtung_lage_im_protokoll_druck_und_excel(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "op", "operator")
    from app.services import montage as mt
    with schreib(eng) as con:
        sid = mt.stutzen_speichern(con, None, {"kuerzel": "DS 1", "bezeichnung": "Demo", "schrauben_anzahl": 4, "drehmoment": "100"},
                                   [{"dichtungsart": "MCR", "artikel_nr": "D-1", "lage": "i"}, {"dichtungsart": "MCR", "artikel_nr": "D-2", "lage": "a"},
                                    {"dichtungsart": "VOR", "artikel_nr": "D-3", "lage": "x"}], "Tester")
    assert [r[0] for r in eng.connect().execute(text("SELECT lage FROM mt_stutzen_dichtungen ORDER BY pos"))] == ["i", "a", None]
    op = client(cfg, "op")
    assert '"lage": "i"' in op.get(f"/ih/montage/protokolle/neu?stutzen={sid}").text
    d = {"stutzen_id": str(sid), "schrauben_anzahl": "4", "aktion": "speichern", "reihenfolge": "[]",
         "d0_dichtungsart": "MCR", "d0_lage": "i", "d1_dichtungsart": "MCR", "d1_lage": "m", "d2_dichtungsart": "VOR", "d2_lage": "a"}
    r = op.post("/ih/montage/protokolle/neu", data=d)
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    assert [x["lage"] for x in json.loads(anzahl(eng, "SELECT dichtungen FROM mt_protokolle"))] == ["i", "m", "a"]
    druck = op.get(f"/ih/montage/protokolle/{pid}/druck").text
    assert "Dichtung 1 · i" in druck and "Dichtung 2 · m" in druck and "Dichtung 3 · ä" in druck
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(op.get(f"/ih/montage/protokolle/{pid}/excel").content)).active
    assert [ws[f"H{z}"].value for z in (9, 10, 11)] == ["Dichtung 1 · i", "Dichtung 2 · m", "Dichtung 3 · ä"]
    op.post(f"/ih/montage/protokolle/{pid}", data={**d, "d1_lage": "z"})
    assert json.loads(anzahl(eng, "SELECT dichtungen FROM mt_protokolle"))[1]["lage"] == ""


# ------------------------------------------------------------------ Meine Einstellungen
def test_meine_einstellungen_startseite_und_vorgaben(env):
    cfg, eng = env
    _grund(cfg, eng)
    op = client(cfg, "op")
    seite = op.get("/mein").text
    assert "Startseite nach dem Anmelden" in seite and "Startseite je Rolle" not in seite and "Lager – Buchen" not in seite
    op.post("/mein", data={"startseite": "schichtbuch", "anzeigename": "Olaf Operator", "monteur_vorbelegen": "on"})
    assert client(cfg).post("/login", data={"username": "op", "passwort": "Lager-Test-2026"}).headers["location"] == "/ih/schichtbuch"
    assert anzahl(eng, "SELECT anzeigename FROM users WHERE username='op'") == "Olaf Operator"
    assert '"Olaf Operator"' in op.get("/ih/montage/protokolle/neu").text or 'value="Olaf Operator"' in op.get("/ih/montage/protokolle/neu").text
    # nicht erlaubte Startseite wird nicht gespeichert, Rollenvorgaben darf der Operator nicht setzen
    op.post("/mein", data={"startseite": "buchen", "rollen_bearbeitet": "1", "rolle_ih:operator": "aufgaben"})
    assert anzahl(eng, "SELECT count(*) FROM settings WHERE schluessel LIKE 'startseite_rolle:%'") == 0
    assert client(cfg).post("/login", data={"username": "op", "passwort": "Lager-Test-2026"}).headers["location"] != "/buchen"
    # Instandhaltungsmanager: Startseite je Rolle
    mgr = client(cfg, "mgr")
    assert "Startseite je Rolle" in mgr.get("/mein").text
    mgr.post("/mein", data={"rollen_bearbeitet": "1", "rolle_ih:operator": "aufgaben", "rolle_ih:techniker": "montage", "rolle_lager:lager": "buchen"})
    ih_benutzer(eng, "op3", "operator")
    assert client(cfg).post("/login", data={"username": "op3", "passwort": "Lager-Test-2026"}).headers["location"] == "/ih/schichtbuch/aufgaben"
    assert client(cfg).post("/login", data={"username": "lager", "passwort": "Lager-Test-2026"}).headers["location"] == "/buchen"
    assert client(cfg).post("/login", data={"username": "admin", "passwort": "Lager-Test-2026"}).headers["location"] in ("/", "/bereich", "/ih")
    # eigene Wahl geht vor; „weiter“ aus dem Link geht vor
    assert client(cfg).post("/login", data={"username": "op", "passwort": "Lager-Test-2026"}).headers["location"] == "/ih/schichtbuch/aufgaben"
    op.post("/mein", data={"startseite": "schichtbuch"})  # eigene Wahl (oben durch die ungültige gelöscht) wieder setzen
    assert client(cfg).post("/login", data={"username": "op", "passwort": "Lager-Test-2026"}).headers["location"] == "/ih/schichtbuch"
    assert client(cfg).post("/login", data={"username": "op", "passwort": "Lager-Test-2026", "weiter": "/ih/auftraege"}).headers["location"] == "/ih/auftraege"
    # Lager: Buchen öffnet mit der gewählten Buchungsart
    lager = client(cfg, "lager")
    lager.post("/mein", data={"buchungsart": "eingang"})
    assert 'name="typ" value="eingang"' in lager.get("/buchen?artikel=").text or "Eingang buchen" in lager.get("/buchen").text
    assert "Meine Einstellungen" in lager.get("/").text
