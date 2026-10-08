"""Tests aus der Abschlussprüfung 2.2.1 – je behobenem Fehler mindestens ein Test.

Mit echtem Casper-Export (nur lokal, nie einchecken):
    LV_CASPER_EXPORT=pfad/daten_export.sql python -m pytest tests
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import insert, text

ECHTER_EXPORT = os.environ.get("LV_CASPER_EXPORT", "")


# ------------------------------------------------------------------ Hilfen
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LV_HOME", str(tmp_path))
    import app.config as config_mod
    from app import db
    from app.config import Config
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg.daten.datenbank = str(tmp_path / "lager.db")
    cfg.daten.anhaenge = str(tmp_path / "anh")
    cfg.server.secret_key = "test-geheim"
    cfg.drucker.modus = "datei"
    cfg.drucker.datei_ordner = str(tmp_path / "druck")
    cfg.backup.ordner = str(tmp_path / "bak")
    eng = db.init_engine(cfg.db_url)
    with eng.execution_options(schreiben=True).begin() as con:
        from app.db import users
        from app.services.betrieb import hash_pw
        for r in ("admin", "lager", "lesen"):
            con.execute(insert(users).values(username=r, anzeigename=r, pw_hash=hash_pw("geheim1"), rolle=r, aktiv=True, api_token=f"tok_{r}"))
    return cfg, eng


def schreib(eng):
    return eng.execution_options(schreiben=True).begin()


def L(con, **kw):
    from app.services.lager import Lager
    return Lager(con, "Tester", **kw)


def menge(con, nr, platz):
    return con.execute(text("SELECT b.menge FROM bestand b JOIN artikel a ON a.id=b.artikel_id JOIN lagerplaetze p ON p.id=b.lagerplatz_id "
                            "WHERE a.nummer=:a AND p.code=:p"), dict(a=nr, p=platz)).scalar()


def client(cfg, rolle=None):
    from fastapi.testclient import TestClient

    from app.main import create_app
    c = TestClient(create_app(cfg, start_scheduler=False), follow_redirects=False)
    if rolle:
        assert c.post("/login", data={"username": rolle, "passwort": "geheim1"}).status_code == 303
    return c


def anzahl(eng, sql, **p):
    with eng.connect() as con:
        return con.execute(text(sql), p).scalar()


# ------------------------------------------------------------------ 3. Buchungslogik: Grenzfälle
@pytest.mark.parametrize("eingabe", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999", "abc", "", "0", "-1", "1e12", "  "])
def test_unsinnige_mengen_werden_abgelehnt(env, eingabe):
    from app.services.lager import BuchungsFehler
    _, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "A1-R1-1", 5)
    for buchung in (lambda l: l.ausgang("1", "A1-R1-1", eingabe), lambda l: l.eingang("1", "A1-R1-1", eingabe)):
        with pytest.raises(BuchungsFehler):
            with schreib(eng) as con:
                buchung(L(con))
    if eingabe.strip() not in ("0",):
        with pytest.raises(BuchungsFehler):
            with schreib(eng) as con:
                L(con).inventur("1", "A1-R1-1", eingabe)
    with eng.connect() as con:
        assert menge(con, "1", "A1-R1-1") == 5  # nichts verändert, insbesondere kein NaN


def test_parse_num_und_formate(env):
    from app.services.lager import fmt_num, parse_num
    assert parse_num("1,5") == 1.5 and parse_num("1.5") == 1.5 and parse_num("1.234,5") == 1234.5 and parse_num(" 2 ") == 2
    assert parse_num("nan") is None and parse_num("inf") is None and parse_num("1e400") is None
    assert fmt_num(1.5) == "1,5" and fmt_num(3.0) == "3"


def test_anfangsbestand_text_wird_abgelehnt(env):
    from app.services.lager import BuchungsFehler
    _, eng = env
    with pytest.raises(BuchungsFehler):
        with schreib(eng) as con:
            L(con).artikel_anlegen({"nummer": "7", "bezeichnung": "X"}, "A1", "zwei")
    assert anzahl(eng, "SELECT count(*) FROM artikel") == 0


def test_grenzfaelle_platz_und_artikel(env):
    from app.services.lager import BuchungsFehler
    _, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1-R1-1", 5)
        L(con).ausgang("1", "c1-r1-1", "1,5")  # Groß-/Kleinschreibung des Platzes egal, Komma als Dezimaltrenner
    with eng.connect() as con:
        assert menge(con, "1", "C1-R1-1") == 3.5
        assert con.execute(text("SELECT count(*) FROM lagerplaetze")).scalar() == 1  # kein zweiter Platz "c1-r1-1"
    for f in (lambda l: l.ausgang("999", "C1-R1-1", 1), lambda l: l.ausgang("1", "GIBTSNICHT", 1), lambda l: l.ausgang("1", "C1-R1-1", 4)):
        with pytest.raises(BuchungsFehler):
            with schreib(eng) as con:
                f(L(con))


# ------------------------------------------------------------------ 3. Inventur-Abschluss
def test_inventur_abschluss_behaelt_buchungen_nach_der_zaehlung(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1-R1-1", 10)
    c = client(cfg, "admin")
    r = c.post("/inventur/neu", data={"name": "T", "bereich": "C1"})
    iid = int(r.headers["location"].rsplit("/", 1)[1])
    pid = anzahl(eng, "SELECT id FROM inventur_pos WHERE inventur_id=:i", i=iid)
    c.post(f"/inventur/{iid}/zaehlen", data={f"ist_{pid}": "8"})  # gezählt: 8 (2 fehlen)
    time.sleep(1.1)  # Buchungen haben Sekundenauflösung
    with schreib(eng) as con:
        L(con).ausgang("1", "C1-R1-1", 3)  # danach entnimmt jemand 3 -> 7 im System, real 5
    c.post(f"/inventur/{iid}/abschliessen")
    with eng.connect() as con:
        assert menge(con, "1", "C1-R1-1") == 5  # vorher (2.2.0): 8 – die Entnahme wäre verloren gegangen


# ------------------------------------------------------------------ 3. Parallelität über echte HTTP-Anfragen
def _freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_parallele_entnahmen_ueber_http(env):
    import httpx
    import uvicorn

    from app.main import create_app
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "3", "bezeichnung": "Sicherung"}, "C1", 1)
    port = _freier_port()
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, start_scheduler=False), host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    basis = f"http://127.0.0.1:{port}"
    clients = []
    for _ in range(8):
        h = httpx.Client(base_url=basis, follow_redirects=False)
        h.post("/login", data={"username": "lager", "passwort": "geheim1"})
        clients.append(h)
    start = threading.Barrier(len(clients))
    erg = []

    def nehmen(h):
        start.wait()
        r = h.post("/m/buchen", data={"artikel": "3", "typ": "ausgang", "menge": "1", "lagerort": "C1"}, headers={"origin": basis})
        erg.append(r.status_code)
    ts = [threading.Thread(target=nehmen, args=(h,)) for h in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    server.should_exit = True
    th.join(5)
    assert erg == [303] * 8
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE typ='ausgang'") == 1
    with eng.connect() as con:
        assert menge(con, "3", "C1") == 0


# ------------------------------------------------------------------ 5. Sicherheit
def test_sicheres_ziel():
    from app.web import sicheres_ziel
    for boese in ("//evil.example", "/\\evil.example", "https://evil.example", "http:/evil", "javascript:alert(1)", "\\\\evil", "", None, "/x\r\nSet-Cookie: a=b"):
        assert sicheres_ziel(boese, "/s") == "/s", boese
    assert sicheres_ziel("/artikel/1?x=2#a", "/s") == "/artikel/1?x=2#a"


def test_keine_offene_weiterleitung(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg, "lager")
    r = c.post("/buchen", data={"artikel": "1", "typ": "ausgang", "menge": "1", "lagerort": "C1", "weiter": "//evil.example/x"})
    assert r.headers["location"].startswith("/") and not r.headers["location"].startswith("//")
    r = c.post("/artikel/1/etikett?weiter=https://evil.example", data={"anzahl": "1"})
    assert r.headers["location"] == "/artikel/1"
    assert c.post("/bewegungen/1/storno", headers={"referer": "https://evil.example/"}).status_code == 403  # CSRF-Prüfung
    r = c.post("/bewegungen/1/storno", headers={"referer": "http://testserver//evil.example/x"})
    assert r.headers["location"] == "/bewegungen"
    c2 = client(cfg)
    r = c2.post("/login", data={"username": "lager", "passwort": "geheim1", "weiter": "/\\evil.example"})
    assert r.headers["location"] in ("/", "/m")


def test_rolle_und_sperre_wirken_sofort(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    lager = client(cfg, "lager")
    assert lager.post("/buchen", data={"artikel": "1", "typ": "ausgang", "menge": "1", "lagerort": "C1"}).status_code == 303
    with schreib(eng) as con:
        con.execute(text("UPDATE users SET rolle='lesen' WHERE username='lager'"))
    r = lager.post("/buchen", data={"artikel": "1", "typ": "ausgang", "menge": "1", "lagerort": "C1"})
    assert r.status_code == 403  # vorher: weiter erlaubt bis zum Abmelden (bis 30 Tage)
    with schreib(eng) as con:
        con.execute(text("UPDATE users SET aktiv=0 WHERE username='lager'"))
    assert lager.get("/").headers["location"].startswith("/login")
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE typ='ausgang'") == 1


def test_passwortwechsel_beendet_andere_sitzungen(env):
    cfg, _ = env
    a, b = client(cfg, "lager"), client(cfg, "lager")
    r = a.post("/passwort", data={"alt": "geheim1", "neu": "neues-pw1", "neu2": "neues-pw1"})
    assert r.status_code == 303
    assert a.get("/").status_code == 200  # eigene Sitzung bleibt
    assert b.get("/").headers["location"].startswith("/login")  # andere Sitzung mit altem Passwort endet


def test_keine_berechtigung_gibt_403(env):
    cfg, _ = env
    assert client(cfg, "lesen").get("/einstellungen").status_code == 403


def test_api_rollen(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg)
    res = {"artikel": "1", "menge": 1, "fuer": "Test"}
    assert c.post("/api/v1/reservierungen", json=res).status_code == 401
    assert c.post("/api/v1/reservierungen", json=res, headers={"Authorization": "Bearer falsch"}).status_code == 401
    assert c.post("/api/v1/reservierungen", json=res, headers={"Authorization": "Bearer tok_lesen"}).status_code == 403
    assert c.post("/api/v1/buchungen", json={"typ": "ausgang", "artikel": "1", "menge": 1, "lagerplatz": "C1"},
                  headers={"Authorization": "Bearer tok_lesen"}).status_code == 403
    assert c.post("/api/v1/reservierungen", json={**res, "menge": 0}, headers={"Authorization": "Bearer tok_lager"}).status_code == 422
    assert c.post("/api/v1/reservierungen", json=res, headers={"Authorization": "Bearer tok_lager"}).status_code == 200
    assert c.get("/api/v1/artikel", headers={"Authorization": "Bearer tok_lesen"}).status_code == 200
    assert c.get("/api/v1/bewegungen?limit=-5", headers={"Authorization": "Bearer tok_lesen"}).status_code == 200


def test_anhaenge_ohne_aktive_inhalte(env, monkeypatch):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg, "lager")
    c.post("/artikel/1/anhang", files={"datei": ("boese.html", b"<script>alert(1)</script>", "text/html")})
    c.post("/artikel/1/anhang", files={"datei": ("bild.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
    ids = sqlite3.connect(cfg.daten.datenbank).execute("SELECT id, dateiname FROM anhaenge ORDER BY id").fetchall()
    r = c.get(f"/anhang/{ids[0][0]}")
    assert r.headers["content-disposition"].startswith("attachment") and r.headers["x-content-type-options"] == "nosniff"
    assert "text/html" not in r.headers["content-type"] and "sandbox" in r.headers["content-security-policy"]
    r = c.get(f"/anhang/{ids[1][0]}")
    assert r.headers["content-disposition"].startswith("inline") and r.headers["content-type"] == "image/png"
    # unbekannter Artikel: keine verwaiste Datei, kein Serverfehler
    vorher = len(list(Path(cfg.daten.anhaenge).iterdir()))
    r = c.post("/artikel/GIBTSNICHT/anhang", files={"datei": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 303 and len(list(Path(cfg.daten.anhaenge).iterdir())) == vorher
    # Größengrenze
    import app.routes.artikel as artikel_routes
    monkeypatch.setattr(artikel_routes, "MAX_ANHANG", 10)
    c.post("/artikel/1/anhang", files={"datei": ("gross.txt", b"x" * 11, "text/plain")})
    assert anzahl(eng, "SELECT count(*) FROM anhaenge") == 2


def test_sammelentnahme_nicht_im_cookie_und_nicht_doppelt(env):
    cfg, eng = env
    with schreib(eng) as con:
        for i in range(40):
            L(con).artikel_anlegen({"nummer": str(20000 + i), "bezeichnung": "Flansch-Absperrventil DN32 PN100 Edelstahl 1.4571 " + str(i)},
                                   f"C2-R{i % 9 + 1}-{i % 5}", 10)
    c = client(cfg, "lager")
    for i in range(40):
        c.post("/m/korb/neu", data={"artikel": str(20000 + i), "lagerort": f"C2-R{i % 9 + 1}-{i % 5}", "menge": "1"})
    assert len(c.cookies.get("lager_session")) < 3000  # vorher: > 4096 Bytes ab ca. 20 Positionen -> Browser verwirft das Cookie
    assert "40" in c.get("/m").text or c.get("/m/korb").text.count("C2-R") >= 40
    assert c.post("/m/korb/buchen", data={}).status_code == 303
    assert c.post("/m/korb/buchen", data={}).status_code == 303  # zweites Absenden (Doppelklick)
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE typ='ausgang'") == 40
    # Rückgängig: jede Zeile zeigt auf ihre eigene Gegenbuchung
    c.post("/m/rueckgaengig")
    with eng.connect() as con:
        paare = con.execute(text("SELECT a.id, a.storniert_durch, s.storno_von FROM bewegungen a JOIN bewegungen s ON s.id=a.storniert_durch "
                                 "WHERE a.typ='ausgang' AND a.storno_von IS NULL")).all()
    assert len(paare) == 40 and all(a == sv for a, _, sv in paare)


def test_rueckgaengig_umbuchung_verknuepft(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg, "lager")
    c.post("/m/buchen", data={"artikel": "1", "typ": "umbuchung", "menge": "2", "lagerort": "C1", "ziel": "C2"})
    c.post("/m/rueckgaengig")
    with eng.connect() as con:
        assert menge(con, "1", "C1") == 5 and menge(con, "1", "C2") == 0
        rows = con.execute(text("SELECT b.lagerplatz, g.lagerplatz FROM bewegungen b JOIN bewegungen g ON g.id=b.storniert_durch")).all()
    assert sorted(rows) == [("C1", "C1"), ("C2", "C2")]  # Gegenbuchung jeweils am selben Platz


def test_sync_robust_und_offline_kennzeichnung(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg, "lager")
    assert c.post("/m/sync", content=b"kein json", headers={"content-type": "application/json"}).status_code == 400
    assert c.post("/m/sync", json=[1, 2]).status_code == 400
    r = c.post("/m/sync", json={"items": [
        "kaputt",
        {"uuid": "u1", "typ": "ausgang", "artikel": 1, "menge": 1, "lagerort": "C1", "erfasst": "2026-10-08T06:00:00Z"},
        {"uuid": "u2", "typ": "ausgang", "artikel": "1", "menge": None, "lagerort": None},
        {"uuid": "u3", "typ": "ausleihe", "artikel": "1", "menge": "1", "lagerort": "C1", "empfaenger": "Max", "rueckgabe_bis": "2030-01-31"},
        {"uuid": "u1", "typ": "ausgang", "artikel": "1", "menge": 1, "lagerort": "C1"},
    ]})
    assert r.status_code == 200
    e = r.json()
    assert e["u1"]["ok"] and e["u2"]["ok"] is False and e["u3"]["ok"]
    with eng.connect() as con:
        assert menge(con, "1", "C1") == 3
        q, t = con.execute(text("SELECT quelle, text FROM bewegungen WHERE typ='ausgang'")).one()
        assert q == "offline" and "offline erfasst" in t
        assert str(con.execute(text("SELECT rueckgabe_bis FROM bewegungen WHERE typ='ausleihe'")).scalar()) == "2030-01-31"
    assert client(cfg).post("/m/sync", json={"items": []}).status_code == 401
    assert client(cfg, "lesen").post("/m/sync", json={"items": []}).status_code == 403


def test_platz_umbenennen_unbekannter_altname(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ohne Platz"}, "", 0)  # Bewegung ohne Lagerplatz
    c = client(cfg, "lager")
    c.post("/lagerplaetze/speichern", data={"code": "NEU-1", "alt": "GIBTSNICHT"})
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE lagerplatz='NEU-1'") == 0  # vorher: alle Bewegungen ohne Platz umbenannt


def test_wareneingang_auf_stornierte_bestellung(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 0)
        con.execute(text("INSERT INTO bestellungen (artikel_id, menge, geliefert, status) VALUES (1, 5, 0, 'storniert')"))
    c = client(cfg, "lager")
    c.post("/bestellungen/1/wareneingang", data={"menge": "5", "lagerort": "C1"})
    assert anzahl(eng, "SELECT status FROM bestellungen WHERE id=1") == "storniert"
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE typ='eingang'") == 0


def test_verbrauch_ohne_stornierte_entnahmen(env):
    from datetime import date

    from app.services.queries import verbrauch, verbrauch_kostenstelle
    _, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 10)
        e = L(con).ausgang("1", "C1", 4, kostenstelle="K1")
        L(con).ausgang("1", "C1", 1, kostenstelle="K1")
    with schreib(eng) as con:
        L(con).storno(e.id)
    with eng.connect() as con:
        v = verbrauch(con, date(2000, 1, 1), date(2100, 1, 1))
        k = verbrauch_kostenstelle(con, date(2000, 1, 1), date(2100, 1, 1))
    assert v[0]["ausgang"] == 1 and v[0]["eingang"] == 0
    assert k[0]["menge"] == 1


# ------------------------------------------------------------------ 2. Datenübernahme
TRIGGER = """
DELIMITER //
CREATE TRIGGER `bewegungsdaten_after_insert` AFTER INSERT ON `bewegungsdaten` FOR EACH ROW BEGIN
IF 1 THEN
    INSERT INTO lagerorte (Artikel, Lagerort, Anzahl) VALUES (new.Artikelnummer, new.lagerort, new.ISTBestand);
END IF;
END//
DELIMITER ;
"""


MINI = """
INSERT INTO `stammdaten` (`Artikelnummer`, `Bezeichnung`, `Meldebestand`, `Mindestbestand`, `Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `ID`) VALUES
	('10001', 'Kugelhahn', '0', '0', 'Swagelok', 'Kugelhahn', '', '', '', 1);
INSERT INTO `lagerorte` (`Artikel`, `Lagerort`, `Anzahl`, `ID`) VALUES
	('10001', 'C1-F3', 2.000, 1);
INSERT INTO `lagerorte` (`Artikel`, `Lagerort`, `Anzahl`, `ID`) VALUES
	('99999', 'C1-F3', 1.000, 2);
"""


def test_import_ignoriert_trigger(env):
    from app.services.casper_import import dump_lesen, uebernehmen
    _, eng = env
    d = dump_lesen(MINI + TRIGGER)
    assert len(d["lagerorte"]) == 2 and all(r.get("Artikel") != "new.Artikelnummer" for r in d["lagerorte"])
    with schreib(eng) as con:
        r = uebernehmen(con, MINI + TRIGGER)
    assert r.gesamtbestand == 2 and any(h.startswith("1 Lagerort-Zeile") for h in r.hinweise)


@pytest.mark.skipif(not (ECHTER_EXPORT and Path(ECHTER_EXPORT).is_file()), reason="kein echter Casper-Export angegeben")
def test_echter_export_sollwerte_und_ersetzen(env):
    cfg, eng = env
    c = client(cfg, "admin")
    daten = Path(ECHTER_EXPORT).read_bytes()
    r = c.post("/einstellungen/uebernahme", files={"datei": ("daten_export.sql", daten, "text/plain")})
    assert r.status_code == 303
    assert len(c.cookies.get("lager_session")) < 1500  # Bericht liegt nicht mehr im Cookie

    def stand():
        with eng.connect() as con:
            return (con.execute(text("SELECT count(*) FROM artikel")).scalar(), round(con.execute(text("SELECT sum(menge) FROM bestand")).scalar(), 3),
                    con.execute(text("SELECT count(*) FROM bewegungen")).scalar(), con.execute(text("SELECT count(*) FROM lagerplaetze")).scalar(),
                    con.execute(text("SELECT group_concat(nummer || ':' || bezeichnung, '|') FROM (SELECT * FROM artikel ORDER BY nummer)")).scalar())
    erst = stand()
    assert erst[:3] == (821, 377.0, 2702)
    assert "nicht mehr vorhandenen Artikeln" in c.get("/einstellungen?tab=uebernahme").text
    # erneute Übernahme ohne Haken: abgelehnt
    c.post("/einstellungen/uebernahme", files={"datei": ("daten_export.sql", daten, "text/plain")})
    assert not list(Path(cfg.backup.ordner).glob("vor_uebernahme_*.zip")) if Path(cfg.backup.ordner).exists() else True
    # mit "Vorhandene Daten ersetzen": Sicherung vorher, danach identischer Stand
    with schreib(eng) as con:
        L(con).ausgang(con.execute(text("SELECT nummer FROM artikel a JOIN bestand b ON b.artikel_id=a.id WHERE b.menge>0 LIMIT 1")).scalar(),
                       con.execute(text("SELECT p.code FROM lagerplaetze p JOIN bestand b ON b.lagerplatz_id=p.id WHERE b.menge>0 LIMIT 1")).scalar(), 1)
    c.post("/einstellungen/uebernahme", data={"ersetzen": "on"}, files={"datei": ("daten_export.sql", daten, "text/plain")})
    sich = list(Path(cfg.backup.ordner).glob("vor_uebernahme_*.zip"))
    assert len(sich) == 1
    assert stand() == erst
    with zipfile.ZipFile(sich[0]) as z, z.open("lager.db") as f:
        p = Path(cfg.backup.ordner) / "pruef.db"
        p.write_bytes(f.read())
    assert sqlite3.connect(p).execute("SELECT count(*) FROM bewegungen").fetchone()[0] == 2703  # Stand vor dem Ersetzen inkl. Testbuchung


# ------------------------------------------------------------------ 6. Etiketten
def _code128_pruefsumme_unabhaengig(daten: str) -> int:
    """Nach ISO/IEC 15417: Startzeichen B = 104, Gewicht = Position; Zeichenwert = ASCII - 32."""
    summe = 104
    for pos, ch in enumerate(daten, start=1):
        summe += pos * (ord(ch) - 32)
    return summe % 103


@pytest.mark.parametrize("daten", ["10001", "20911", "09052025", "C2-R9-2", "Technikum EG", "A"])
def test_code128_pruefsumme(daten):
    from app.services.labels import _C128, code128_modules
    mods = code128_modules(daten)
    zeichen = ["".join(map(str, mods[i:i + 6])) for i in range(0, len(mods) - 7, 6)]
    assert zeichen[0] == _C128[104]  # Start B
    assert zeichen[-1] == _C128[_code128_pruefsumme_unabhaengig(daten)]
    assert "".join(map(str, mods[-7:])) == "2331112"  # Stopp
    assert all(sum(map(int, z)) == 11 for z in zeichen)  # jedes Zeichen 11 Module breit


@pytest.mark.parametrize("fmt,breite,hoehe", [("45x23", 360, 184), ("60x20", 480, 160)])
def test_tspl_ausgabe(fmt, breite, hoehe):
    from app.services.labels import etikett_tspl
    roh = etikett_tspl("10001", "10001", 'Kugelhahn "DN15" \\ Größe ÄÖÜ\r\nPRINT 999', fmt)
    zeilen = roh.decode("cp1252").split("\r\n")
    assert zeilen[0] == f"SIZE {fmt.split('x')[0]} mm,{fmt.split('x')[1]} mm" and zeilen[1].startswith("GAP ") and "CODEPAGE 1252" in zeilen
    assert zeilen[-2] == "PRINT 1,1" and sum(z.startswith("PRINT") for z in zeilen) == 1  # kein eingeschleuster Druckbefehl
    assert "Größe ÄÖÜ".encode("cp1252") in roh
    bc = next(z for z in zeilen if z.startswith("BARCODE"))
    x, y, typ, h, _, _, schmal, breit, inhalt = re.match(r'BARCODE (\d+),(\d+),"(\w+)",(\d+),(\d),(\d),(\d+),(\d+),"(.*)"', bc).groups()
    from app.services.labels import code128_modules
    assert typ == "128" and inhalt == "10001" and int(x) + sum(code128_modules("10001")) * int(schmal) <= breite and int(y) + int(h) <= hoehe
    for t in (z for z in zeilen if z.startswith("TEXT")):
        assert t.count('"') == 4  # Anführungszeichen im Text ersetzt


def test_tspl_zu_langer_code():
    from app.services.labels import DruckFehler, etikett_tspl
    with pytest.raises(DruckFehler):
        etikett_tspl("X" * 40, "a", "b", "45x23")
    assert b"QRCODE" in etikett_tspl("X" * 40, "a", "b", "45x23", barcode="QR")


def test_druckansicht_seitengroesse(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 1)
    c = client(cfg, "lesen")
    for fmt, b, h in (("45x23", 45, 23), ("60x20", 60, 20)):
        t = c.get(f"/etiketten/druckansicht?nr=1&nr=1&format={fmt}").text
        assert re.search(rf"@page\s*{{[^}}]*size:\s*{b}mm\s+{h}mm", t), fmt
        assert t.count('class="etikett-seite"') == 2
    assert c.get("/etiketten/druckansicht?nr=1&format=99x99").status_code == 200  # unbekanntes Format: Standard statt Serverfehler


# ------------------------------------------------------------------ 8. Datensicherung
def test_backup_konsistent_waehrend_schreiben_und_wiederherstellung(env):
    from app.services.betrieb import backup_erstellen
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 0)
    Path(cfg.daten.anhaenge).mkdir(parents=True, exist_ok=True)
    (Path(cfg.daten.anhaenge) / "foto.jpg").write_bytes(b"jpg")
    stopp = threading.Event()

    def schreiber():
        while not stopp.is_set():
            with schreib(eng) as con:
                L(con).eingang("1", "C1", 1)
    t = threading.Thread(target=schreiber)
    t.start()
    zips = []
    try:
        for _ in range(3):
            zips.append(backup_erstellen(cfg))
            time.sleep(0.05)
    finally:
        stopp.set()
        t.join()
    assert len(set(zips)) == 3  # keine Überschreibung bei gleicher Sekunde
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            assert {"lager.db", "anhaenge/foto.jpg", "LIESMICH.txt"} <= set(zf.namelist())
            assert "lager.db-wal" in zf.read("LIESMICH.txt").decode()
            ziel = Path(cfg.backup.ordner) / "w" / z.stem
            zf.extract("lager.db", ziel)
        k = sqlite3.connect(ziel / "lager.db")
        assert k.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        n, summe = k.execute("SELECT (SELECT count(*) FROM bewegungen WHERE typ='eingang'), (SELECT sum(menge) FROM bestand)").fetchone()
        assert n == summe  # Bewegungen und Bestand passen zusammen (konsistenter Schnappschuss)
    # Wiederherstellung nach Anleitung: alte -wal/-shm löschen, lager.db ersetzen -> identischer Stand
    src = Path(cfg.backup.ordner) / "w" / zips[-1].stem / "lager.db"
    restore = Path(cfg.backup.ordner) / "restore"
    restore.mkdir()
    shutil.copy(cfg.daten.datenbank, restore / "lager.db")
    for endung in ("-wal", "-shm"):
        if Path(cfg.daten.datenbank + endung).exists():
            shutil.copy(cfg.daten.datenbank + endung, restore / f"lager.db{endung}")
    for endung in ("-wal", "-shm"):
        (restore / f"lager.db{endung}").unlink(missing_ok=True)
    shutil.copy(src, restore / "lager.db")
    a = sqlite3.connect(src).execute("SELECT count(*), max(id) FROM bewegungen").fetchone()
    b = sqlite3.connect(restore / "lager.db").execute("SELECT count(*), max(id) FROM bewegungen").fetchone()
    assert a == b


def test_backup_aufbewahrung_loescht_nur_alte_sicherungen(env):
    from app.services.betrieb import backup_erstellen
    cfg, _ = env
    o = Path(cfg.backup.ordner)
    o.mkdir(parents=True)
    alt = o / "lager_backup_20200101_000000.zip"
    fremd = o / "wichtig.zip"
    vor = o / "vor_uebernahme_20200101_000000.zip"
    for f in (alt, fremd, vor):
        f.write_bytes(b"x")
        os.utime(f, (time.time() - 90 * 86400,) * 2)
    backup_erstellen(cfg)
    assert not alt.exists() and fremd.exists() and vor.exists()


# ------------------------------------------------------------------ Konfiguration, Excel, Mail
def test_konfiguration_mit_steuerzeichen_bleibt_lesbar(env, tmp_path):
    from app.config import load_config, save_section
    p = tmp_path / "c.toml"
    save_section("server", {"firmenname": 'CAP"HENIA\nZeile2\\x', "port": 8080}, p)
    save_section("drucker", {"port": 9100}, p)
    cfg = load_config(p)
    assert cfg.server.firmenname == 'CAP"HENIA\nZeile2\\x' and cfg.server.port == 8080 and cfg.drucker.port == 9100


def test_excel_export_ohne_formeln():
    import io

    from openpyxl import load_workbook

    from app.services.excel import tabelle_xlsx
    wb = load_workbook(io.BytesIO(tabelle_xlsx("T", ["a", "b"], [["=HYPERLINK(\"http://x\")", 1]])))
    c = wb.active["A2"]
    assert c.data_type == "s" and c.value.startswith("=")


def test_mail_html_maskiert(env, monkeypatch):
    from app.services import betrieb
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "<b>Ventil</b>", "meldebestand": 5}, "C1", 1)
    gesendet = {}
    monkeypatch.setattr(betrieb, "mail_senden", lambda m, betreff, t, html: gesendet.update(html=html))
    betrieb.meldebestand_mail(eng, cfg)
    assert "&lt;b&gt;Ventil&lt;/b&gt;" in gesendet["html"]


def test_start_mit_leerem_datenordner(tmp_path, monkeypatch):
    from app.config import Config
    from app.main import create_app
    monkeypatch.setenv("LV_HOME", str(tmp_path))
    cfg = Config()
    cfg.daten.datenbank = str(tmp_path / "neu" / "daten" / "lager.db")
    cfg.daten.anhaenge = str(tmp_path / "neu" / "daten" / "anhaenge")
    cfg.server.secret_key = "x"
    create_app(cfg, start_scheduler=False)
    assert (tmp_path / "neu" / "daten" / "lager.db").is_file() and (tmp_path / "neu" / "daten" / "anhaenge").is_dir()
    from app.services.zertifikat import ca_pfade, sicherstellen
    cert, key = sicherstellen(tmp_path / "neu" / "daten")
    assert cert.is_file() and key.is_file() and ca_pfade(tmp_path / "neu" / "daten")[1].is_file()


# ------------------------------------------------------------------ 5. Zertifikate, SQL-Injection
def test_zertifikate_ca_san_erneuerung_und_kein_schluessel(env, monkeypatch, tmp_path):
    from cryptography import x509

    from app.services import zertifikat
    cfg, _ = env
    ordner = tmp_path / "daten"
    monkeypatch.setattr(zertifikat, "lokale_adressen", lambda: ["127.0.0.1", "192.168.10.20"])
    cert_p, _ = zertifikat.sicherstellen(ordner)
    ca = x509.load_pem_x509_certificate(zertifikat.ca_pfade(ordner)[0].read_bytes())
    bc = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    server = x509.load_pem_x509_certificates(cert_p.read_bytes())[0]
    san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "192.168.10.20" in {str(i) for i in san.get_values_for_type(x509.IPAddress)} and "localhost" in san.get_values_for_type(x509.DNSName)
    assert server.issuer == ca.subject and server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    # IP-Wechsel: beim nächsten Start neues Serverzertifikat mit neuer IP, gleiche CA
    monkeypatch.setattr(zertifikat, "lokale_adressen", lambda: ["127.0.0.1", "10.0.0.7"])
    server2 = x509.load_pem_x509_certificates(zertifikat.sicherstellen(ordner)[0].read_bytes())[0]
    assert "10.0.0.7" in {str(i) for i in server2.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)}
    assert server2.issuer == ca.subject
    # /zertifikat.crt liefert nur das CA-Zertifikat (DER), nie einen privaten Schlüssel
    c = client(cfg)
    r = c.get("/zertifikat.crt")
    assert r.status_code == 200 and b"PRIVATE KEY" not in r.content
    assert x509.load_der_x509_certificate(r.content).extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    for pfad in ("/static/../daten/lager_ca_schluessel.pem", "/static/%2e%2e/daten/lager_ca_schluessel.pem", "/einstellungen/backup/..%2flager.db"):
        assert b"PRIVATE KEY" not in c.get(pfad).content


def test_sql_injection_stichprobe(env):
    cfg, eng = env
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1", 5)
    c = client(cfg, "lesen")
    for q in ("' OR 1=1 --", "%' UNION SELECT pw_hash FROM users --", "\"; DROP TABLE artikel; --"):
        for pfad in (f"/artikel?q={q}", f"/bewegungen?q={q}", f"/m/suche?q={q}", f"/artikel/{q}", f"/lagerplaetze/ansicht?code={q}"):
            r = c.get(pfad)
            assert r.status_code == 200 and "pbkdf2$" not in r.text, pfad
    assert anzahl(eng, "SELECT count(*) FROM artikel") == 1
