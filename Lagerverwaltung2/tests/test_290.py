"""2.9.0: Schicht wieder öffnen, nächste Schicht vorzeitig beginnen, Meldungen nachtragen, Papierformulare,
Instandhaltungs-App, Programmname. Alle Daten erfunden."""
from __future__ import annotations

import base64
import re
import sqlite3
from datetime import datetime

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import anzahl, client
from test_schichtbuch_280 import _Uhr, _als, _team_id, _uid
from test_wartung_260 import _anlagen


def _start(env, monkeypatch):
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    uhr = _Uhr(monkeypatch)
    for name, rolle in (("anna", "operator"), ("bernd", "schichtfuehrer"), ("leser", "lesen")):
        ih_benutzer(eng, name, rolle)
    admin = client(cfg, "admin")
    admin.get("/ih/schichtbuch")
    admin.post("/ih/schichtbuch/einrichten/mitglieder", data={f"team_{_uid(eng, 'anna')}": _team_id(eng, "Grün"),
                                                              f"team_{_uid(eng, 'bernd')}": _team_id(eng, "Blau")})
    return cfg, eng, uhr, admin, _als(cfg, "anna"), _als(cfg, "bernd")


# ------------------------------------------------------------------ Schicht wieder öffnen
def test_schicht_wieder_oeffnen_und_erneut_beenden(env, monkeypatch):
    cfg, eng, uhr, admin, anna, bernd = _start(env, monkeypatch)
    anna.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün")})
    for t in ("Pumpe undicht", "Ventil klemmt"):
        anna.post("/ih/schichtbuch/neu", data={"titel": t, "prioritaet": "hoch"})
    m1, m2 = (anzahl(eng, "SELECT id FROM sb_meldungen WHERE titel=:t", t=t) for t in ("Pumpe undicht", "Ventil klemmt"))
    sid = anzahl(eng, "SELECT id FROM sb_schichten")
    uhr.stelle(2026, 11, 11, 16, 0)
    anna.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "ueb": [str(m1), str(m2)], f"text_{m1}": "Dichtung bestellt", "notiz": "Teillast"})
    seite = anna.get("/ih/schichtbuch").text
    assert "Schicht beendet" in seite and "Schicht wieder öffnen" in seite and "Nacht 11.11.–12.11.2026" in seite and "Offene Übergaben (2)" in seite
    # versehentlich beendet -> wieder öffnen: Übergaben sind ausgeblendet, Schicht läuft weiter
    r = anna.post("/ih/schichtbuch/wieder-oeffnen", data={"schicht_id": sid}, follow_redirects=True)
    assert "wieder offen" in r.text and "Schicht läuft" in r.text and "Offene Übergaben (0)" in r.text
    assert anzahl(eng, f"SELECT beendet_am IS NULL FROM sb_schichten WHERE id={sid}") == 1
    assert "Vorgemerkt" in anna.get(f"/ih/schichtbuch/meldung/{m1}").text
    assert "schon übernommen" in bernd.post(f"/ih/schichtbuch/meldung/{m1}/uebernehmen", follow_redirects=True).text  # nicht übernehmbar
    # erneut beenden: Auswahl und Texte vorbelegt; m2 jetzt abgewählt -> zurückgenommen
    form = anna.get("/ih/schichtbuch/beenden").text
    assert "Dichtung bestellt" in form and ">Teillast</textarea>" in form
    anna.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "ueb": str(m1), f"text_{m1}": "Dichtung kommt morgen", "notiz": "Teillast"})
    assert anzahl(eng, f"SELECT uebergabe || '|' || coalesce(uebergeben_schicht_id, '-') FROM sb_meldungen WHERE id={m2}") == "0|-"
    assert anzahl(eng, f"SELECT count(*) FROM sb_verlauf WHERE meldung_id={m2} AND art='uebergabe_zurueck'") == 1
    assert "Übergabe zurückgenommen" in anna.get(f"/ih/schichtbuch/meldung/{m2}").text
    # Nachtschicht beginnt und übernimmt -> nicht mehr öffnen
    uhr.stelle(2026, 11, 11, 18, 5)
    seite = bernd.get("/ih/schichtbuch").text
    assert "Offene Übergaben (1)" in seite and "Dichtung kommt morgen" in seite
    bernd.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Blau")})
    r = anna.post("/ih/schichtbuch/wieder-oeffnen", data={"schicht_id": sid}, follow_redirects=True)
    assert "hat schon begonnen" in r.text and anzahl(eng, f"SELECT beendet_am IS NOT NULL FROM sb_schichten WHERE id={sid}") == 1
    bernd.post(f"/ih/schichtbuch/meldung/{m1}/uebernehmen")
    from app.services import schichtbuch as sb
    with eng.connect() as con:
        assert "übernommen" in sb.wieder_oeffnen_grund(con, sid)
    assert _als(cfg, "leser").post("/ih/schichtbuch/wieder-oeffnen", data={"schicht_id": sid}).status_code == 403


def test_naechste_schicht_vorzeitig_beginnen(env, monkeypatch):
    cfg, eng, uhr, admin, anna, bernd = _start(env, monkeypatch)
    uhr.stelle(2026, 11, 11, 12, 0)
    anna.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün")})
    assert "Nächste Schicht beginnen" not in bernd.get("/ih/schichtbuch").text  # mittags noch nicht
    r = bernd.post("/ih/schichtbuch/beginnen", data={"naechste": "1", "team_id": _team_id(eng, "Blau")}, follow_redirects=True)
    assert "frühestens 2 Stunden" in r.text and anzahl(eng, "SELECT count(*) FROM sb_schichten") == 1
    # 17:30: Übergabe vor der vollen Stunde -> Nachtschicht beginnt schon
    uhr.stelle(2026, 11, 11, 17, 30)
    assert "Nächste Schicht beginnen" in bernd.get("/ih/schichtbuch").text
    bernd.post("/ih/schichtbuch/beginnen", data={"naechste": "1", "team_id": _team_id(eng, "Blau"), "schichtfuehrer": "Bernd B."})
    seite = bernd.get("/ih/schichtbuch").text
    assert "Nacht 11.11.–12.11.2026" in seite.split("Schichtbuch</h1>")[1][:400] and "Bernd B." in seite
    assert "nicht beendet" in seite or "Übergabe nachholen" in seite  # Tagschicht ist noch offen
    bernd.post("/ih/schichtbuch/neu", data={"titel": "Rundgang Nacht"})
    nacht = anzahl(eng, "SELECT id FROM sb_schichten WHERE zeit_id=(SELECT id FROM sb_zeiten WHERE name='Nacht')")
    assert anzahl(eng, "SELECT schicht_id FROM sb_meldungen WHERE titel='Rundgang Nacht'") == nacht


# ------------------------------------------------------------------ Nachtrag
def test_meldung_nachtragen(env, monkeypatch):
    cfg, eng, uhr, admin, anna, bernd = _start(env, monkeypatch)
    uhr.stelle(2026, 11, 11, 9, 0)
    form = bernd.get("/ih/schichtbuch/neu?nachtrag=1").text
    assert 'name="zeitpunkt"' in form and 'max="2026-11-11T09:00"' in form and "nachtrag: true" in form
    basis = {"titel": "Pumpe ausgefallen (Papier)", "nachtrag": "on", "nachtrag_team": _team_id(eng, "Rot"), "nachtrag_schichtfuehrer": "Max M.",
             "status": "erledigt", "asset": "P -10401 A"}
    for zp, fehler in (("", "Datum und Uhrzeit"), ("2026-11-11T10:00", "Zukunft"), ("2025-01-01T08:00", "ein Jahr")):
        r = bernd.post("/ih/schichtbuch/neu", data={**basis, "zeitpunkt": zp})
        assert r.status_code == 200 and fehler in r.text, zp
    assert anzahl(eng, "SELECT count(*) FROM sb_meldungen") == 0
    r = bernd.post("/ih/schichtbuch/neu", data={**basis, "zeitpunkt": "2026-11-10T03:15"}, follow_redirects=True)
    assert "nachgetragen (10.11.2026 03:15)" in r.text
    with eng.connect() as con:
        row = con.exec_driver_sql(
            "SELECT m.erstellt_am, m.nachgetragen_von, m.nachgetragen_am, m.erledigt_am, z.name, s.datum, t.name, s.schichtfuehrer FROM sb_meldungen m "
            "JOIN sb_schichten s ON s.id=m.schicht_id JOIN sb_zeiten z ON z.id=s.zeit_id JOIN sb_teams t ON t.id=s.team_id").fetchone()
    assert str(row[0]).startswith("2026-11-10 03:15") and row[1] == "bernd" and str(row[2]).startswith("2026-11-11 09:00")
    assert str(row[3]).startswith("2026-11-10 03:15")
    assert (row[4], str(row[5]), row[6], row[7]) == ("Nacht", "2026-11-09", "Rot", "Max M.")  # 03:15 gehört zur Nacht vom 09.11.
    mid = anzahl(eng, "SELECT id FROM sb_meldungen")
    detail = bernd.get(f"/ih/schichtbuch/meldung/{mid}").text
    assert "Nachtrag, erfasst 11.11.2026 09:00 von bernd" in detail and "Nachtrag zum 10.11.2026 03:15" in detail
    assert ">Nachtrag</span>" in bernd.get("/ih/schichtbuch/meldungen").text
    # erscheint in den vorherigen Schichten und „seit der letzten Schicht“
    seite = anna.get("/ih/schichtbuch").text
    assert "Pumpe ausgefallen (Papier)" in seite and "Nacht 09.11.–10.11.2026" in seite
    # Export: Datum = Zeitpunkt des Ereignisses
    from openpyxl import load_workbook
    import io
    ws = load_workbook(io.BytesIO(admin.get("/ih/schichtbuch/export.xlsx").content)).active
    assert ws.cell(2, 2).value == datetime(2026, 11, 10, 3, 15)


# ------------------------------------------------------------------ Papierformulare
def test_papierformulare(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "op", "operator")
    admin = client(cfg, "admin")
    admin.post("/ih/schichtbuch/einrichten/typen", data={"typen": "Störung\nLeckage"})
    seite = admin.get("/ih/schichtbuch/papier").text
    for erwartet in ("Schichtbuch – Papierformular", "Grün", "Rot", "Tag (06:00–18:00)", "1 = Störung", "2 = Leckage", "Nachtragen", "window.print()"):
        assert erwartet in seite, erwartet
    assert _als(cfg, "op").get("/ih/schichtbuch/papier").status_code == 200
    lager = client(cfg, "lager").get("/papier/lager")
    assert lager.status_code == 200 and "Entnahmen und Eingänge" in lager.text and "Papier vom TT.MM." in lager.text
    assert _als(cfg, "op").get("/papier/lager").status_code == 403  # ohne Lagerrolle
    assert client(cfg).get("/papier/lager").status_code in (302, 303)
    notfall = admin.get("/einstellungen?tab=notfall").text
    assert "/ih/schichtbuch/papier" in notfall and "/papier/lager" in notfall and "jetzt ausdrucken" in notfall


# ------------------------------------------------------------------ Instandhaltungs-App
def test_instandhaltungs_app(env, monkeypatch):
    cfg, eng, uhr, admin, anna, bernd = _start(env, monkeypatch)
    anna.post("/ih/schichtbuch/neu", data={"titel": "Leck"})
    start = anna.get("/ih/m")
    assert start.status_code == 200 and "Neue Meldung" in start.text and "offene Meldungen" in start.text and "Grün" in start.text
    assert 'href="/ih/manifest.webmanifest"' in start.text and "/ih/sw.js" in start.text and 'aria-label="App-Navigation"' in start.text
    lager_seite = client(cfg, "lager").get("/artikel").text
    assert 'href="/manifest.webmanifest"' in lager_seite and "App-Navigation" not in lager_seite
    man = client(cfg).get("/ih/manifest.webmanifest").json()
    assert (man["scope"], man["start_url"], man["short_name"]) == ("/ih/", "/ih/m", "Instandhaltung") and "icon-ih-192.png" in str(man["icons"])
    sw = client(cfg).get("/ih/sw.js")
    assert sw.headers["service-worker-allowed"] == "/ih/" and "Papierformular" in sw.text
    # Tag-Nr. scannen: genau ein Treffer -> Anlage, sonst Liste
    assert anna.get("/ih/m/suche", params={"q": "p-10401a"}).headers["location"] == "/ih/anlagen/2"
    assert anna.get("/ih/m/suche", params={"q": "P 104"}).headers["location"] == "/ih/anlagen?q=P%20104"
    assert client(cfg, "lager").get("/ih/m").status_code == 403
    hinweis = admin.get("/einstellungen?tab=handy").text
    assert "Instandhaltungs-App fürs Handy" in hinweis and "/ih/m" in hinweis


# ------------------------------------------------------------------ Programmname
def test_programmname(env):
    cfg, eng = env
    admin = client(cfg, "admin")
    allgemein = {"firmenname": "CAPHENIA", "port": "8080", "https_port": "8443", "standard_einheit": "Stk", "live_abfrage_sekunden": "10"}
    r = admin.post("/einstellungen/allgemein", data={**allgemein, "programmname": "Werk:App"}, follow_redirects=True)
    assert "ohne die Zeichen" in r.text and cfg.server.programmname == "Lagerverwaltung"
    admin.post("/einstellungen/allgemein", data={**allgemein, "programmname": "  Betriebssoftware  "})
    assert cfg.server.programmname == "Betriebssoftware"
    from app.config import CONFIG_PATH
    import tomllib
    assert tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))["server"]["programmname"] == "Betriebssoftware"
    assert "Betriebssoftware CAPHENIA" in client(cfg).get("/login").text
    assert admin.get("/manifest.webmanifest").json()["short_name"] == "Betriebssoftware"
    assert "– CAPHENIA Betriebssoftware</title>" in admin.get("/artikel").text
    bat = admin.get("/arbeitsplatz.bat").content.decode("cp1252")
    ps = base64.b64decode(re.search(r"-EncodedCommand (\S+)", bat).group(1)).decode("utf-16-le")
    assert "$name = 'Betriebssoftware'" in ps and "Remove-Item (Join-Path $d 'Lagerverwaltung.lnk')" in ps
    admin.post("/einstellungen/allgemein", data={**allgemein, "programmname": ""})
    assert cfg.server.programmname == "Lagerverwaltung"


# ------------------------------------------------------------------ Rechte und Migration
NEUE = [("post", "/ih/schichtbuch/wieder-oeffnen", "ih.schichtbuch.schreiben"), ("get", "/ih/schichtbuch/papier", "ih.schichtbuch.ansehen"),
        ("get", "/ih/m", "ih.ansehen"), ("get", "/ih/m/suche?q=x", "ih.ansehen")]


def test_rechte_neue_routen_290(env):
    from app.rechte import IH_ROLLEN, RECHTE
    cfg, eng = env
    cmms_an(cfg)
    for r in IH_ROLLEN:
        ih_benutzer(eng, f"ih_{r}", r)
    for r in IH_ROLLEN:
        c = _als(cfg, f"ih_{r}")
        for methode, pfad, recht in NEUE:
            status = getattr(c, methode)(pfad).status_code
            assert (status != 403) == (r in RECHTE[recht]), (r, pfad, status)


def test_migration_4_von_2_8(env):
    from app import db, migrationen
    cfg, eng = env
    db.engine().dispose()
    pfad = cfg.path(cfg.daten.datenbank)
    con = sqlite3.connect(str(pfad))
    con.execute("DELETE FROM schema_version WHERE version=4")
    for s in ("nachgetragen_am", "nachgetragen_von"):
        con.execute(f"ALTER TABLE sb_meldungen DROP COLUMN {s}")
    con.commit()
    con.close()
    migrationen.vor_start(cfg)
    db.init_engine(cfg.db_url)
    with db.engine().connect() as c2:
        assert [r[0] for r in c2.exec_driver_sql("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4]
        assert {"nachgetragen_am", "nachgetragen_von"} <= {r[1] for r in c2.exec_driver_sql("PRAGMA table_info(sb_meldungen)")}
