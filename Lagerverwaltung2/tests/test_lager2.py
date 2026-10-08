"""Tests der eigenständigen Lagerverwaltung (SQLite)."""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

ECHTER_EXPORT = os.environ.get("LV_CASPER_EXPORT", "")

MINI_DUMP = """
INSERT INTO `benutzer` (`benutzer`, `passwort`) VALUES ('Administrator', NULL);
INSERT INTO `stammdaten` (`Artikelnummer`, `Bezeichnung`, `Meldebestand`, `Mindestbestand`, `Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `ID`) VALUES
	('10001', 'Kugelhahn DN15', '2', '0', 'Swagelok', 'Kugelhahn', 'SS-45', '', 'Freifeld5', 1);
INSERT INTO `stammdaten` (`Artikelnummer`, `Bezeichnung`, `Meldebestand`, `Mindestbestand`, `Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `ID`) VALUES
	('10002', 'Manometer 0-10 bar, O\\'Ring', '0', '0', 'swagelok', 'Druckmessung', '', 'Verbaut', '', 2);
INSERT INTO `lagerorte` (`Artikel`, `Lagerort`, `Anzahl`, `ID`) VALUES ('10001', 'C1-F3 ', 2.000, 1), ('10001', 'C1-F3', 1.000, 2), ('10002', '', 1.000, 3), ('99999', 'C1-R1-1', 5.000, 4);
INSERT INTO `bewegungsdaten` (`Artikelnummer`, `Lagerort`, `ISTBestand`, `Zeit`, `Datum`, `EingangAusgang`, `Benutzer`, `Bewegungsdaten_ID`, `ID`) VALUES
	('10001', 'C1-F3', 3, '10:00:00', '01.02.2025', 'Neuer Artikel', 'Administrator', 1, 0);
INSERT INTO `bewegungsdaten` (`Artikelnummer`, `Lagerort`, `ISTBestand`, `Zeit`, `Datum`, `EingangAusgang`, `Benutzer`, `Bewegungsdaten_ID`, `ID`) VALUES
	('10001', '', 3, '10:01:00', '01.02.2025', 'Artikel bearbeitet', 'Administrator', 2, 0);
"""


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LV_HOME", str(tmp_path))
    from app import db
    from app.config import Config
    cfg = Config()
    cfg.daten.datenbank = str(tmp_path / "lager.db")
    cfg.daten.anhaenge = str(tmp_path / "anh")
    cfg.server.secret_key = "test"
    cfg.drucker.modus = "datei"
    cfg.drucker.datei_ordner = str(tmp_path / "druck")
    cfg.backup.ordner = str(tmp_path / "bak")
    eng = db.init_engine(cfg.db_url)
    return cfg, eng


def L(con, **kw):
    from app.services.lager import Lager
    return Lager(con, "Tester", **kw)


def menge(con, nr, platz):
    return con.execute(text("SELECT b.menge FROM bestand b JOIN artikel a ON a.id=b.artikel_id JOIN lagerplaetze p ON p.id=b.lagerplatz_id "
                            "WHERE a.nummer=:a AND p.code=:p"), dict(a=nr, p=platz)).scalar()


def test_buchungen(app_env):
    from app.services.lager import BuchungsFehler
    _, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "A1-R1-1", 5)
    with eng.execution_options(schreiben=True).begin() as con:
        e = L(con).ausgang("1", "A1-R1-1", 2, kostenstelle="4711")
        assert e.bestand_nachher == 3
        L(con).eingang("1", "A1-R1-2", 4)
        L(con).umbuchung("1", "A1-R1-2", "A1-R1-1", 1)
    with eng.connect() as con:
        assert menge(con, "1", "A1-R1-1") == 4 and menge(con, "1", "A1-R1-2") == 3
    with pytest.raises(BuchungsFehler):
        with eng.execution_options(schreiben=True).begin() as con:
            L(con).ausgang("1", "A1-R1-1", 99)
    with pytest.raises(BuchungsFehler):  # unbekannter Platz beim Entnehmen
        with eng.execution_options(schreiben=True).begin() as con:
            L(con).ausgang("1", "X9", 1)
    with eng.execution_options(schreiben=True).begin() as con:
        e = L(con).inventur("1", "A1-R1-1", 10)
        assert e.menge == 6
        aus = L(con).ausleihe("1", "A1-R1-1", 2, "Fa. Müller")
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).rueckgabe(aus.id, 1)
    with eng.connect() as con:
        from app.services.queries import offene_ausleihen
        assert offene_ausleihen(con)[0]["offen"] == 1
        assert menge(con, "1", "A1-R1-1") == 9


def test_storno_und_archiv(app_env):
    from app.services.lager import BuchungsFehler
    _, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        a = L(con).artikel_anlegen({"nummer": "2", "bezeichnung": "Dichtung"}, "B1", 3)
        e = L(con).ausgang("2", "B1", 1)
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).storno(e.id)
    with eng.connect() as con:
        assert menge(con, "2", "B1") == 3
    with pytest.raises(BuchungsFehler):
        with eng.execution_options(schreiben=True).begin() as con:
            L(con).storno(e.id)
    with pytest.raises(BuchungsFehler):  # Archivieren nur ohne Bestand
        with eng.execution_options(schreiben=True).begin() as con:
            L(con).artikel_archivieren(a["id"])
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).inventur("2", "B1", 0)
        L(con).artikel_archivieren(a["id"])
    with pytest.raises(BuchungsFehler):
        with eng.execution_options(schreiben=True).begin() as con:
            L(con).eingang("2", "B1", 1)


def test_parallel(app_env):
    """Zwei gleichzeitige Entnahmen des letzten Teils: genau eine gelingt."""
    from app.services.lager import BuchungsFehler
    _, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).artikel_anlegen({"nummer": "3", "bezeichnung": "Sicherung"}, "C1", 1)
    erg = []

    def nehmen():
        try:
            with eng.execution_options(schreiben=True).begin() as con:
                L(con).ausgang("3", "C1", 1)
            erg.append("ok")
        except BuchungsFehler:
            erg.append("nein")
    ts = [threading.Thread(target=nehmen) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(erg) == ["nein", "nein", "nein", "ok"]
    with eng.connect() as con:
        assert menge(con, "3", "C1") == 0


def test_casper_import_mini(app_env):
    from app.services.casper_import import uebernehmen
    _, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        r = uebernehmen(con, MINI_DUMP)
    assert r.artikel == 2 and r.lieferanten == 1  # Swagelok/swagelok zusammengeführt
    assert r.gesamtbestand == 4  # 99999 verwaist, nicht übernommen
    with eng.connect() as con:
        assert menge(con, "10001", "C1-F3") == 3  # 'C1-F3 ' und 'C1-F3' zusammengeführt
        assert menge(con, "10002", "OHNE-PLATZ") == 1
        a = con.execute(text("SELECT * FROM artikel WHERE nummer='10002'")).mappings().first()
        assert a["bezeichnung"] == "Manometer 0-10 bar, O'Ring" and "Verbaut" in a["notiz"] and a["meldebestand"] is None
        typen = [r[0] for r in con.execute(text("SELECT typ FROM bewegungen ORDER BY id"))]
        assert typen == ["anlage", "info"]
        assert con.execute(text("SELECT aktiv FROM users WHERE username='Administrator'")).scalar() == 0


@pytest.mark.skipif(not (ECHTER_EXPORT and Path(ECHTER_EXPORT).is_file()), reason="kein echter Casper-Export angegeben")
def test_casper_import_echt(app_env):
    from app.services.casper_import import uebernehmen
    _, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        r = uebernehmen(con, Path(ECHTER_EXPORT).read_text(encoding="utf-8"))
    assert r.artikel > 0 and r.bewegungen > 0


def test_backup(app_env):
    import zipfile
    from app.services.betrieb import backup_erstellen
    cfg, eng = app_env
    with eng.execution_options(schreiben=True).begin() as con:
        L(con).artikel_anlegen({"nummer": "5", "bezeichnung": "X"}, "", 0)
    z = backup_erstellen(cfg)
    assert "lager.db" in zipfile.ZipFile(z).namelist()


def test_web_mobil_api(app_env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    cfg, eng = app_env
    app = create_app(cfg, start_scheduler=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:  # Ersteinrichtung nur am Lager-PC
        assert "Ersten Administrator" in c.get("/", follow_redirects=True).text
        c.post("/einrichtung", data=dict(username="admin", anzeigename="Admin", passwort="geheim-12345", passwort2="geheim-12345"))
        r = c.post("/login", data=dict(username="admin", passwort="geheim-12345", weiter="/"), follow_redirects=True)
        assert "Willkommen" in r.text
        r = c.post("/einstellungen/uebernahme", files={"datei": ("daten.sql", MINI_DUMP.encode(), "text/plain")}, follow_redirects=True)
        assert "Übernommen: 2 Artikel" in r.text
        r = c.post("/artikel/neu", data=dict(nummer="20000", bezeichnung="Web-Test", meldebestand="1", platz="C9-R5-1", anfangsbestand="2"), follow_redirects=True)
        assert "Web-Test" in r.text
        r = c.post("/buchen", data=dict(artikel="20000", typ="ausgang", menge="1", lagerort="C9-R5-1", kostenstelle="KST1"), follow_redirects=True)
        assert "Entnahme: 1 × 20000" in r.text
        r = c.post("/m/buchen", data=dict(artikel="20000", typ="eingang", menge="3", lagerort="C9-R5-1"), follow_redirects=True)
        assert "Eingang: 3 × 20000" in r.text and 'data-flash="ok"' in r.text
        r = c.post("/m/buchen", data=dict(artikel="20000", typ="ausgang", menge="50", lagerort="C9-R5-1"), follow_redirects=True)
        assert 'data-flash="fehler"' in r.text
        assert c.get("/scan?code=20000&m=1", follow_redirects=False).headers["location"] == "/m/artikel/20000"
        for pfad in ["/", "/artikel", "/artikel/20000", "/bewegungen", "/lagerplaetze", "/nachbestellung", "/bestellungen", "/reservierungen",
                     "/ausleihen", "/inventur", "/auswertungen", "/einstellungen?tab=handy", "/protokoll", "/m", "/m/artikel/20000", "/m/suche?q=web",
                     "/m/platz?code=C9-R5-1", "/artikel/export.xlsx", "/bewegungen/export.csv", "/etiketten/druckansicht?nr=20000"]:
            assert c.get(pfad).status_code == 200, pfad
        assert "Druckdatei gespeichert" in c.post("/artikel/20000/etikett", data=dict(anzahl="1"), follow_redirects=True).text
        # Inventur über die Handy-Ansicht
        r = c.post("/inventur/neu", data=dict(name="Test", bereich="C9"), follow_redirects=True)
        iid = int(re.search(r"/inventur/(\d+)/zaehlliste", r.text).group(1))
        r = c.get(f"/m/inventur/{iid}?platz=C9-R5-1")
        pid = re.search(r'name="ist_(\d+)"', r.text).group(1)
        c.post(f"/m/inventur/{iid}", data={"platz": "C9-R5-1", f"ist_{pid}": "7"})
        assert "Inventur abgeschlossen" in c.post(f"/inventur/{iid}/abschliessen", follow_redirects=True).text
        # API
        with eng.connect() as con:
            uid = con.execute(text("SELECT id FROM users WHERE username='admin'")).scalar()
        c.post(f"/benutzer/{uid}/token")
        with eng.connect() as con:
            token = con.execute(text("SELECT api_token FROM users WHERE id=:i"), dict(i=uid)).scalar()
        h = {"Authorization": f"Bearer {token}"}
        assert c.get("/api/v1/artikel/20000").status_code == 401
        a = c.get("/api/v1/artikel/20000", headers=h).json()
        assert a["bestand"] == 7
        r = c.post("/api/v1/buchungen", headers=h, json=dict(typ="ausgang", artikel="20000", menge=2, lagerplatz="C9-R5-1"))
        assert r.status_code == 200 and r.json()["ok"]
        assert c.post("/api/v1/buchungen", headers=h, json=dict(typ="ausgang", artikel="20000", menge=99, lagerplatz="C9-R5-1")).status_code == 422


def test_handheld_funktionen(app_env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    cfg, eng = app_env
    app = create_app(cfg, start_scheduler=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:  # Ersteinrichtung nur am Lager-PC
        c.post("/einrichtung", data=dict(username="admin", anzeigename="Admin", passwort="geheim-12345", passwort2="geheim-12345"))
        c.post("/login", data=dict(username="admin", passwort="geheim-12345", weiter="/m"))
        # PWA-Hülle
        m = c.get("/m/manifest.webmanifest").json()
        assert m["display"] == "standalone" and m["start_url"] == "/m"
        sw = c.get("/m/sw.js")
        assert sw.headers["service-worker-allowed"] == "/m" and "caches" in sw.text
        assert c.get("/zertifikat.crt").headers["content-type"] == "application/x-x509-ca-cert"
        # Neuer Artikel am Handheld
        r = c.post("/m/neu", data=dict(nummer="H-1", bezeichnung="Handheld-Teil", platz="H1-R1-1", anfangsbestand="5", lieferant="Neu GmbH"), follow_redirects=True)
        assert "Artikel H-1 angelegt" in r.text
        # Grenzwerte setzen
        c.post("/m/artikel/H-1/werte", data=dict(meldebestand="3", mindestbestand="1"))
        with eng.connect() as con:
            assert con.execute(text("SELECT meldebestand FROM artikel WHERE nummer='H-1'")).scalar() == 3
        # Entnahme + Rückgängig
        c.post("/m/buchen", data=dict(artikel="H-1", typ="ausgang", menge="2", lagerort="H1-R1-1"))
        r = c.post("/m/rueckgaengig", follow_redirects=True)
        assert "Zurückgenommen" in r.text
        with eng.connect() as con:
            assert menge(con, "H-1", "H1-R1-1") == 5
        # Umbuchung + Rückgängig
        c.post("/m/buchen", data=dict(artikel="H-1", typ="umbuchung", menge="1", lagerort="H1-R1-1", ziel="H1-R1-2"))
        assert "Zurückgenommen" in c.post("/m/rueckgaengig", follow_redirects=True).text
        with eng.connect() as con:
            assert menge(con, "H-1", "H1-R1-1") == 5 and menge(con, "H-1", "H1-R1-2") == 0
        # Sammelentnahme: alles oder nichts
        c.post("/m/korb/neu", data=dict(artikel="H-1", lagerort="H1-R1-1", menge="2"))
        c.post("/m/korb/neu", data=dict(artikel="H-1", lagerort="H1-R1-1", menge="9"))
        assert "Nichts gebucht" in c.post("/m/korb/buchen", data=dict(kostenstelle="K1"), follow_redirects=True).text
        c.post("/m/korb/entfernen/1")
        assert "1 Positionen gebucht" in c.post("/m/korb/buchen", data=dict(kostenstelle="K1"), follow_redirects=True).text
        # Offline-Sync: idempotent und mit Fehlermeldung
        items = [dict(uuid="u-1", typ="ausgang", artikel="H-1", lagerort="H1-R1-1", menge="1", erfasst="2026-10-08T06:00:00Z"),
                 dict(uuid="u-2", typ="ausgang", artikel="H-1", lagerort="H1-R1-1", menge="99", erfasst="2026-10-08T06:01:00Z")]
        e1 = c.post("/m/sync", json=dict(items=items)).json()
        assert e1["u-1"]["ok"] and not e1["u-2"]["ok"]
        e2 = c.post("/m/sync", json=dict(items=items[:1])).json()
        assert e2["u-1"].get("doppelt")
        with eng.connect() as con:
            assert menge(con, "H-1", "H1-R1-1") == 2
            assert con.execute(text("SELECT quelle FROM bewegungen ORDER BY id DESC LIMIT 1")).scalar() == "offline"
        kat = c.get("/m/katalog.json").json()
        assert "H-1" in kat["artikel"]
        for p in ["/m", "/m/offline", "/m/korb", "/m/neu", "/m/reservierungen", "/m/wareneingang", "/m/artikel/H-1", "/m/platz?code=H1-R1-1"]:
            assert c.get(p).status_code == 200, p
    # ohne Anmeldung kein Sync
    with TestClient(app) as c2:
        assert c2.post("/m/sync", json=dict(items=[])).status_code == 401


def test_zertifikat_kette(tmp_path):
    from cryptography import x509
    from app.services.zertifikat import ca_pfade, sicherstellen
    cert, key = sicherstellen(tmp_path)
    ca = x509.load_pem_x509_certificate(ca_pfade(tmp_path)[0].read_bytes())
    srv = x509.load_pem_x509_certificates(cert.read_bytes())[0]
    assert srv.issuer == ca.subject
    srv.verify_directly_issued_by(ca)
    assert sicherstellen(tmp_path) == (cert, key)  # unverändert bei gleichen Adressen
