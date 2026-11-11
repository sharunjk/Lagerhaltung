"""2.5.0 – Phase 0 der CMMS-Erweiterung: Migrationen, Rechte je Modul, Modulwahl, Asset-Import.

Testdaten sind erfunden und bilden nur das Format der echten Asset-Liste nach (SharePoint-Export, Instandhaltungsplan).
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, select

from test_pruefung import L, anzahl, client, schreib


def ih_benutzer(eng, name, rolle_ih, rolle="keine"):
    from app.db import benutzer_rollen, users
    from app.services.betrieb import hash_pw
    with schreib(eng) as con:
        uid = con.execute(insert(users).values(username=name, anzeigename=name, pw_hash=hash_pw("Lager-Test-2026"), rolle=rolle,
                                               aktiv=True)).inserted_primary_key[0]
        if rolle_ih:
            con.execute(insert(benutzer_rollen).values(user_id=uid, modul="ih", rolle=rolle_ih))


def cmms_an(cfg):
    cfg.cmms.aktiv = True


# ------------------------------------------------------------------ Migrationen
def _alte_datenbank(pfad: Path):
    """Datenbank im Stand 2.4.0: ohne neue Spalten und ohne schema_version."""
    con = sqlite3.connect(str(pfad))
    con.execute("DROP TABLE schema_version")
    for t, s in (("bewegungen", "preis"), ("bewegungen", "auftrag_id"), ("reservierungen", "auftrag_id")):
        con.execute(f"ALTER TABLE {t} DROP COLUMN {s}")
    for t in ("sb_verlauf", "sb_meldungen", "sb_schichten", "sb_mitglieder", "sb_zeiten", "sb_teams", "ih_stueckliste", "ih_kampagne_bauteile", "ih_dokumente", "ih_statuslog", "ih_auftrag_positionen", "ih_auftraege", "ih_kampagnen", "ih_klassen_intervalle",
              "ih_massnahmen", "ih_import_zeilen", "ih_import_laeufe", "ih_plaetze", "benutzer_rollen"):
        con.execute(f"DROP TABLE {t}")
    con.commit()
    con.close()


def test_neue_datenbank_hat_alle_migrationen(env):
    cfg, eng = env
    with eng.connect() as con:
        assert [r[0] for r in con.exec_driver_sql("SELECT version FROM schema_version")] == [1, 2, 3]
        spalten = {r[1] for r in con.exec_driver_sql("PRAGMA table_info(bewegungen)")}
    assert {"preis", "auftrag_id"} <= spalten


def test_update_von_2_4_probelauf_sicherung_und_daten_unveraendert(env):
    from app import db, migrationen
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Kugelhahn", "preis": 12.5}, "C1-R1-1", 7)
        L(con).ausgang("1", "C1-R1-1", 2)
    eng.dispose()
    datei = cfg.path(cfg.daten.datenbank)
    _alte_datenbank(datei)
    con = sqlite3.connect(str(datei))
    vorher = migrationen.kennzahlen(con)
    con.close()
    assert migrationen._datei_ausstehend(datei) == [1, 2, 3]
    name = migrationen.vor_start(cfg)
    assert name.startswith("vor_update_") and (cfg.path(cfg.backup.ordner) / name).exists()
    db.init_engine(cfg.db_url)  # führt die Migration aus
    con = sqlite3.connect(str(datei))
    try:
        assert migrationen.kennzahlen(con) == vorher
        assert {"preis", "auftrag_id"} <= {r[1] for r in con.execute("PRAGMA table_info(bewegungen)")}
        assert con.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 3
    finally:
        con.close()
    assert migrationen._datei_ausstehend(datei) == []
    assert migrationen.vor_start(cfg) is None  # nichts mehr offen: keine weitere Sicherung
    db.init_engine(cfg.db_url)  # wiederholbar


def test_probelauf_bricht_ab_wenn_lagerdaten_sich_aendern_wuerden(env, monkeypatch):
    from app import migrationen
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "X"}, "C1-R1-1", 5)
    eng.dispose()
    datei = cfg.path(cfg.daten.datenbank)
    _alte_datenbank(datei)
    kaputt = lambda con: con.exec_driver_sql("UPDATE bestand SET menge = menge + 1")  # noqa: E731
    monkeypatch.setattr(migrationen, "MIGRATIONEN", [*migrationen.MIGRATIONEN, (99, "fehlerhaft", kaputt)])
    with pytest.raises(migrationen.MigrationsFehler, match="Lagerdaten"):
        migrationen.vor_start(cfg)
    con = sqlite3.connect(str(datei))
    try:  # echte Datenbank unberührt: weiter Stand 2.4, Bestand 5
        assert con.execute("SELECT menge FROM bestand").fetchone()[0] == 5
        assert "schema_version" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    finally:
        con.close()
    with pytest.raises(migrationen.MigrationsFehler):
        client(cfg)  # das Programm startet nicht mit halber Aktualisierung


def test_wiederherstellen_alter_sicherung_ergaenzt_spalten(env):
    from app import db
    from app.services import sicherung
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "X"}, "C1-R1-1", 1)
    alt = Path(cfg.path(cfg.backup.ordner)) / "alt"
    alt.mkdir(parents=True)
    eng.dispose()
    _alte_datenbank(cfg.path(cfg.daten.datenbank))
    datei = sicherung.einzel_sicherung(cfg, alt, name="lager_sicherung")
    eng = db.init_engine(cfg.db_url)
    sicherung.wiederherstellen(cfg, eng, datei, "admin")
    with eng.connect() as con:
        assert "preis" in {r[1] for r in con.exec_driver_sql("PRAGMA table_info(bewegungen)")}
        assert con.exec_driver_sql("SELECT count(*) FROM artikel").scalar() == 1


def test_buchung_speichert_preis(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "X", "preis": 19.27}, "C1-R1-1", 3)
        L(con).ausgang("1", "C1-R1-1", 1)
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE preis = 19.27") == 2


# ------------------------------------------------------------------ Rechte und Modulwahl
def test_cmms_aus_aendert_nichts(env):
    cfg, eng = env
    c = client(cfg, "admin")
    assert c.get("/ih").status_code == 403
    seite = c.get("/").text
    assert "Instandhaltung" not in seite and "/bereich/" not in seite
    assert "Rolle Instandhaltung" not in c.get("/einstellungen?tab=benutzer").text
    assert client(cfg, "lager").post("/login", data={"username": "lager", "passwort": "Lager-Test-2026"}).headers["location"] == "/"


@pytest.mark.parametrize("rolle,ansehen,importieren", [("admin", 200, 200), ("lager", 403, 403), ("lesen", 403, 403)])
def test_lager_rollen_im_cmms(env, rolle, ansehen, importieren):
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, rolle)
    assert c.get("/ih").status_code == ansehen
    assert c.get("/ih/import").status_code == importieren


IH_ROUTEN = [("get", "/ih", "ih.ansehen"), ("get", "/ih/anlagen", "ih.ansehen"), ("get", "/ih/anlagen/1", "ih.ansehen"),
             ("get", "/ih/anlagen/1/bearbeiten", "ih.anlagen.pflegen"), ("post", "/ih/anlagen/1/bearbeiten", "ih.anlagen.pflegen"),
             ("get", "/ih/import", "ih.import"), ("post", "/ih/import", "ih.import"), ("get", "/ih/import/1", "ih.import"),
             ("post", "/ih/import/1/pruefen", "ih.import"), ("post", "/ih/import/1/uebernehmen", "ih.import"),
             ("post", "/ih/import/1/verwerfen", "ih.import"), ("get", "/ih/import/1/bericht.xlsx", "ih.import")]


def test_rechtematrix_jede_route_jede_rolle(env):
    """Jede CMMS-Route prüft ihr Recht auf dem Server – unabhängig davon, ob ein Knopf sichtbar ist."""
    from app.rechte import IH_ROLLEN, RECHTE
    cfg, eng = env
    cmms_an(cfg)
    with schreib(eng) as con:
        from app.db import ih_plaetze
        con.execute(insert(ih_plaetze).values(id=1, code="P -10401 A", schluessel="p-10401a", art="platz", aktiv=True))
    for r in IH_ROLLEN:
        ih_benutzer(eng, f"ih_{r}", r)
    for r in IH_ROLLEN:
        c = client(cfg)
        c.post("/login", data={"username": f"ih_{r}", "passwort": "Lager-Test-2026"})
        for methode, pfad, recht in IH_ROUTEN:
            status = getattr(c, methode)(pfad).status_code
            if r in RECHTE[recht]:
                assert status != 403, (r, pfad)
            else:
                assert status == 403, (r, pfad)
    # Kein Lagerzugriff für reine CMMS-Benutzer – auch nicht über die API
    c = client(cfg)
    c.post("/login", data={"username": "ih_techniker", "passwort": "Lager-Test-2026"})
    for pfad in ("/artikel", "/buchen", "/m", "/lagerplaetze", "/einstellungen"):
        assert c.get(pfad).status_code == 403, pfad
    assert c.get("/").headers["location"] == "/ih"


def test_api_ohne_lagerrolle_gesperrt(env):
    from app.db import users
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "nur_ih", "ingenieur")
    with schreib(eng) as con:
        con.execute(users.update().where(users.c.username == "nur_ih").values(api_token="tok_ih"))
    c = client(cfg)
    assert c.get("/api/v1/artikel", headers={"Authorization": "Bearer tok_ih"}).status_code == 403
    assert c.get("/api/v1/artikel", headers={"Authorization": "Bearer tok_lesen"}).status_code == 200


def test_modulwahl_und_wechsel_ohne_neue_anmeldung(env):
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "beides", "techniker", rolle="lager")
    ih_benutzer(eng, "nur_ih", "operator")
    c = client(cfg)
    r = c.post("/login", data={"username": "beides", "passwort": "Lager-Test-2026"})
    assert r.headers["location"] == "/bereich"
    seite = c.get("/bereich").text
    assert "/bereich/lager" in seite and "/bereich/ih" in seite
    assert c.get("/bereich/ih").headers["location"] == "/ih"
    ih = c.get("/ih").text
    assert "Zur Lagerverwaltung" in ih and "Asset-Import" not in ih  # Techniker: kein Import-Menüpunkt
    assert "Zur Instandhaltung" in c.get("/").text
    c.get("/logout")
    assert c.post("/login", data={"username": "beides", "passwort": "Lager-Test-2026"}).headers["location"] == "/ih"  # zuletzt genutzt
    # nur Instandhaltung: direkt dorthin, auch aus der Scanner-App
    c = client(cfg)
    assert c.post("/login", data={"username": "nur_ih", "passwort": "Lager-Test-2026", "weiter": "/m"}).headers["location"] == "/ih"
    assert "/bereich/" not in c.get("/ih").text
    assert c.get("/bereich/lager").status_code == 403
    # weder Lager noch CMMS: kein Login
    ih_benutzer(eng, "niemand", None)
    r = client(cfg).post("/login", data={"username": "niemand", "passwort": "Lager-Test-2026"})
    assert r.status_code == 200 and "keinen Zugriff" in r.text


def test_benutzerverwaltung_cmms_rolle(env):
    from app.db import benutzer_rollen, users
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, "admin")
    assert "Rolle Instandhaltung" in c.get("/einstellungen?tab=benutzer").text
    c.post("/benutzer/speichern", data={"username": "anna", "anzeigename": "Anna", "rolle": "keine", "rolle_ih": "ingenieur",
                                         "passwort": "Sehr-Sicher-123", "aktiv": "on"})
    with eng.connect() as con:
        uid, rolle = con.execute(select(users.c.id, users.c.rolle).where(users.c.username == "anna")).one()
        assert rolle == "keine"
        assert con.execute(select(benutzer_rollen.c.rolle).where(benutzer_rollen.c.user_id == uid)).scalar() == "ingenieur"
    c.post("/benutzer/speichern", data={"id": str(uid), "username": "anna", "rolle": "lesen", "rolle_ih": "", "rolle_ih_feld": "1", "aktiv": "on"})
    assert anzahl(eng, "SELECT count(*) FROM benutzer_rollen") == 0
    c.post("/einstellungen/allgemein", data={"firmenname": "X", "port": "8080", "https_port": "8443", "standard_einheit": "Stk",
                                             "live_abfrage_sekunden": "10"})
    assert cfg.cmms.aktiv is False or c.app.state.cfg.cmms.aktiv is False


# ------------------------------------------------------------------ Asset-Import
SCHEMA = 'ListSchema={"schemaXmlList":["<Field ID=\\"{x}\\" Type=\\"Text\\" Name=\\"Title\\" />"]}'
KOPF = ["Tag Nr.", "abgehakt (Kosten)", "Bezeichnung", "Kategorie", "Kosten Einkauf", "Kürzel", "Unit", "Functional Location", "Criticality",
        "Lieferant", "Manufacturer", "Model", "Serial Number", "URL Documentation", "Notes", "Datum der Anschaffung", "Kommentar", "Hubspot Deal"]
ZEILEN = [
    ["E -10101  ", "Wahr", "Rohrbündelwärmetauscher", "Wärmetauscher", "67.200", "E", "1010", "", "", "Muster GmbH", "Hersteller A", "XPS 50", "",
     "https://firma.sharepoint.com/sites/Technik/Doku/1010/E/E-10101", "", "2024-10-13T22:00:00Z", "", ""],
    ["FIC 1040 01-01", "Falsch", "Durchflussregler", "Regelung", "2.210,45", "FIC", "", "", "1", "Muster GmbH", "", "", "SN-77",
     "https://firma.sharepoint.com/sites/Technik/Doku/1040/FIC", "", "2025-07-01T22:00:00Z", "Kommentar 1", ""],
    ["TIZ 3030 01-01", "Wahr", "Temperaturschalter", "Sensorik", "482,1", "TIZ", "3030", "", "", "", "", "", "", "javascript:alert(1)", "", "", "", ""],
    ["VV 3010 xx", "Wahr", "Kugelhahn", "Ventil", "19,27", "VV", "3010", "", "", "", "", "", "", "", "", "", "", ""],
    ["VV 3010 xx", "Wahr", "Kugelhahn", "Ventil", "19,27", "VV", "3010", "", "", "", "", "", "", "", "", "", "", ""],
    ["VC 3030 07", "Wahr", "Regelventil", "Ventil", "485", "VC", "1093", "", "", "", "", "", "", "", "", "", "", ""],
    ["CAP01-13030", "Wahr", "Montagematerial", "30000 - Anlage", "1.931,5", "CAP01", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "Wahr", "ohne Tag", "Ventil", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["P -10401 A", "Wahr", "Speisepumpe", "Pumpe", "7.090", "P", "", "", "", "", "", "", "", "", "", "", "", ""],
]


def _csv(zeilen=ZEILEN) -> bytes:
    import csv
    puffer = io.StringIO()
    puffer.write(SCHEMA + "\r\n")
    w = csv.writer(puffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(KOPF)
    w.writerows(zeilen)
    return b"\xef\xbb\xbf" + puffer.getvalue().encode("utf-8")


def _matrix_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Anleitung"
    wb.active.append(["Thema", "Erläuterung"])
    wb.active.append(["Was ist das?", "Instandhaltungsplan"])
    m = wb.create_sheet("Maßnahmen")
    m.append(["Symbol", "Code", "Maßnahme"])
    m.append(["●", "S", "Sichtprüfung"])
    ws = wb.create_sheet("Matrix")
    ws.append(["Asset", "Bezeichnung", "Bauteilklasse", "Unit", "PLT-Sicherheitseinrichtung", "● S", "▲ W", "■ F"])
    ws.append(["E -10101", "Rohrbündelwärmetauscher", "Wärmetauscher", "1010", "Nein", 12, 12, None])
    ws.append(["TIZ 3030 01-01", "Temperaturschalter", "PLTS-Sensor", "3030", "Ja", 3, 12, 12])
    ws.append(["FIC  1040 01-01", "Durchflussregler", "Messstelle", "1040", "Nein", 12, None, 24])
    ws.append(["LS 9999 01", "Neu im Plan", "Sonstiges", "", "Nein", 12, None, None])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _hochladen(c, daten: bytes, name: str, blatt: str = "") -> int:
    r = c.post("/ih/import", files={"datei": (name, daten)}, data={"blatt": blatt})
    assert r.status_code == 303 and r.headers["location"].startswith("/ih/import/"), r.text[:500]
    return int(r.headers["location"].rsplit("/", 1)[1])


def _formular(c, lid) -> dict:
    """Vorgeschlagene Zuordnung aus der Seite lesen (wie der Browser sie absenden würde)."""
    import re
    seite = c.get(f"/ih/import/{lid}").text
    daten = {}
    for m in re.finditer(r'<select name="(spalte_\d+)"[^>]*>(.*?)</select>', seite, re.S):
        gew = re.search(r'<option value="([^"]*)" selected', m.group(2))
        daten[m.group(1)] = gew.group(1) if gew else ""
    for k in ("unit_aus_tag", "bereiche_bilden"):
        if re.search(rf'name="{k}" class="mt-1" checked', seite):
            daten[k] = "on"
    return daten


def test_import_sharepoint_csv_pruefen_testlauf_uebernehmen(env):
    from app.db import ih_plaetze
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, "admin")
    lid = _hochladen(c, _csv(), "Asset_List.csv")
    f = _formular(c, lid)
    assert f["spalte_0"] == "code" and f["spalte_4"] == "kosten" and f["spalte_6"] == "gruppe" and f["spalte_13"] == "doku_url"
    assert f["spalte_1"] == "zusatz" and f["spalte_17"] == ""  # unbekannt -> Zusatzfeld, leer -> ignorieren
    # Prüfen + Testlauf: nichts in der Datenbank
    r = c.post(f"/ih/import/{lid}/pruefen", data=f, follow_redirects=True)
    assert "Testlauf abgeschlossen" in r.text
    assert anzahl(eng, "SELECT count(*) FROM ih_plaetze") == 0
    with eng.connect() as con:
        e = json.loads(con.execute(select(__import__("app.db", fromlist=["x"]).ih_import_laeufe.c.ergebnis)).scalar())
    assert e["neu"] == 6 and e["fehler"] == 3 and e["testlauf_ok"]  # 2 x Platzhalter doppelt + 1 ohne Tag
    seite = c.get(f"/ih/import/{lid}?zeige=fehler").text
    assert "mehrfach in der Datei" in seite and "Tag-Nr. fehlt" in seite
    hinweise = c.get(f"/ih/import/{lid}?zeige=hinweise").text
    assert "javascript" in hinweise and "Unit 1093 passt nicht zur Tag-Nr." in hinweise
    # Übernahme nur mit Bestätigung, mit Sicherung davor
    c.post(f"/ih/import/{lid}/uebernehmen", data={})
    assert anzahl(eng, "SELECT count(*) FROM ih_plaetze") == 0
    r = c.post(f"/ih/import/{lid}/uebernehmen", data={"bestaetigt": "ja"}, follow_redirects=True)
    assert "Import übernommen: 6 neu" in r.text
    assert list(Path(cfg.path(cfg.backup.ordner)).glob("vor_import_*.zip"))
    with eng.connect() as con:
        p = {r["code"]: dict(r) for r in con.execute(select(ih_plaetze)).mappings()}
    assert set(p) == {"E -10101", "FIC 1040 01-01", "TIZ 3030 01-01", "VC 3030 07", "CAP01-13030", "P -10401 A",
                      "1000", "1010", "1040", "3000", "3030", "1093"}
    e = p["E -10101"]
    assert e["kosten"] == 67200 and e["anschaffung"] == date(2024, 10, 14) and e["doku_url"].startswith("https://")
    assert json.loads(e["zusatz"]) == {"abgehakt (Kosten)": "Wahr"}
    assert p["FIC 1040 01-01"]["kosten"] == 2210.45 and p["FIC 1040 01-01"]["kritikalitaet"] == "A"
    assert p["FIC 1040 01-01"]["anschaffung"] == date(2025, 7, 2)  # 22:00 UTC im Sommer = 00:00 MESZ am Folgetag
    assert p["FIC 1040 01-01"]["notiz"] == "Kommentar 1"
    assert p["TIZ 3030 01-01"]["doku_url"] is None  # javascript:-Link nie übernommen
    nach_id = {v["id"]: k for k, v in p.items()}
    assert nach_id[p["E -10101"]["eltern_id"]] == "1010" and nach_id[p["1010"]["eltern_id"]] == "1000"
    assert nach_id[p["P -10401 A"]["eltern_id"]] == "1040"   # Unit aus der Tag-Nr.
    assert nach_id[p["VC 3030 07"]["eltern_id"]] == "1093"   # Unit-Spalte hat Vorrang
    assert p["CAP01-13030"]["eltern_id"] is None
    # Bericht, Anlagenseiten
    b = c.get(f"/ih/import/{lid}/bericht.xlsx")
    assert b.status_code == 200 and b.content[:2] == b"PK"
    liste = c.get("/ih/anlagen?q=fic1040").text
    assert "FIC 1040 01-01" in liste and "E -10101" not in liste
    seite = c.get(f"/ih/anlagen/{p['E -10101']['id']}").text
    assert "Dokumentation öffnen" in seite and 'rel="noopener noreferrer"' in seite and "67.200,00 €" in seite
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Asset-Import übernommen'") == 1
    # zweimal übernehmen geht nicht
    c.post(f"/ih/import/{lid}/uebernehmen", data={"bestaetigt": "ja"})
    assert anzahl(eng, "SELECT count(*) FROM ih_plaetze") == 12


def test_import_matrix_aus_instandhaltungsplan_aktualisiert(env):
    from app.db import ih_plaetze
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, "admin")
    lid = _hochladen(c, _csv(), "Asset_List.csv")
    c.post(f"/ih/import/{lid}/pruefen", data=_formular(c, lid))
    c.post(f"/ih/import/{lid}/uebernehmen", data={"bestaetigt": "ja"})
    with schreib(eng) as con:
        con.execute(ih_plaetze.update().where(ih_plaetze.c.code == "E -10101").values(status="in Betrieb"))
    lid2 = _hochladen(c, _matrix_xlsx(), "Instandhaltungsplan_CAPHENIA_v2.xlsx")
    seite = c.get(f"/ih/import/{lid2}").text
    assert "Tabellenblatt „Matrix“" in seite and "Weitere Blätter: Anleitung, Maßnahmen" in seite
    f = _formular(c, lid2)
    assert f["spalte_2"] == "bauteilklasse" and f["spalte_4"] == "sicherheitsgerichtet"
    c.post(f"/ih/import/{lid2}/pruefen", data=f)
    # zwischen Prüfung und Übernahme ändert jemand eine Anlage -> Übernahme verweigert
    with schreib(eng) as con:
        con.execute(ih_plaetze.update().where(ih_plaetze.c.code == "P -10401 A").values(geaendert_am=datetime(2030, 1, 1)))
    r = c.post(f"/ih/import/{lid2}/uebernehmen", data={"bestaetigt": "ja"}, follow_redirects=True)
    assert "seit der Prüfung verändert" in r.text
    c.post(f"/ih/import/{lid2}/pruefen", data=f)
    r = c.post(f"/ih/import/{lid2}/uebernehmen", data={"bestaetigt": "ja"}, follow_redirects=True)
    assert "1 neu, 3 geändert" in r.text
    with eng.connect() as con:
        p = {r["code"]: dict(r) for r in con.execute(select(ih_plaetze)).mappings()}
    assert p["TIZ 3030 01-01"]["sicherheitsgerichtet"] is True and p["TIZ 3030 01-01"]["bauteilklasse"] == "PLTS-Sensor"
    assert p["FIC 1040 01-01"]["bauteilklasse"] == "Messstelle"  # „FIC  1040 01-01“ (2 Leerzeichen) = dieselbe Anlage
    assert p["E -10101"]["status"] == "in Betrieb" and p["E -10101"]["kosten"] == 67200  # nicht zugeordnet -> unverändert
    assert json.loads(p["E -10101"]["zusatz"]) == {"abgehakt (Kosten)": "Wahr", "● S": "12", "▲ W": "12"}
    assert "CAP01-13030" in p  # fehlt in der Matrix -> bleibt
    assert anzahl(eng, "SELECT count(*) FROM ih_plaetze WHERE code='LS 9999 01'") == 1
    assert "PLT-S" in c.get("/ih/anlagen?filter=sicher").text


def test_import_fehlerfaelle(env):
    cfg, eng = env
    cmms_an(cfg)
    c = client(cfg, "admin")
    for daten, name, text in ((b"", "leer.csv", "leer"), (b"%PDF-1.4", "x.pdf", "Excel-Datei"), (b"a;b\n", "k.csv", "keine Datenzeilen"),
                              (_matrix_xlsx(), "p.xlsx", "Tabellenblatt „Gibtsnicht“")):
        r = c.post("/ih/import", files={"datei": (name, daten)}, data={"blatt": "Gibtsnicht" if name == "p.xlsx" else ""}, follow_redirects=True)
        assert text in r.text, name
    lid = _hochladen(c, _csv(), "a.csv")
    f = _formular(c, lid)
    f["spalte_2"] = "kosten"  # Kosten doppelt zugeordnet
    assert "mehreren Spalten zugeordnet" in c.post(f"/ih/import/{lid}/pruefen", data=f, follow_redirects=True).text
    f = {k: ("" if v == "code" else v) for k, v in _formular(c, lid).items()}
    assert "genau eine Spalte" in c.post(f"/ih/import/{lid}/pruefen", data=f, follow_redirects=True).text
    assert "zuerst" in c.post(f"/ih/import/{lid}/uebernehmen", data={"bestaetigt": "ja"}, follow_redirects=True).text
    c.post(f"/ih/import/{lid}/verwerfen")
    assert anzahl(eng, "SELECT count(*) FROM ih_import_laeufe") == 0 and anzahl(eng, "SELECT count(*) FROM ih_import_zeilen") == 0


def test_umwandlungen():
    from app.services import asset_import as ai
    assert ai.zahl("67.200") == 67200 and ai.zahl("2.210,45") == 2210.45 and ai.zahl("482,1") == 482.1 and ai.zahl("19.5") == 19.5
    assert ai.zahl("1,234.5") == 1234.5 and ai.zahl("") is None
    with pytest.raises(ValueError):
        ai.zahl("abc")
    assert ai.datum("2024-10-13T22:00:00Z") == date(2024, 10, 14)   # MESZ
    assert ai.datum("2024-11-07T23:00:00Z") == date(2024, 11, 8)    # MEZ
    assert ai.datum("2025-03-30T00:30:00Z") == date(2025, 3, 30)    # Umstellung 01:00 UTC
    assert ai.datum("14.10.24") == date(2024, 10, 14) and ai.datum("2024-10-14") == date(2024, 10, 14)
    assert ai.unit_aus_tag("FIC 1040 01-01") == "1040" and ai.unit_aus_tag("P -10401 A") == "1040" and ai.unit_aus_tag("PM -30201") == "3020"
    assert ai.unit_aus_tag("CAP01-13030") is None and ai.unit_aus_tag("CAP-34004") is None and ai.unit_aus_tag("LS") is None
    assert ai.schluessel("PI  3020 01-02") == ai.schluessel("pi 3020 01-02")
    assert ai.kritikalitaet("2") == "B" and ai.ja_nein("Wahr") is True and ai.ja_nein("Nein") is False


def test_anlage_bearbeiten(env):
    from app.db import ih_plaetze
    cfg, eng = env
    cmms_an(cfg)
    with schreib(eng) as con:
        con.execute(insert(ih_plaetze), [{"id": 1, "code": "1000", "schluessel": "1000", "art": "bereich", "eltern_id": None, "aktiv": True},
                                         {"id": 2, "code": "1040", "schluessel": "1040", "art": "unit", "eltern_id": 1, "aktiv": True},
                                         {"id": 3, "code": "P -10401 A", "schluessel": "p-10401a", "art": "platz", "eltern_id": 2, "aktiv": True}])
    ih_benutzer(eng, "ing", "ingenieur")
    c = client(cfg)
    c.post("/login", data={"username": "ing", "passwort": "Lager-Test-2026"})
    r = c.post("/ih/anlagen/2/bearbeiten", data={"bezeichnung": "Feedstock Treatment", "eltern_id": "1"}, follow_redirects=True)
    assert "Gespeichert" in r.text
    r = c.post("/ih/anlagen/1/bearbeiten", data={"eltern_id": "2"}, follow_redirects=True)
    assert "nicht unter sich selbst" in r.text  # Bereich unter seine eigene Unit -> abgelehnt
    r = c.post("/ih/anlagen/3/bearbeiten", data={"doku_url": "javascript:alert(1)", "eltern_id": "2"}, follow_redirects=True)
    assert "http://" in r.text
    c.post("/ih/anlagen/3/bearbeiten", data={"bauteilklasse": "Pumpe", "sicherheitsgerichtet": "nein", "kritikalitaet": "B",
                                             "kosten": "7.090", "inbetriebnahme": "2025-01-15", "eltern_id": "2"})
    with eng.connect() as con:
        p = con.execute(select(ih_plaetze).where(ih_plaetze.c.id == 3)).mappings().one()
    assert (p["bauteilklasse"], p["sicherheitsgerichtet"], p["kritikalitaet"], p["kosten"], p["inbetriebnahme"]) == \
        ("Pumpe", False, "B", 7090, date(2025, 1, 15))
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Anlage geändert'") == 2
    s = c.get("/ih/anlagen/3").text
    assert "Feedstock Treatment" in s  # Pfad zeigt die Ebenen


def test_testsystem_kopie_und_eigene_einstellungen(env, tmp_path, monkeypatch):
    from app import testsystem
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Echt"}, "C1-R1-1", 4)
    programm = tmp_path / "prog"
    (programm / "daten").mkdir(parents=True)
    testsystem.kopieren(cfg.path(cfg.daten.datenbank), programm / "daten" / "lager.db")  # „Echtbetrieb“
    monkeypatch.setattr(testsystem, "PROGRAMM", programm)
    monkeypatch.setattr(testsystem, "TEST", programm / "testsystem")
    testsystem.vorbereiten()
    test_db = programm / "testsystem" / "daten" / "lager.db"
    k = (programm / "testsystem" / "config.toml").read_text(encoding="utf-8")
    assert "port = 8090" in k and 'host = "127.0.0.1"' in k and "[backup]\naktiv = false" in k and "[mail]\naktiv = false" in k
    con = sqlite3.connect(str(test_db))
    con.execute("UPDATE bestand SET menge = 99")  # im Testsystem buchen ...
    con.commit()
    con.close()
    testsystem.vorbereiten("n")  # ... bleibt bei „nein“ erhalten
    assert sqlite3.connect(str(test_db)).execute("SELECT menge FROM bestand").fetchone()[0] == 99
    testsystem.vorbereiten("j")  # neu kopieren
    assert sqlite3.connect(str(test_db)).execute("SELECT menge FROM bestand").fetchone()[0] == 4
    assert sqlite3.connect(str(programm / "daten" / "lager.db")).execute("SELECT menge FROM bestand").fetchone()[0] == 4
