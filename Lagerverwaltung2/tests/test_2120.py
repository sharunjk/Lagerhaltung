"""2.12.0: Sets im Lager (Inhalt, Teil-Entnahme mit Warnung „Set unvollständig“) und Montageunterstützung
(Stutzenübersicht, Import aus der Excel-Vorlage, Montageprotokoll mit Skizze, „#“, Abschluss, Korrektur, Druck, Excel).
Alle Daten erfunden – nur das Format der Vorlage ist nachgebildet."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date

import pytest
from sqlalchemy import select, text

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import L, anzahl, client, schreib


# ------------------------------------------------------------------ Sets
def _teile(eng):
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "9001", "bezeichnung": "Pulsationsdämpfer Demo"}, "A1-R1-1", 3)
        L(con).artikel_anlegen({"nummer": "9002", "bezeichnung": "Flachdichtung Demo"}, "", 0)
        L(con).artikel_anlegen({"nummer": "9003", "bezeichnung": "O-Ring Demo"}, "", 0)


def _set_anlegen(admin, nummer="9100", bestand="2"):
    return admin.post("/artikel/neu", data={"nummer": nummer, "bezeichnung": "Ersatzteilset Pumpenmodul Demo", "platz": "B2-R1-1",
                                            "anfangsbestand": bestand, "set_bearbeitet": "1", "ist_set": "on",
                                            "set_teil": ["9001 – Pulsationsdämpfer Demo", "9002", "9003", ""], "set_menge": ["1", "4", "2", "1"]})


def test_set_anlegen_inhalt_und_anzeige(env):
    cfg, eng = env
    _teile(eng)
    admin = client(cfg, "admin")
    r = _set_anlegen(admin)
    assert r.status_code == 303, r.text[:500]
    assert anzahl(eng, "SELECT count(*) FROM artikel_set_inhalt") == 3
    assert anzahl(eng, "SELECT ist_set FROM artikel WHERE nummer='9100'") == 1
    seite = admin.get("/artikel/9100").text
    assert "Inhalt des Sets" in seite and "Pulsationsdämpfer Demo" in seite and "Vollständig" in seite
    teil = admin.get("/artikel/9002").text
    assert "Auch enthalten in Sets" in teil and "9100" in teil and "2 Set(s) auf Lager" in teil
    # Bestand der Teile bleibt unberührt
    assert anzahl(eng, "SELECT coalesce(sum(menge),0) FROM bestand b JOIN artikel a ON a.id=b.artikel_id WHERE a.nummer='9002'") == 0
    # Bearbeiten-Formular zeigt den Inhalt
    form = admin.get("/artikel/9100/bearbeiten").text
    assert "9001 – Pulsationsdämpfer Demo" in form and "Inhalt des Sets" in form
    # unbekanntes Teil, Set im Set, Set enthält sich selbst: abgelehnt
    r = admin.post("/artikel/9100/bearbeiten", data={"bezeichnung": "Set", "set_bearbeitet": "1", "ist_set": "on", "set_teil": ["7777"], "set_menge": ["1"]})
    assert "7777 gibt es nicht" in r.text
    _set_anlegen(admin, "9101", "0")
    r = admin.post("/artikel/9100/bearbeiten", data={"bezeichnung": "Set", "set_bearbeitet": "1", "ist_set": "on", "set_teil": ["9101"], "set_menge": ["1"]})
    assert "selbst ein Set" in r.text
    r = admin.post("/artikel/9100/bearbeiten", data={"bezeichnung": "Set", "set_bearbeitet": "1", "ist_set": "on", "set_teil": ["9100"], "set_menge": ["1"]})
    assert "nicht selbst enthalten" in r.text
    assert anzahl(eng, "SELECT count(*) FROM artikel_set_inhalt s JOIN artikel a ON a.id=s.set_id WHERE a.nummer='9100'") == 3
    # Teil, das in einem Set steckt, lässt sich nicht löschen
    r = admin.post("/artikel/9003/loeschen", data={"bestaetigung": "9003"}, follow_redirects=True)
    assert anzahl(eng, "SELECT count(*) FROM artikel WHERE nummer='9003'") == 1 and "Set-Inhalt" in r.text


def test_set_teilentnahme_warnung_und_erledigen(env):
    cfg, eng = env
    _teile(eng)
    admin = client(cfg, "admin")
    _set_anlegen(admin)
    lager = client(cfg, "lager")
    assert client(cfg, "lesen").post("/artikel/9100/set/teil-entnehmen", data={"teil": "9001", "menge": "1"}).status_code == 403
    r = lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9001", "menge": "1", "platz": "B2-R1-1", "empfaenger": "Max", "zweck": "Pumpe P1"},
                   follow_redirects=True)
    assert "unvollständig" in r.text and "Set unvollständig" in r.text
    assert anzahl(eng, "SELECT count(*) FROM set_fehlteile WHERE erledigt_am IS NULL") == 1
    assert anzahl(eng, "SELECT sum(menge) FROM bestand b JOIN artikel a ON a.id=b.artikel_id WHERE a.nummer='9100'") == 2  # Set-Bestand bleibt
    # mehr als drin ist: abgelehnt (2 Sets × 1 Pulsationsdämpfer, 1 schon heraus)
    r = lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9001", "menge": "2", "platz": "B2-R1-1"}, follow_redirects=True)
    assert "noch 1 × 9001" in r.text
    # Teil, das nicht zum Set gehört / falscher Platz
    assert "gehört nicht zum Set" in lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "4711", "menge": "1"}, follow_redirects=True).text
    assert "kein Set" in lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9002", "menge": "1", "platz": "Z9-R9-9"}, follow_redirects=True).text
    # Warnung beim Buchen (PC und Handscanner)
    assert "Set unvollständig" in lager.get("/buchen/panel?artikel=9100&typ=ausgang").text
    assert "fehlteil_erledigt" in lager.get("/buchen/panel?artikel=9100&typ=ausgang").text
    assert "Set unvollständig" in lager.get("/m/artikel/9100").text
    # ganzes Set entnehmen (nicht das unvollständige): Warnung bleibt in der Erfolgsmeldung
    r = lager.post("/buchen", data={"artikel": "9100", "typ": "ausgang", "menge": "1", "lagerort": "B2-R1-1"}, follow_redirects=True)
    assert "Set unvollständig" in r.text
    assert anzahl(eng, "SELECT count(*) FROM set_fehlteile WHERE erledigt_am IS NULL") == 1
    # aus dem Lager nachlegen: bucht eine Entnahme des Teils
    fid = anzahl(eng, "SELECT id FROM set_fehlteile")
    r = lager.post(f"/artikel/9100/set/fehlteil/{fid}", data={"art": "aus_lager"}, follow_redirects=True)
    assert "aus dem Lager nachgelegt" in r.text
    assert anzahl(eng, "SELECT sum(menge) FROM bestand b JOIN artikel a ON a.id=b.artikel_id WHERE a.nummer='9001'") == 2
    assert anzahl(eng, "SELECT zweck FROM bewegungen WHERE artikel_nr='9001' AND typ='ausgang'") == "In Set 9100 nachgelegt"
    assert "Vollständig" in lager.get("/artikel/9100").text
    # unvollständiges Set entnommen: mit Haken das Fehlteil schließen
    lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9002", "menge": "2", "platz": "B2-R1-1"})
    fid = anzahl(eng, "SELECT id FROM set_fehlteile WHERE erledigt_am IS NULL")
    r = lager.post("/buchen", data={"artikel": "9100", "typ": "ausgang", "menge": "1", "lagerort": "B2-R1-1", "fehlteil_erledigt": str(fid)}, follow_redirects=True)
    assert "Set unvollständig" not in r.text
    assert anzahl(eng, "SELECT erledigt_art FROM set_fehlteile WHERE id=:i", i=fid) == "set_entnommen"
    # kein Set mehr auf Lager: offene Fehlteile sind gegenstandslos
    with schreib(eng) as con:
        L(con).eingang("9100", "B2-R1-1", 1)
    lager.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9003", "menge": "1", "platz": "B2-R1-1"})
    lager.post("/buchen", data={"artikel": "9100", "typ": "ausgang", "menge": "1", "lagerort": "B2-R1-1"})
    assert anzahl(eng, "SELECT count(*) FROM set_fehlteile WHERE erledigt_am IS NULL") == 0
    assert anzahl(eng, "SELECT count(*) FROM set_fehlteile WHERE erledigt_art='kein_bestand'") == 1
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Teil aus Set entnommen'") == 3


def test_set_abwaehlen_nur_ohne_fehlteile(env):
    cfg, eng = env
    _teile(eng)
    admin = client(cfg, "admin")
    _set_anlegen(admin)
    admin.post("/artikel/9100/set/teil-entnehmen", data={"teil": "9001", "menge": "1", "platz": "B2-R1-1"})
    r = admin.post("/artikel/9100/bearbeiten", data={"bezeichnung": "Set", "set_bearbeitet": "1"})
    assert "fehlende Teile" in r.text and anzahl(eng, "SELECT ist_set FROM artikel WHERE nummer='9100'") == 1
    fid = anzahl(eng, "SELECT id FROM set_fehlteile")
    admin.post(f"/artikel/9100/set/fehlteil/{fid}", data={"art": "nachgelegt"})
    admin.post("/artikel/9100/bearbeiten", data={"bezeichnung": "Set", "set_bearbeitet": "1"})
    assert anzahl(eng, "SELECT ist_set FROM artikel WHERE nummer='9100'") == 0
    assert anzahl(eng, "SELECT count(*) FROM artikel_set_inhalt") == 0
    # Formular ohne Set-Bereich (z. B. Handy) ändert nichts am Set
    _set_anlegen(admin, "9102", "0")
    admin.post("/artikel/9102/bearbeiten", data={"bezeichnung": "Neu benannt"})
    assert anzahl(eng, "SELECT ist_set FROM artikel WHERE nummer='9102'") == 1 and anzahl(eng, "SELECT count(*) FROM artikel_set_inhalt") == 3


# ------------------------------------------------------------------ Montage: Stutzenübersicht
def vorlage_xlsx() -> bytes:
    """Nachbildung der Excel-Vorlage (Blätter „Stutzen Übersicht“ und „Zuordnung Dichtungen“) mit erfundenen Werten."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Stutzen Übersicht"
    ws["A1"] = "Stutzen Übersicht"
    ws.append(["Bezeichnung", "Stutzen", "Dichtungsart", "Dichtungsdurchmesser", "Auftragsnummer", "Soll Drehmoment [Nm]", "Schrauben Länge Soll [mm]"])
    ws.append(["Demo-Stutzen", "DS 1", "MCR", " Ø100MM", "DEMO MCI-7-3,18w-0099,68", 120, 100, "M20"])
    ws.append(["Demo-Stutzen", "DS 1", "MCR", "Ø80MM", "DEMO MCI-7-3,18w-0079,68-1O", 120, 100, "M20"])
    ws.append(["Fühlerstutzen", "DF 1", "Dichtscheibe", "1 Zoll", "XX-16-DEMO*", 180])
    ws.append([None, "Zweite Gruppe"])
    ws.append(["Großflansch", "GF", "MCR", "Ø900MM", "DEMO MCI-7-6,35w-0899,36-1O", 1800, "250?", "M42"])
    ws.append(["Großflansch", "GF", "VOR", "Ø950MM", "O-Ring Demo 950x6"])
    ws.append([None, "Dritte Gruppe"])
    ws.append(["Gaszufuhr innen", "N1", "MCR", None, None, "30-40", None, "M16"])
    ws.append(["Gaszufuhr außen", "N1", "MCR", None, None, "90-110", None, "M20"])
    z = wb.create_sheet("Zuordnung Dichtungen")
    z["A1"] = "Zuordnung Dichtungen"
    z.append(["Stutzen", "Bezeichnung", "Dichtungsart", "Dichtungsdurchmesser", "Auftragsnummer", "Menge", "Dicke- Soll [mm]", "Dicke-Ist [mm]"])
    z.append(["DS", "Demo-Stutzen", "MCR", " Ø100MM", "DEMO MCI-7-3,18w-0099,68", 8, 3.2, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import(c, **extra):
    return c.post("/ih/montage/stutzen-import", files={"datei": ("Vorlage.xlsx", vorlage_xlsx(), "application/octet-stream")},
                  data={"gruppe_anfang": "Reaktor", **extra})


def test_stutzen_import_aus_vorlage(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "sf", "schichtfuehrer")
    ih_benutzer(eng, "op", "operator")
    sf = client(cfg, "sf")
    assert client(cfg, "op").get("/ih/montage/stutzen-import").status_code == 403
    # Vorschau speichert nichts
    r = _import(sf, probe="1")
    assert "Vorschau: 5 Stutzen" in r.text and anzahl(eng, "SELECT count(*) FROM mt_stutzen") == 0
    r = _import(sf)
    assert r.status_code == 200 and "5 Stutzen neu angelegt" in r.text, r.text[-800:]
    with eng.connect() as con:
        st = {(s.gruppe, s.kuerzel, s.bezeichnung): s for s in con.execute(text("SELECT * FROM mt_stutzen"))}
        assert set(st) == {("Reaktor", "DS 1", "Demo-Stutzen"), ("Reaktor", "DF 1", "Fühlerstutzen"), ("Zweite Gruppe", "GF", "Großflansch"),
                           ("Dritte Gruppe", "N1", "Gaszufuhr innen"), ("Dritte Gruppe", "N1", "Gaszufuhr außen")}
        ds = st[("Reaktor", "DS 1", "Demo-Stutzen")]
        assert (ds.drehmoment, ds.schraube_laenge, ds.gewinde) == ("120", "100", "M20")
        d = con.execute(text("SELECT pos, dichtungsart, durchmesser, artikel_nr, nenndicke FROM mt_stutzen_dichtungen WHERE stutzen_id=:i ORDER BY pos"),
                        {"i": ds.id}).all()
        assert [tuple(x) for x in d] == [(1, "MCR", "Ø100MM", "DEMO MCI-7-3,18w-0099,68", 3.2), (2, "MCR", "Ø80MM", "DEMO MCI-7-3,18w-0079,68-1O", 3.18)]
        gf = st[("Zweite Gruppe", "GF", "Großflansch")]
        assert gf.schraube_laenge == "250?" and gf.gewinde == "M42"
        assert con.execute(text("SELECT nenndicke FROM mt_stutzen_dichtungen WHERE stutzen_id=:i AND pos=1"), {"i": gf.id}).scalar() == 6.35
        assert st[("Dritte Gruppe", "N1", "Gaszufuhr innen")].drehmoment == "30-40"
    seite = sf.get("/ih/montage/stutzen").text
    assert "ungeklärt" in seite and "Zweite Gruppe" in seite and "DS 1" in seite
    assert "Gaszufuhr außen" in sf.get("/ih/montage/stutzen?q=außen").text and "Demo-Stutzen" not in sf.get("/ih/montage/stutzen?q=außen").text
    # Anzahl Schrauben im System nachgetragen – erneuter Import: nichts doppelt, Eintrag bleibt
    sf.post(f"/ih/montage/stutzen/{ds.id}/bearbeiten", data={"kuerzel": "DS 1", "bezeichnung": "Demo-Stutzen", "gruppe": "Reaktor", "schrauben_anzahl": "8",
                                                             "gewinde": "M20", "schraube_laenge": "100", "drehmoment": "120", "d0_dichtungsart": "MCR",
                                                             "d0_durchmesser": "Ø100MM", "d0_artikel_nr": "DEMO MCI-7-3,18w-0099,68", "d0_nenndicke": "3,2"})
    r = _import(sf)
    assert "0 Stutzen neu" in r.text and anzahl(eng, "SELECT count(*) FROM mt_stutzen") == 5
    assert anzahl(eng, "SELECT schrauben_anzahl FROM mt_stutzen WHERE kuerzel='DS 1'") == 8
    assert anzahl(eng, "SELECT count(*) FROM mt_stutzen_dichtungen WHERE stutzen_id=:i", i=ds.id) == 2  # aus der Datei wiederhergestellt
    # Export
    ex = sf.get("/ih/montage/stutzen/export.xlsx")
    assert ex.status_code == 200 and ex.content[:2] == b"PK"
    # falsche Datei
    r = sf.post("/ih/montage/stutzen-import", files={"datei": ("x.xlsx", b"kein excel", "application/octet-stream")}, follow_redirects=True)
    assert "nicht als Excel-Datei" in r.text


def _stutzen(eng, n=8):
    from app.services import montage as mt
    with schreib(eng) as con:
        return mt.stutzen_speichern(con, None, {"kuerzel": "DS 1", "bezeichnung": "Demo-Stutzen", "gruppe": "Reaktor", "schrauben_anzahl": n,
                                                "gewinde": "M20", "schraube_laenge": "100", "drehmoment": "120", "schraube_typ": "ISO 4014",
                                                "schraube_werkstoff": "A4-70", "anlage": "Demo-Reaktor"},
                                    [{"dichtungsart": "MCR", "durchmesser": "Ø100MM", "artikel_nr": "DEMO-100", "nenndicke": 3.18},
                                     {"dichtungsart": "MCR", "durchmesser": "Ø80MM", "artikel_nr": "DEMO-80", "nenndicke": "3,18"}], "Tester")


def _protokoll_daten(sid, n=8, **extra):
    d = {"stutzen_id": str(sid), "anlage": "Demo-Reaktor", "datum": "2026-11-13", "monteur": "M. Muster", "pruefer": "P. Prüfer",
         "arbeitsauftrag": "WO-DEMO-1", "reinigung": "Dichtflächen gereinigt", "schmiermittel": "Demo-Paste", "schrauben_anzahl": str(n),
         "d0_dichtungsart": "MCR Ø100MM", "d0_artikel_nr": "DEMO-100", "d0_nenndicke": "3,18", "d0_alt_neu": "neu",
         "d1_dichtungsart": "MCR Ø80MM", "d1_artikel_nr": "DEMO-80", "d1_nenndicke": "3,18", "aktion": "speichern", "reihenfolge": "[]"}
    for i in range(n):
        d.update({f"s{i}_typ": "ISO 4014" if i == 0 else "#", f"s{i}_groesse": "M20" if i == 0 else "#", f"s{i}_laenge_soll": "100" if i == 0 else "#",
                  f"s{i}_werkstoff": "A4-70" if i == 0 else "#", f"s{i}_soll_nm": "120" if i == 0 else "#", f"s{i}_alt_neu": "neu"})
    d.update(extra)
    return d


def test_protokoll_ablauf_zwei_schritte_abschluss_korrektur(env):
    cfg, eng = env
    cmms_an(cfg)
    for name, rolle in (("op", "operator"), ("ing", "ingenieur"), ("le", "lesen")):
        ih_benutzer(eng, name, rolle)
    sid = _stutzen(eng)
    op = client(cfg, "op")
    # Vorbelegung aus der Stutzenübersicht
    form = op.get(f"/ih/montage/protokolle/neu?stutzen={sid}").text
    assert '"soll_nm": "120"' in form and '"soll_nm": "#"' in form and '"nenndicke": "3,18"' in form and "Demo-Reaktor" in form
    assert client(cfg, "le").get("/ih/montage/protokolle/neu").status_code == 403
    # Schritt 1: vor der Montage – Kopf und Dichtungen, zwischenspeichern
    r = op.post("/ih/montage/protokolle/neu", data=_protokoll_daten(sid))
    assert r.status_code == 303, r.text[-600:]
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    with eng.connect() as con:
        p = con.execute(text("SELECT * FROM mt_protokolle WHERE id=:i"), {"i": pid}).mappings().first()
    assert p["status"] == "entwurf" and p["nummer"] == "MP-2026-0001" and p["stutzen"] == "DS 1" and p["schrauben_anzahl"] == 8
    schr = json.loads(p["schrauben"])
    assert len(schr) == 8 and all(z["soll_nm"] == "120" and z["groesse"] == "M20" for z in schr)  # „#“ aufgelöst
    # Liste zeigt den Entwurf mit offenen Drehmomenten
    assert "8 von 8 Ist-Drehmomenten offen" in op.get("/ih/montage/protokolle").text
    # Schritt 2: nach der Montage – Reihenfolge (über Kreuz) und Ist-Drehmomente nachtragen
    folge = [1, 5, 3, 7, 2, 6, 4, 8]
    stand = op.get(f"/ih/montage/protokolle/{pid}").text
    m = re.search(r'name="stand" value="([^"]+)"', stand)
    ist = {f"s{i}_ist_nm": ("118" if i == 0 else "#") for i in range(8)}
    r = op.post(f"/ih/montage/protokolle/{pid}", data=_protokoll_daten(sid, reihenfolge=json.dumps(folge), stand=m.group(1), **ist))
    assert r.status_code == 303
    with eng.connect() as con:
        p = con.execute(text("SELECT * FROM mt_protokolle WHERE id=:i"), {"i": pid}).mappings().first()
    assert json.loads(p["reihenfolge"]) == folge and all(z["ist_nm"] == "118" for z in json.loads(p["schrauben"]))
    # Konflikt: veralteter Stand wird nicht still überschrieben
    r = op.post(f"/ih/montage/protokolle/{pid}", data=_protokoll_daten(sid, stand=m.group(1), monteur="Jemand"))
    assert "inzwischen" in r.text and anzahl(eng, "SELECT monteur FROM mt_protokolle") == "M. Muster"
    # Abschließen mit fehlenden Angaben: gespeichert, aber nicht abgeschlossen
    r = op.post(f"/ih/montage/protokolle/{pid}", data=_protokoll_daten(sid, reihenfolge=json.dumps(folge), aktion="abschliessen", **ist), follow_redirects=True)
    assert "noch nicht abgeschlossen" in r.text and "Lecktest" in r.text and "Trotzdem abschließen" in r.text
    assert anzahl(eng, "SELECT status FROM mt_protokolle") == "entwurf"
    r = op.post(f"/ih/montage/protokolle/{pid}", data=_protokoll_daten(sid, reihenfolge=json.dumps(folge), aktion="abschliessen", montage_abgeschlossen="ja",
                                                                          lecktest="bestanden", abschluss_zeit="13.11.2026 14:05", **ist), follow_redirects=True)
    assert "abgeschlossen" in r.text and anzahl(eng, "SELECT status FROM mt_protokolle") == "abgeschlossen"
    # Abgeschlossen: Operator kann nicht mehr ändern, sieht nur die Ansicht
    seite = op.get(f"/ih/montage/protokolle/{pid}").text
    assert "Zwischenspeichern" not in seite and "MONTAGEPROTOKOLL" in seite and "DS1-1-118 Nm" in seite
    r = op.post(f"/ih/montage/protokolle/{pid}", data=_protokoll_daten(sid, monteur="X"))
    assert "abgeschlossen" in r.text and anzahl(eng, "SELECT monteur FROM mt_protokolle") == "M. Muster"
    assert op.post(f"/ih/montage/protokolle/{pid}/oeffnen", data={"grund": "x"}).status_code == 403
    assert op.post(f"/ih/montage/protokolle/{pid}/loeschen").status_code == 303 and anzahl(eng, "SELECT count(*) FROM mt_protokolle") == 1
    # Ingenieur korrigiert – nur mit Grund, Änderung steht im Verlauf
    ing = client(cfg, "ing")
    assert "Grund der Änderung" in ing.get(f"/ih/montage/protokolle/{pid}?korrektur=1").text
    neu = {**ist, "s2_ist_nm": "121", "s3_ist_nm": "118"}  # nur Pos. 3 ändern: Pos. 4 explizit, sonst gilt „#“ = 121
    korr = _protokoll_daten(sid, reihenfolge=json.dumps(folge), montage_abgeschlossen="ja", lecktest="bestanden", abschluss_zeit="13.11.2026 14:05", **neu)
    assert "Grund" in ing.post(f"/ih/montage/protokolle/{pid}", data=korr).text
    r = ing.post(f"/ih/montage/protokolle/{pid}", data={**korr, "grund": "Pos. 3 falsch abgelesen"})
    assert r.status_code == 303
    with eng.connect() as con:
        v = con.execute(text("SELECT * FROM mt_verlauf WHERE art='korrigiert'")).mappings().first()
        schr = json.loads(con.execute(text("SELECT schrauben FROM mt_protokolle")).scalar())
    assert v["grund"] == "Pos. 3 falsch abgelesen" and ["Schraube Pos. 3 Ist [Nm]", "118", "121"] in json.loads(v["aenderungen"])
    assert [z["ist_nm"] for z in schr] == ["118", "118", "121", "118", "118", "118", "118", "118"]  # „#“ bezieht sich auf die Zeile darüber
    assert anzahl(eng, "SELECT status FROM mt_protokolle") == "abgeschlossen"
    # Wieder öffnen (Ingenieur) -> Operator kann ergänzen
    ing.post(f"/ih/montage/protokolle/{pid}/oeffnen", data={"grund": "Lecktest wiederholt"})
    assert anzahl(eng, "SELECT status FROM mt_protokolle") == "entwurf"
    assert "Zwischenspeichern" in op.get(f"/ih/montage/protokolle/{pid}").text
    # Übersicht je Stutzen
    assert "MP-2026-0001" in op.get(f"/ih/montage/stutzen/{sid}").text


def test_druck_und_excel_mit_skizze_und_zeilen_je_schraube(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "op", "operator")
    sid = _stutzen(eng, n=8)
    op = client(cfg, "op")
    folge = [1, 5, 3, 7]
    ist = {f"s{i}_ist_nm": ("118" if i == 0 else "#") for i in range(8)}
    r = op.post("/ih/montage/protokolle/neu", data=_protokoll_daten(sid, reihenfolge=json.dumps(folge), **ist))
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    d = op.get(f"/ih/montage/protokolle/{pid}/druck").text
    assert d.count('stroke-width="1"/>') == 8  # 8 Löcher
    assert "POSITIONEN 1 BIS 8" in d and d.count("DS1-") == 8 and "Demo-Stutzen" in d
    assert ">#<" in d  # Wiederholungen als „#“
    for nr in ("1", "2", "3", "4"):
        assert f'fill="#C00000" text-anchor="middle" dominant-baseline="central">{nr}</text>' in d
    # Excel: genau 8 Schraubenzeilen, Zeichnung mit 8 Löchern + Ring + Öffnung, 4 Nummern
    x = op.get(f"/ih/montage/protokolle/{pid}/excel")
    assert x.status_code == 200 and "MP-2026-0001" in x.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(x.content))
    zeichnung = z.read("xl/drawings/drawing_skizze.xml").decode()
    assert zeichnung.count('prst="ellipse"') == 10 and zeichnung.count("<a:t>") == 4
    assert "drawing_skizze.xml" in z.read("xl/worksheets/_rels/sheet1.xml.rels").decode()
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A15"].value == "SCHRAUBEN – POSITIONEN 1 BIS 8"
    assert [ws.cell(17 + i, 1).value for i in range(8)] == list(range(1, 9)) and ws.cell(25, 1).value is None
    assert ws["B17"].value == "DS1-1-118 Nm" and ws["M17"].value == 120 and ws["M18"].value == "#" and ws["N18"].value == "#"
    assert ws["H3"].value.startswith("DS 1") and ws["N3"].value == "13.11.2026"
    assert ws.page_setup.orientation == "portrait" and ws.page_setup.fitToHeight == 1
    # leeres Blatt mit gewünschter Anzahl
    b = op.get("/ih/montage/protokolle/blanko?n=12").text
    assert b.count('stroke-width="1"/>') == 12 and "POSITIONEN 1 BIS 12" in b


def test_skizze_geometrie_und_ditto():
    from app.services import montage as mt
    g = mt.skizze(8, [3, 1])
    l1 = g["loecher"][0]
    assert abs(l1["x"] - g["cx"]) < 0.01 and l1["y"] < g["cy"]  # Loch 1 oben
    assert g["loecher"][2]["pos"] == 1 and g["loecher"][0]["pos"] == 2 and g["loecher"][1]["pos"] is None
    assert g["loecher"][2]["x"] > g["cx"] and abs(g["loecher"][2]["y"] - g["cy"]) < 0.01  # Loch 3 rechts (im Uhrzeigersinn)
    assert not mt.skizze(20)["aussen"] and mt.skizze(40)["aussen"]
    zeilen = mt.ditto_aufloesen([{"soll_nm": "120", "ist_nm": "118"}, {"soll_nm": "#", "ist_nm": "#"}, {"soll_nm": "#", "ist_nm": "121"}, {"soll_nm": "#", "ist_nm": "#"}])
    assert [z["ist_nm"] for z in zeilen] == ["118", "118", "121", "121"] and {z["soll_nm"] for z in zeilen} == {"120"}
    assert [z["ist_nm"] for z in mt.ditto_anzeige(zeilen)] == ["118", "#", "121", "#"]
    assert mt.kennzeichnung("RO", 1, "65") == "RO-1-65 Nm" and mt.kennzeichnung("RL 1", 3, "") == "RL1-3"


def test_rechte_montage(env):
    cfg, eng = env
    cmms_an(cfg)
    for name, rolle in (("le", "lesen"), ("op", "operator"), ("sf", "schichtfuehrer")):
        ih_benutzer(eng, name, rolle)
    sid = _stutzen(eng)
    le, op, sf = client(cfg, "le"), client(cfg, "op"), client(cfg, "sf")
    assert le.get("/ih/montage/stutzen").status_code == 200 and le.get(f"/ih/montage/stutzen/{sid}").status_code == 200
    assert le.post("/ih/montage/protokolle/neu", data=_protokoll_daten(sid)).status_code == 403
    assert op.get("/ih/montage/stutzen/neu").status_code == 403
    assert op.post(f"/ih/montage/stutzen/{sid}/archivieren", data={}).status_code == 403
    r = sf.post("/ih/montage/stutzen/neu", data={"kuerzel": "XY", "bezeichnung": "Neuer Demo", "schrauben_anzahl": "12"})
    assert r.status_code == 303 and anzahl(eng, "SELECT count(*) FROM mt_stutzen") == 2
    assert "gibt es schon" in sf.post("/ih/montage/stutzen/neu", data={"kuerzel": "XY", "bezeichnung": "Neuer Demo"}).text
    assert "ganze Zahl" in sf.post("/ih/montage/stutzen/neu", data={"kuerzel": "XZ", "schrauben_anzahl": "0"}).text
    # Menü zeigt den Reiter mit Unterpunkten
    seite = op.get("/ih/montage/stutzen").text
    assert "Montageunterstützung" in seite and "Stutzenübersicht" in seite and "Montageprotokolle" in seite
    # CMMS aus: nicht erreichbar
    cfg.cmms.aktiv = False
    assert client(cfg, "admin").get("/ih/montage/stutzen").status_code in (403, 303)
