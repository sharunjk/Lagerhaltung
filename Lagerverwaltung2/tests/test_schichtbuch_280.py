"""2.8.0: Schichtbuch – Teams, Schichtzeiten, Schichtbeginn, Meldungen, Übergaben, Schichtende, Export. Alle Daten erfunden."""
from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from sqlalchemy import select

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import anzahl, client, schreib
from test_wartung_260 import _anlagen


class _Uhr:
    """Steuert „jetzt“ im Schichtbuch (Service und Seiten)."""

    def __init__(self, monkeypatch):
        import app.routes.schichtbuch as r
        import app.services.schichtbuch as s
        uhr = self

        class DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return uhr.jetzt
        self.jetzt = datetime(2026, 11, 11, 7, 0)
        monkeypatch.setattr(s, "datetime", DT)
        monkeypatch.setattr(r, "datetime", DT)

    def stelle(self, *args):
        self.jetzt = datetime(*args)


def _als(cfg, name):
    c = client(cfg)
    assert c.post("/login", data={"username": name, "passwort": "Lager-Test-2026"}).status_code == 303
    return c


def _team_id(eng, name):
    return anzahl(eng, "SELECT id FROM sb_teams WHERE name=:n", n=name)


def _uid(eng, name):
    return anzahl(eng, "SELECT id FROM users WHERE username=:n", n=name)


# ------------------------------------------------------------------ Schichtzeiten
def test_schichtzeiten_und_aktuelle_schicht(env):
    from app.services import schichtbuch as sb
    cfg, eng = env
    with schreib(eng) as con:
        sb.sicherstellen(con)
        sb.sicherstellen(con)  # zweimal: keine Doppelten
        assert [t["name"] for t in sb.teams(con)] == ["Grün", "Blau", "Gelb", "Rot"]
        assert [(z["name"], z["beginn"], z["ende"]) for z in sb.zeiten(con)] == [("Tag", "06:00", "18:00"), ("Nacht", "18:00", "06:00")]
        for jetzt, erwartet in [((2026, 11, 11, 6, 0), ("Tag", date(2026, 11, 11))), ((2026, 11, 11, 17, 59), ("Tag", date(2026, 11, 11))),
                                ((2026, 11, 11, 18, 0), ("Nacht", date(2026, 11, 11))), ((2026, 11, 12, 5, 59), ("Nacht", date(2026, 11, 11))),
                                ((2026, 12, 31, 23, 0), ("Nacht", date(2026, 12, 31)))]:
            d, z = sb.slot(con, datetime(*jetzt))
            assert (z["name"], d) == erwartet, jetzt
        nacht = sb.zeiten(con)[1]
        assert sb.bezeichnung(date(2026, 11, 11), nacht) == "Nacht 11.11.–12.11.2026"
        assert sb.bezeichnung(date(2026, 11, 11), sb.zeiten(con)[0]) == "Tag 11.11.2026"
    assert sb.uhrzeit("6:00") == "06:00" and sb.uhrzeit("2200") == "22:00" and sb.uhrzeit("14.30") == "14:30"
    for falsch in ("24:00", "6", "abc", "12:60"):
        with pytest.raises(sb.SchichtFehler):
            sb.uhrzeit(falsch)


# ------------------------------------------------------------------ Ablauf über drei Schichten
def test_ablauf_beginn_meldung_uebergabe_naechste_schicht(env, monkeypatch):
    from app.db import sb_meldungen
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    uhr = _Uhr(monkeypatch)
    ih_benutzer(eng, "anna", "operator")
    ih_benutzer(eng, "bernd", "schichtfuehrer")
    ih_benutzer(eng, "leser", "lesen")
    admin = client(cfg, "admin")
    admin.get("/ih/schichtbuch")  # legt Teams und Zeiten an
    admin.post("/ih/schichtbuch/einrichten/mitglieder", data={f"team_{_uid(eng, 'anna')}": _team_id(eng, "Grün"),
                                                              f"team_{_uid(eng, 'bernd')}": _team_id(eng, "Blau")})
    assert anzahl(eng, "SELECT count(*) FROM sb_mitglieder") == 2
    anna, bernd, leser = _als(cfg, "anna"), _als(cfg, "bernd"), _als(cfg, "leser")

    # --- Tagschicht 11.11., Team Grün
    seite = anna.get("/ih/schichtbuch").text
    assert "Schicht noch nicht begonnen" in seite and "Tag 11.11.2026" in seite and "Ihr Team" in seite
    anna.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Grün"), "schichtfuehrer": "Anna A."})
    seite = anna.get("/ih/schichtbuch").text
    assert "Schicht läuft" in seite and "Anna A." in seite
    r = anna.post("/ih/schichtbuch/neu", data={"titel": "", "beschreibung": "x"})
    assert r.status_code == 200 and "Titel" in r.text and anzahl(eng, "SELECT count(*) FROM sb_meldungen") == 0
    uhr.stelle(2026, 11, 11, 9, 30)
    r = anna.post("/ih/schichtbuch/neu", data={
        "titel": "Pumpe undicht am Gleitring", "ereignistyp": "Störung", "prioritaet": "hoch", "beschreibung": "Tropft ca. 1 l/h",
        "massnahme": "Auffangwanne gestellt", "asset": "P -10401 A – Bauteil P -10401 A", "work_order": "4711-EXT",
        "stillstand_h": "1,5", "sicherheitsrelevant": "on", "weiter": "dashboard"})
    assert r.headers["location"] == "/ih/schichtbuch"
    with eng.connect() as con:
        m1 = dict(con.execute(select(sb_meldungen)).mappings().first())
    assert (m1["platz_id"], m1["asset"], m1["functional_location"]) == (2, "P -10401 A", "1040")  # Bezeichnung „Bauteil 1040“ wiederholt nur die Nummer
    assert m1["stillstand"] and m1["stillstand_h"] == 1.5 and m1["prioritaet"] == "hoch" and m1["auftrag_id"] is None
    anna.post("/ih/schichtbuch/neu", data={"titel": "Umstellung auf Teillast", "ereignistyp": "Information", "status": "erledigt"})
    m2 = anzahl(eng, "SELECT max(id) FROM sb_meldungen")
    assert anzahl(eng, f"SELECT erledigt_von FROM sb_meldungen WHERE id={m2}") == "anna"
    r = anna.post(f"/ih/schichtbuch/meldung/{m1['id']}/ergaenzen", data={"text": "", "status": "offen"}, follow_redirects=True)
    assert "Ergänzung schreiben oder den Status" in r.text
    anna.post(f"/ih/schichtbuch/meldung/{m1['id']}/ergaenzen", data={"text": "Gleitring bestellt", "status": "in_arbeit"})
    assert anzahl(eng, f"SELECT status FROM sb_meldungen WHERE id={m1['id']}") == "in_arbeit"
    # Lesen darf nichts schreiben
    assert leser.get("/ih/schichtbuch").status_code == 200
    assert leser.post("/ih/schichtbuch/neu", data={"titel": "x"}).status_code == 403
    assert leser.post("/ih/schichtbuch/beenden", data={"schicht_id": "1"}).status_code == 403
    # Schichtende: Meldung 1 ist vorausgewählt (Prio hoch, dieser Schicht), Meldung 2 ist erledigt
    uhr.stelle(2026, 11, 11, 17, 50)
    seite = anna.get("/ih/schichtbuch/beenden").text
    assert f'name="ueb" value="{m1["id"]}"' in seite and "In dieser Schicht erledigt" in seite
    assert seite.split(f'name="ueb" value="{m1["id"]}"')[1].split(">")[0].count("checked") == 1
    sid = anzahl(eng, "SELECT id FROM sb_schichten")
    anna.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "ueb": str(m1["id"]), f"text_{m1['id']}": "Ersatzteil kommt morgen früh",
                                               "notiz": "Anlage auf Teillast."})
    assert anzahl(eng, f"SELECT uebergabe || '|' || uebergeben_schicht_id FROM sb_meldungen WHERE id={m1['id']}") == f"1|{sid}"
    r = anna.post("/ih/schichtbuch/beenden", data={"schicht_id": sid}, follow_redirects=True)
    assert "schon beendet" in r.text

    # --- Nachtschicht 11./12.11., Team Blau
    uhr.stelle(2026, 11, 11, 18, 5)
    seite = bernd.get("/ih/schichtbuch").text
    assert "Nacht 11.11.–12.11.2026" in seite and "Offene Übergaben (1)" in seite and "Ersatzteil kommt morgen früh" in seite
    assert "Anlage auf Teillast." in seite and "Team Blau hatte noch keine Schicht" in seite
    bernd.post("/ih/schichtbuch/beginnen", data={"team_id": _team_id(eng, "Blau")})
    bernd.post(f"/ih/schichtbuch/meldung/{m1['id']}/uebernehmen", data={"kommentar": "Wanne kontrolliert"})
    assert "Offene Übergaben (0)" in bernd.get("/ih/schichtbuch").text
    assert bernd.post(f"/ih/schichtbuch/meldung/{m1['id']}/uebernehmen", follow_redirects=True).text.count("schon übernommen") == 1
    nacht = anzahl(eng, "SELECT id FROM sb_schichten WHERE zeit_id=(SELECT id FROM sb_zeiten WHERE name='Nacht')")
    assert anzahl(eng, f"SELECT uebernommen_von || '|' || uebernommen_schicht_id FROM sb_meldungen WHERE id={m1['id']}") == f"bernd|{nacht}"
    uhr.stelle(2026, 11, 12, 2, 0)
    bernd.post(f"/ih/schichtbuch/meldung/{m1['id']}/ergaenzen", data={"text": "Gleitring getauscht, dicht", "status": "erledigt"})
    assert anzahl(eng, f"SELECT erledigt_schicht_id FROM sb_meldungen WHERE id={m1['id']}") == nacht
    detail = bernd.get(f"/ih/schichtbuch/meldung/{m1['id']}").text
    assert "Übergabe übernommen" in detail and "Wanne kontrolliert" in detail and "von einer späteren Schicht" in detail
    # Nachtschicht wird nicht beendet -> nächste Schicht sieht den Hinweis

    # --- Tagschicht 12.11., wieder Team Grün: sieht, was seit seiner letzten Schicht passiert ist
    uhr.stelle(2026, 11, 12, 6, 10)
    seite = anna.get("/ih/schichtbuch").text
    assert "Seit der letzten Schicht von" in seite and "Gleitring" in seite.split("Seit der letzten Schicht von")[1]
    assert "Übergabe nachholen" in seite and "Tag 12.11.2026" in seite
    assert anna.get(f"/ih/schichtbuch/beenden?schicht={nacht}").status_code == 200

    # --- Export mit den Spalten der SharePoint-Liste
    from openpyxl import load_workbook
    r = admin.get("/ih/schichtbuch/export.xlsx")
    ws = load_workbook(io.BytesIO(r.content)).active
    kopf = [c.value for c in ws[1]]
    assert kopf == ["Titel", "Datum", "Schicht", "Schichtführer", "Team", "Ereignistyp", "Beschreibung", "Maßnahme", "Status", "Priorität",
                    "Asset", "Functional Location", "Work Order", "Übergabe an nächste Schicht", "Erledigt von nächster Schicht",
                    "Kommentar nächste Schicht", "Sicherheitsrelevant", "Stillstand Anlage", "Stillstandsdauer (h)"]
    zeilen = {row[0]: row for row in ws.iter_rows(min_row=2, values_only=True)}
    z = dict(zip(kopf, zeilen["Pumpe undicht am Gleitring"]))
    assert (z["Schicht"], z["Schichtführer"], z["Team"], z["Status"], z["Priorität"], z["Work Order"]) == ("Tag", "Anna A.", "Grün", "Erledigt", "Hoch", "4711-EXT")
    assert (z["Übergabe an nächste Schicht"], z["Erledigt von nächster Schicht"], z["Sicherheitsrelevant"], z["Stillstandsdauer (h)"]) == ("Ja", "Ja", "Ja", 1.5)
    assert "Wanne kontrolliert" in z["Kommentar nächste Schicht"] and "Gleitring getauscht" in z["Kommentar nächste Schicht"]
    assert dict(zip(kopf, zeilen["Umstellung auf Teillast"]))["Erledigt von nächster Schicht"] == "Nein"
    # Anlage zeigt die Meldung, Liste filtert
    assert "Pumpe undicht am Gleitring" in anna.get("/ih/anlagen/2").text
    assert "Pumpe undicht" in anna.get("/ih/schichtbuch/meldungen?nur=sicherheit").text
    assert "Pumpe undicht" not in anna.get("/ih/schichtbuch/meldungen?status=offen_alle").text
    liste = anna.get(f"/ih/schichtbuch/meldungen?team={_team_id(eng, 'Blau')}").text
    assert "Keine Meldungen" in liste  # beide Meldungen stammen aus der Schicht von Team Grün


def test_work_order_verknuepft_auftrag_und_bearbeiten(env, monkeypatch):
    from app.db import ih_auftraege
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    _Uhr(monkeypatch)
    with schreib(eng) as con:
        con.execute(ih_auftraege.insert().values(id=12, termin=date(2026, 11, 9), massnahme="W", titel="Wartung Pumpe", status="in_arbeit",
                                                 erstellt_von="t", erstellt_am=datetime(2026, 11, 1)))
    admin = client(cfg, "admin")
    admin.post("/ih/schichtbuch/neu", data={"titel": "Pumpe laut", "work_order": "A-00012", "asset": "unbekannt 99"})
    mid = anzahl(eng, "SELECT id FROM sb_meldungen")
    assert anzahl(eng, f"SELECT auftrag_id || '|' || asset FROM sb_meldungen WHERE id={mid}") == "12|unbekannt 99"
    seite = admin.get(f"/ih/schichtbuch/meldung/{mid}").text
    assert "/ih/auftraege/12" in seite and "in_arbeit" in seite
    form = admin.get(f"/ih/schichtbuch/meldung/{mid}/bearbeiten").text
    assert 'value="Pumpe laut"' in form
    admin.post(f"/ih/schichtbuch/meldung/{mid}/bearbeiten", data={"titel": "Pumpe laut (Lager)", "work_order": "", "prioritaet": "niedrig"})
    assert anzahl(eng, f"SELECT titel || '|' || prioritaet || '|' || coalesce(auftrag_id, '-') FROM sb_meldungen WHERE id={mid}") == "Pumpe laut (Lager)|niedrig|-"
    assert "Geändert: Titel" in admin.get(f"/ih/schichtbuch/meldung/{mid}").text


# ------------------------------------------------------------------ Einrichten
def test_einrichten_teams_zeiten_typen(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "sf", "schichtfuehrer")
    ih_benutzer(eng, "op", "operator")
    sf, op = _als(cfg, "sf"), _als(cfg, "op")
    assert op.get("/ih/schichtbuch/einrichten").status_code == 403
    assert op.post("/ih/schichtbuch/einrichten/teams", data={}).status_code == 403
    seite = sf.get("/ih/schichtbuch/einrichten").text
    assert "Grün" in seite and "Rot" in seite and "sf" in seite and "op" in seite
    g, b, ge, r = (_team_id(eng, n) for n in ("Grün", "Blau", "Gelb", "Rot"))
    alle = {f"name_{i}": n for i, n in ((g, "Grün"), (b, "Blau"), (ge, "Gelb"), (r, "Rot"))} | \
           {f"farbe_{i}": "#112233" for i in (g, b, ge, r)} | {f"aktiv_{i}": "on" for i in (g, b, ge, r)}
    # fünftes Team, Rot deaktivieren
    sf.post("/ih/schichtbuch/einrichten/teams", data={**{k: v for k, v in alle.items() if k != f"aktiv_{r}"}, "neu_name": "Weiß", "neu_farbe": "#eeeeee"})
    assert anzahl(eng, "SELECT group_concat(name || ':' || aktiv, ',') FROM (SELECT * FROM sb_teams ORDER BY reihenfolge)") == \
        "Grün:1,Blau:1,Gelb:1,Rot:0,Weiß:1"
    ohne_aktiv = {k: v for k, v in alle.items() if not k.startswith("aktiv")}
    for daten, meldung in [({**alle, f"name_{b}": "grün"}, "verschieden"), ({**alle, f"farbe_{g}": "rot"}, "#RRGGBB"), (ohne_aktiv, "aktiv bleiben")]:
        assert meldung in sf.post("/ih/schichtbuch/einrichten/teams", data=daten, follow_redirects=True).text, meldung
    # drei Schichten 06–14, 14–22, 22–06
    t, n = (anzahl(eng, "SELECT id FROM sb_zeiten WHERE name=:n", n=x) for x in ("Tag", "Nacht"))
    sf.post("/ih/schichtbuch/einrichten/zeiten", data={f"name_{t}": "Früh", f"beginn_{t}": "06:00", f"ende_{t}": "14:00", f"aktiv_{t}": "on",
                                                       f"name_{n}": "Nacht", f"beginn_{n}": "22:00", f"ende_{n}": "06:00", f"aktiv_{n}": "on",
                                                       "neu_name": "Spät", "neu_beginn": "14:00", "neu_ende": "22:00"})
    assert anzahl(eng, "SELECT group_concat(name || ' ' || beginn || '-' || ende, ', ') FROM sb_zeiten WHERE aktiv") == \
        "Früh 06:00-14:00, Nacht 22:00-06:00, Spät 14:00-22:00"
    from app.services import schichtbuch as sb
    with eng.connect() as con:
        assert sb.slot(con, datetime(2026, 11, 11, 15, 0))[1]["name"] == "Spät"
        assert sb.slot(con, datetime(2026, 11, 12, 1, 0))[0] == date(2026, 11, 11)
    r2 = sf.post("/ih/schichtbuch/einrichten/zeiten", data={f"name_{t}": "Früh", f"beginn_{t}": "06:00", f"ende_{t}": "15:00", f"aktiv_{t}": "on",
                                                            f"name_{n}": "Nacht", f"beginn_{n}": "22:00", f"ende_{n}": "06:00", f"aktiv_{n}": "on",
                                                            f"name_{n + 1}": "Spät", f"beginn_{n + 1}": "14:00", f"ende_{n + 1}": "22:00",
                                                            f"aktiv_{n + 1}": "on"}, follow_redirects=True)
    assert "überschneiden sich" in r2.text
    r2 = sf.post("/ih/schichtbuch/einrichten/zeiten", data={f"beginn_{t}": "25:00"}, follow_redirects=True)
    assert "HH:MM" in r2.text
    # Ereignistypen
    sf.post("/ih/schichtbuch/einrichten/typen", data={"typen": "Störung\nProbe\n\nStörung\n"})
    assert ">Probe</option>" in sf.get("/ih/schichtbuch/neu").text
    assert "Mindestens ein" in sf.post("/ih/schichtbuch/einrichten/typen", data={"typen": " "}, follow_redirects=True).text
    # Zuordnung lösen
    sf.post("/ih/schichtbuch/einrichten/mitglieder", data={f"team_{_uid(eng, 'op')}": g})
    sf.post("/ih/schichtbuch/einrichten/mitglieder", data={f"team_{_uid(eng, 'op')}": ""})
    assert anzahl(eng, "SELECT count(*) FROM sb_mitglieder") == 0


# ------------------------------------------------------------------ Rechte
ROUTEN = [("get", "/ih/schichtbuch", "ih.schichtbuch.ansehen"), ("get", "/ih/schichtbuch/meldungen", "ih.schichtbuch.ansehen"),
          ("get", "/ih/schichtbuch/export.xlsx", "ih.schichtbuch.ansehen"), ("get", "/ih/schichtbuch/meldung/1", "ih.schichtbuch.ansehen"),
          ("get", "/ih/schichtbuch/neu", "ih.schichtbuch.schreiben"), ("post", "/ih/schichtbuch/neu", "ih.schichtbuch.schreiben"),
          ("post", "/ih/schichtbuch/beginnen", "ih.schichtbuch.schreiben"), ("get", "/ih/schichtbuch/beenden", "ih.schichtbuch.schreiben"),
          ("post", "/ih/schichtbuch/beenden", "ih.schichtbuch.schreiben"), ("post", "/ih/schichtbuch/meldung/1/ergaenzen", "ih.schichtbuch.schreiben"),
          ("post", "/ih/schichtbuch/meldung/1/uebernehmen", "ih.schichtbuch.schreiben"), ("post", "/ih/schichtbuch/uebernehmen-alle", "ih.schichtbuch.schreiben"),
          ("get", "/ih/schichtbuch/meldung/1/bearbeiten", "ih.schichtbuch.schreiben"),
          ("get", "/ih/schichtbuch/einrichten", "ih.schichtbuch.einrichten"), ("post", "/ih/schichtbuch/einrichten/teams", "ih.schichtbuch.einrichten"),
          ("post", "/ih/schichtbuch/einrichten/zeiten", "ih.schichtbuch.einrichten"), ("post", "/ih/schichtbuch/einrichten/typen", "ih.schichtbuch.einrichten"),
          ("post", "/ih/schichtbuch/einrichten/mitglieder", "ih.schichtbuch.einrichten")]


def test_rechte_schichtbuch(env):
    from app.rechte import IH_ROLLEN, RECHTE
    cfg, eng = env
    cmms_an(cfg)
    for r in IH_ROLLEN:
        ih_benutzer(eng, f"ih_{r}", r)
    for r in IH_ROLLEN:
        c = _als(cfg, f"ih_{r}")
        for methode, pfad, recht in ROUTEN:
            status = getattr(c, methode)(pfad).status_code
            assert (status != 403) == (r in RECHTE[recht]), (r, pfad, status)
    # Lager ohne CMMS-Rolle: kein Zugriff; CMMS aus: nichts erreichbar
    assert client(cfg, "lager").get("/ih/schichtbuch").status_code == 403
    cfg.cmms.aktiv = False
    assert client(cfg, "admin").get("/ih/schichtbuch").status_code == 403
