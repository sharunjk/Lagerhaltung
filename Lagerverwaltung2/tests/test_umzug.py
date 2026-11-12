"""2.10.0: Umzugspaket – ganzes System als ZIP, altes System danach „nur lesen“; entpacken und starten auf dem neuen PC.
Alle Daten erfunden."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from test_cmms_phase0 import cmms_an
from test_pruefung import L, anzahl, client, schreib


def _grunddaten(cfg, eng):
    cmms_an(cfg)
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "4711", "bezeichnung": "Gleitringdichtung"}, "C1-R1-1", 5)
    anh = cfg.path(cfg.daten.anhaenge)
    anh.mkdir(parents=True, exist_ok=True)
    (anh / "foto_test.jpg").write_bytes(b"\xff\xd8 Testfoto")
    from app import config
    sk = config.BASE_DIR / ".secret_key"
    if not sk.exists():
        sk.write_text("a" * 64)
    from app.services.zertifikat import ca_sicherstellen
    ca_sicherstellen(cfg.path("daten"))
    admin = client(cfg, "admin")
    admin.post("/ih/schichtbuch/neu", data={"titel": "Pumpe undicht"})
    return admin


def _erstellen(admin, ziel: Path, **extra):
    return admin.post("/einstellungen/umzug", data={"passwort": "Lager-Test-2026", "ordner": str(ziel), "bestaetigt": "on", **extra},
                      follow_redirects=True)


def test_umzugspaket_inhalt_und_sperre(env, tmp_path):
    cfg, eng = env
    admin = _grunddaten(cfg, eng)
    ziel = tmp_path / "usb"
    # falsches Passwort / ohne Bestätigung: nichts passiert
    r = admin.post("/einstellungen/umzug", data={"passwort": "falsch", "ordner": str(ziel), "bestaetigt": "on"}, follow_redirects=True)
    assert "Passwort ist falsch" in r.text and not (ziel.exists() and list(ziel.glob("*.zip")))
    r = admin.post("/einstellungen/umzug", data={"passwort": "Lager-Test-2026", "ordner": str(ziel)}, follow_redirects=True)
    assert "bestätigen" in r.text and anzahl(eng, "SELECT count(*) FROM settings WHERE schluessel='umzug.sperre'") == 0
    assert client(cfg, "lager").post("/einstellungen/umzug", data={}).status_code == 403
    # erstellen
    r = _erstellen(admin, ziel)
    assert "Umzugspaket erstellt" in r.text and "Nur lesen" in r.text
    pakete = list(ziel.glob("Umzugspaket_*.zip"))
    assert len(pakete) == 1 and not list(ziel.glob("*.teil"))
    with zipfile.ZipFile(pakete[0]) as z:
        namen = z.namelist()
        oben = namen[0].split("/")[0]
        rel = {n[len(oben) + 1:] for n in namen}
        for pflicht in ("app/main.py", "app/services/umzug.py", "windows/UMZUG_ABSCHLIESSEN_als_Admin.bat", "daten/lager.db", "config.toml",
                        ".secret_key", "daten/anhaenge/foto_test.jpg", "daten/lager_ca.crt", "daten/lager_ca_schluessel.pem",
                        "UMZUG_LIESMICH.txt", "daten/umzug.json", "logs/", "backups/"):
            assert pflicht in rel, pflicht
        assert not any("__pycache__" in n or n.endswith(".pyc") or n.endswith(".teil") for n in namen)
        assert not any(n.startswith(f"{oben}/backups/") and n != f"{oben}/backups/" for n in namen)  # ohne Sicherungen
        assert not any(r.startswith("testsystem/") for r in rel)
        import tomllib
        conf = tomllib.loads(z.read(f"{oben}/config.toml").decode())
        assert conf["daten"] == {"datenbank": "daten/lager.db", "anhaenge": "daten/anhaenge"} and conf["cmms"]["aktiv"] is True
        liesmich = z.read(f"{oben}/UMZUG_LIESMICH.txt").decode()
        assert "UMZUG_ABSCHLIESSEN_als_Admin.bat" in liesmich and "VERTRAULICH" in liesmich
        db = tmp_path / "pruef.db"
        db.write_bytes(z.read(f"{oben}/daten/lager.db"))
    k = sqlite3.connect(db)
    assert k.execute("SELECT count(*) FROM artikel").fetchone()[0] == 1 and k.execute("SELECT count(*) FROM sb_meldungen").fetchone()[0] == 1
    assert k.execute("SELECT count(*) FROM settings WHERE schluessel='umzug.sperre'").fetchone()[0] == 0  # neuer PC nicht gesperrt
    k.close()
    # altes System: nur lesen – PC, Scanner-App, API, Instandhaltung; Lesen und Anmelden gehen
    lager = client(cfg, "lager")
    r = lager.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"})
    assert r.status_code == 423 and "Nur lesen" in r.text and anzahl(eng, "SELECT menge FROM bestand") == 5
    assert lager.post("/m/sync", json={"items": []}).status_code == 423
    assert client(cfg).post("/api/v1/buchungen", headers={"Authorization": "Bearer tok_lager"}, json={}).status_code == 423
    assert admin.post("/ih/schichtbuch/neu", data={"titel": "x"}).status_code == 423
    seite = lager.get("/artikel/4711")
    assert seite.status_code == 200 and "Nur lesen" in seite.text
    assert "Nur lesen" in lager.get("/m").text
    # bleibt nach Neustart bestehen
    assert client(cfg, "admin").post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"}).status_code == 423
    # zweites Paket (z. B. anderer USB-Stick) auch während der Sperre
    assert "Umzugspaket erstellt" in _erstellen(admin, tmp_path / "usb2").text
    # aufheben: falsches Passwort nicht, richtiges ja
    admin.post("/einstellungen/umzug/aufheben", data={"passwort": "falsch"})
    assert anzahl(eng, "SELECT count(*) FROM settings WHERE schluessel='umzug.sperre'") == 1
    admin.post("/einstellungen/umzug/aufheben", data={"passwort": "Lager-Test-2026"})
    assert lager.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"}).status_code == 303
    assert anzahl(eng, "SELECT menge FROM bestand") == 4
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion IN ('Umzugspaket erstellt', 'Umzugs-Sperre aufgehoben')") == 3


def test_umzugspaket_mit_sicherungen_und_fehlerfall(env, tmp_path, monkeypatch):
    cfg, eng = env
    admin = _grunddaten(cfg, eng)
    from app.services import sicherung
    sicherung.sichern(cfg, eng, erzwingen=True)
    _erstellen(admin, tmp_path / "usb", mit_backups="on")
    with zipfile.ZipFile(next((tmp_path / "usb").glob("Umzugspaket_*.zip"))) as z:
        assert any("/backups/lager_backup_" in n for n in z.namelist())
    admin.post("/einstellungen/umzug/aufheben", data={"passwort": "Lager-Test-2026"})
    # Fehler beim Packen: keine halbe Datei, keine Sperre
    def kaputt(*a, **k):
        raise OSError("Datenträger voll")
    monkeypatch.setattr(sicherung, "db_kopie", kaputt)
    r = _erstellen(admin, tmp_path / "usb3")
    assert "nicht erstellt" in r.text and "Datenträger voll" in r.text
    assert not list((tmp_path / "usb3").glob("*")) and anzahl(eng, "SELECT count(*) FROM settings WHERE schluessel='umzug.sperre'") == 0
    assert admin.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"}).status_code == 303
    # Ziel ist eine Datei statt eines Ordners
    (tmp_path / "datei").write_text("x")
    assert "nicht erstellt" in _erstellen(admin, tmp_path / "datei").text


@pytest.mark.skipif(os.name == "nt", reason="Startprobe nutzt POSIX-Pfade")
def test_entpacken_und_starten_auf_neuem_pc(env, tmp_path):
    """Paket entpacken, in einem neuen Ordner starten: gleiche Daten, gleiche Benutzer, nicht gesperrt, Zertifikat bleibt."""
    cfg, eng = env
    admin = _grunddaten(cfg, eng)
    _erstellen(admin, tmp_path / "usb")
    paket = next((tmp_path / "usb").glob("Umzugspaket_*.zip"))
    neu = tmp_path / "neuer_pc"
    with zipfile.ZipFile(paket) as z:
        z.extractall(neu)
    wurzel = next(neu.iterdir())
    ca_alt = cfg.path("daten").joinpath("lager_ca.crt").read_bytes()
    probe = textwrap.dedent("""
        import json
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.config import BASE_DIR
        c = TestClient(create_app(start_scheduler=False), follow_redirects=False)
        login = c.post("/login", data={"username": "admin", "passwort": "Lager-Test-2026"}).status_code
        artikel = c.get("/artikel/4711")
        buchung = c.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "2", "lagerort": "C1-R1-1"}).status_code
        meldung = "Pumpe undicht" in c.get("/ih/schichtbuch/meldungen").text
        print(json.dumps({"basis": str(BASE_DIR), "login": login, "artikel": artikel.status_code, "gesperrt": "Nur lesen" in artikel.text,
                          "buchung": buchung, "meldung": meldung, "foto": (BASE_DIR / "daten/anhaenge/foto_test.jpg").exists()}))
    """)
    umgebung = {k: v for k, v in os.environ.items() if not k.startswith("LV_")}
    erg = subprocess.run([sys.executable, "-c", probe], cwd=wurzel, env={**umgebung, "LV_HOME": str(wurzel)},
                         capture_output=True, text=True, timeout=120)
    assert erg.returncode == 0, erg.stderr[-2000:]
    d = json.loads(erg.stdout.strip().splitlines()[-1])
    assert d == {"basis": str(wurzel), "login": 303, "artikel": 200, "gesperrt": False, "buchung": 303, "meldung": True, "foto": True}, d
    assert (wurzel / "daten/lager_ca.crt").read_bytes() == ca_alt  # Handscanner müssen nichts neu installieren
    # das alte System ist weiter gesperrt
    assert admin.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"}).status_code == 423
