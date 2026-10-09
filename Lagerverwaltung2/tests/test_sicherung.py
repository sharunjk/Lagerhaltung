"""Datensicherung 2.3.0: mehrere Speicherorte, mehrere Uhrzeiten, nur bei Änderung, Status/Warnungen, Ordnerauswahl,
Wiederherstellen."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pytest

from test_pruefung import L, anzahl, client, schreib

PW = "Lager-Test-2026"


def mit_artikel(eng, nr="1", menge=5):
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": nr, "bezeichnung": f"Artikel {nr}"}, "C1", menge)


def zwei_ziele(cfg, tmp: Path, tage=90):
    cfg.backup.weitere_ziele = [{"ordner": str(tmp / "usb" / "Lagerbackup"), "aufbewahren_tage": tage}]
    return Path(cfg.backup.ordner), tmp / "usb" / "Lagerbackup"


def zips(o: Path, muster="lager_backup_*.zip"):
    return sorted(o.glob(muster)) if o.exists() else []


# ------------------------------------------------------------------ Uhrzeiten und Termine
def test_uhrzeiten_lesen_und_pruefen():
    from app.services.sicherung import uhrzeiten
    assert uhrzeiten("22:00") == ["22:00"]
    assert uhrzeiten("7:00, 12:00;16.30  22:00, 12:00") == ["07:00", "12:00", "16:30", "22:00"]
    for falsch in ("", "  ", "24:00", "12:60", "mittags", "12", "7:5"):
        with pytest.raises(ValueError):
            uhrzeiten(falsch)


def test_faelliger_termin():
    from app.services.sicherung import faelliger_termin
    t = "07:00, 12:00, 22:00"
    assert faelliger_termin(t, datetime(2026, 10, 9, 6, 59)) is None
    assert faelliger_termin(t, datetime(2026, 10, 9, 7, 0)) == "2026-10-09 07:00"
    assert faelliger_termin(t, datetime(2026, 10, 9, 15, 30)) == "2026-10-09 12:00"
    assert faelliger_termin(t, datetime(2026, 10, 9, 23, 59)) == "2026-10-09 22:00"
    assert faelliger_termin("kaputt", datetime(2026, 10, 9, 23, 59)) is None


# ------------------------------------------------------------------ Konfiguration
def test_konfiguration_weitere_ziele_bleibt_lesbar(tmp_path):
    from app.config import load_config, save_section
    p = tmp_path / "config.toml"
    p.write_text('[server]\nport = 8080\n\n[backup]\naktiv = true\nordner = "backups"\nuhrzeit = "22:00"\naufbewahren_tage = 30\n', encoding="utf-8")
    alt = load_config(p)  # Konfiguration aus 2.2.x: neue Felder mit Standardwerten
    assert alt.backup.weitere_ziele == [] and alt.backup.nur_bei_aenderung is True and alt.server.port == 8080
    save_section("backup", {"uhrzeit": "07:00, 22:00", "weitere_ziele": [
        {"ordner": "S:\\Lagerbackup", "aufbewahren_tage": 90}, {"ordner": '\\\\server\\frei "gabe"', "aufbewahren_tage": 14}]}, p)
    neu = load_config(p)
    assert neu.backup.weitere_ziele == [{"ordner": "S:\\Lagerbackup", "aufbewahren_tage": 90},
                                        {"ordner": '\\\\server\\frei "gabe"', "aufbewahren_tage": 14}]
    assert neu.backup.uhrzeit == "07:00, 22:00" and neu.backup.ordner == "backups" and neu.server.port == 8080


def test_ziele_ohne_doppelte_und_leere(env, tmp_path):
    from app.services.sicherung import ziele
    cfg, _ = env
    cfg.backup.weitere_ziele = [{"ordner": cfg.backup.ordner}, {"ordner": " "}, {"ordner": str(tmp_path / "x"), "aufbewahren_tage": "abc"}, "kaputt"]
    z = ziele(cfg)
    assert [x.haupt for x in z] == [True, False] and z[1].aufbewahren_tage == 30


# ------------------------------------------------------------------ Sichern
def test_sichern_in_alle_speicherorte_gleicher_inhalt(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    Path(cfg.daten.anhaenge).mkdir(parents=True, exist_ok=True)
    (Path(cfg.daten.anhaenge) / "foto.jpg").write_bytes(b"jpg")
    haupt, usb = zwei_ziele(cfg, tmp_path)
    erg = sicherung.sichern(cfg, eng)
    assert all(e.ok and not e.unveraendert for e in erg) and len(erg) == 2
    a, b = zips(haupt), zips(usb)
    assert len(a) == len(b) == 1 and a[0].name == b[0].name and a[0].read_bytes() == b[0].read_bytes()
    with zipfile.ZipFile(b[0]) as z:
        assert {"lager.db", "anhaenge/foto.jpg", "LIESMICH.txt"} <= set(z.namelist())
    assert not list(usb.glob("*.teil"))
    with eng.connect() as con:
        st = sicherung.status_lesen(con)
        assert {v["datei"] for v in st.values()} == {str(a[0]), str(b[0])}
        assert sicherung.warnungen(cfg, con) == []


def test_nur_bei_aenderung(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    haupt, usb = zwei_ziele(cfg, tmp_path)
    sicherung.sichern(cfg, eng)
    # nichts geändert (auch kein Login zählt) -> keine neue Datei, aber Zustand "aktuell"
    with schreib(eng) as con:
        con.exec_driver_sql("UPDATE users SET letzter_login = CURRENT_TIMESTAMP")
    erg = sicherung.sichern(cfg, eng)
    assert all(e.ok and e.unveraendert for e in erg)
    assert len(zips(haupt)) == len(zips(usb)) == 1
    # Buchung -> neue Sicherung
    with schreib(eng) as con:
        L(con).eingang("1", "C1", 1)
    time.sleep(1.1)
    erg = sicherung.sichern(cfg, eng)
    assert all(e.ok and not e.unveraendert for e in erg)
    assert len(zips(haupt)) == len(zips(usb)) == 2
    # neues Foto -> neue Sicherung
    Path(cfg.daten.anhaenge).mkdir(parents=True, exist_ok=True)
    (Path(cfg.daten.anhaenge) / "neu.jpg").write_bytes(b"x")
    time.sleep(1.1)
    assert not any(e.unveraendert for e in sicherung.sichern(cfg, eng))
    # "Jetzt sichern" schreibt immer
    time.sleep(1.1)
    assert not any(e.unveraendert for e in sicherung.sichern(cfg, eng, erzwingen=True))
    assert len(zips(haupt)) == 4
    # ausgeschaltet -> jedes Mal eine Datei
    cfg.backup.nur_bei_aenderung = False
    time.sleep(1.1)
    sicherung.sichern(cfg, eng)
    assert len(zips(usb)) == 5


def test_neuer_speicherort_bekommt_sofort_eine_sicherung(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    sicherung.sichern(cfg, eng)
    _, usb = zwei_ziele(cfg, tmp_path)
    erg = sicherung.sichern(cfg, eng)  # keine Änderung, aber auf dem neuen Speicherort liegt noch nichts
    assert erg[0].unveraendert and not erg[1].unveraendert and len(zips(usb)) == 1
    # Datei auf dem Stick gelöscht -> wird neu geschrieben
    zips(usb)[0].unlink()
    erg = sicherung.sichern(cfg, eng)
    assert not erg[1].unveraendert and len(zips(usb)) == 1


def test_ausgefallener_speicherort_haelt_andere_nicht_auf(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    blockiert = tmp_path / "keinordner"
    blockiert.write_text("ich bin eine Datei")  # Ordner lässt sich nicht anlegen
    cfg.backup.weitere_ziele = [{"ordner": str(blockiert / "sub")}, {"ordner": str(tmp_path / "ok")}]
    erg = sicherung.sichern(cfg, eng)
    assert [e.ok for e in erg] == [True, False, True]
    assert erg[1].fehler and len(zips(tmp_path / "ok")) == 1
    with eng.connect() as con:
        w = sicherung.warnungen(cfg, con)
        u = sicherung.uebersicht(cfg, con)
    assert len(w) == 1 and str(blockiert / "sub") in w[0]
    assert u[1]["warnung"] and not u[0]["warnung"] and not u[2]["warnung"]
    # wieder erreichbar -> Warnung verschwindet
    blockiert.unlink()
    sicherung.sichern(cfg, eng)
    with eng.connect() as con:
        assert sicherung.warnungen(cfg, con) == []


def test_warnung_bei_alter_sicherung_und_ausgeschaltet(env):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    with eng.connect() as con:
        assert "noch keine Sicherung" in sicherung.warnungen(cfg, con)[0]
    sicherung.sichern(cfg, eng)
    with eng.connect() as con:
        u = sicherung.uebersicht(cfg, con, jetzt=datetime(2099, 1, 1))
        assert "älter als einen Tag" in u[0]["warnung"]
    cfg.backup.aktiv = False
    with eng.connect() as con:
        assert sicherung.warnungen(cfg, con) == ["Die automatische Datensicherung ist ausgeschaltet."]


def test_sicherungen_aus_alter_version_werden_erkannt(env):
    from app.services import sicherung
    cfg, eng = env
    o = Path(cfg.backup.ordner)
    o.mkdir(parents=True)
    (o / "lager_backup_20261008_220000.zip").write_bytes(b"x")  # aus 2.2.x, noch kein Status
    with eng.connect() as con:
        u = sicherung.uebersicht(cfg, con)
    assert u[0]["ok_am"] and not u[0]["warnung"]


def test_aufraeumen_behaelt_die_neuesten(tmp_path):
    from app.services.sicherung import MIN_BEHALTEN, aufraeumen
    for i in range(6):
        f = tmp_path / f"lager_backup_2020010{i}_000000.zip"
        f.write_bytes(b"x")
        os.utime(f, (time.time() - (100 - i) * 86400,) * 2)
    teil = tmp_path / "lager_backup_20200101_000000.zip.teil"
    teil.write_bytes(b"x")
    os.utime(teil, (time.time() - 7200,) * 2)
    assert aufraeumen(tmp_path, 30) == 6 - MIN_BEHALTEN
    assert len(list(tmp_path.glob("*.zip"))) == MIN_BEHALTEN and not teil.exists()


# ------------------------------------------------------------------ Zeitplaner
def test_zeitplaner_termine_und_nachholen(env, tmp_path):
    from app.services import sicherung
    from app.services.betrieb import Zeitplaner, get_setting
    cfg, eng = env
    mit_artikel(eng)
    blockiert = tmp_path / "usb"
    blockiert.write_text("Stick fehlt")
    cfg.backup.weitere_ziele = [{"ordner": str(blockiert)}]
    cfg.backup.uhrzeit = "07:00, 12:00"
    z = Zeitplaner(eng, lambda: cfg)
    assert z.sicherung_pruefen(cfg, datetime(2026, 10, 9, 6, 30)) is None
    erg = z.sicherung_pruefen(cfg, datetime(2026, 10, 9, 12, 30))
    assert [e.ok for e in erg] == [True, False]
    with eng.connect() as con:
        assert get_setting(con, sicherung.TERMIN) == "2026-10-09 12:00"
    assert z.nachholen and z.nachholen[1] == {erg[1].ziel.schluessel}
    # nächste Minute: kein neuer Termin, Wiederholung erst nach 30 Minuten
    assert z.sicherung_pruefen(cfg, datetime(2026, 10, 9, 12, 31)) is None
    # Stick wieder da, Wiederholungszeit erreicht -> nur der fehlende Speicherort wird beschrieben
    blockiert.unlink()
    z.nachholen = (0, z.nachholen[1])
    n_haupt = len(zips(Path(cfg.backup.ordner)))
    erg = z.sicherung_pruefen(cfg, datetime(2026, 10, 9, 13, 5))
    assert erg[0].uebersprungen and erg[1].ok and len(zips(blockiert)) == 1
    assert len(zips(Path(cfg.backup.ordner))) == n_haupt and z.nachholen is None
    # ausgeschaltet -> nichts
    cfg.backup.aktiv = False
    assert z.sicherung_pruefen(cfg, datetime(2026, 10, 10, 12, 30)) is None


# ------------------------------------------------------------------ Oberfläche
def test_einstellungen_speichern_und_rechte(env, tmp_path):
    from app.config import load_config
    cfg, _ = env
    c = client(cfg, "admin")
    usb = tmp_path / "usb"
    r = c.post("/einstellungen/backup", data={"aktiv": "on", "uhrzeit": "22:00, 7:00", "nur_bei_aenderung": "on",
                                              "ziel_ordner": [cfg.backup.ordner, str(usb), ""], "ziel_tage": ["30", "90", "5"],
                                              "aktion": "jetzt"})
    assert r.status_code == 303
    gespeichert = load_config()
    assert gespeichert.backup.uhrzeit == "07:00, 22:00"
    assert gespeichert.backup.weitere_ziele == [{"ordner": str(usb), "aufbewahren_tage": 90}]
    assert len(zips(usb)) == 1 and len(zips(Path(cfg.backup.ordner))) == 1
    seite = c.get("/einstellungen?tab=backup").text
    assert str(usb) in seite and "in Ordnung" in seite and "lvSicherung" in seite
    # ungültige Uhrzeit -> nichts gespeichert
    c.post("/einstellungen/backup", data={"uhrzeit": "25:00", "ziel_ordner": ["backups"], "ziel_tage": ["30"]})
    assert load_config().backup.uhrzeit == "07:00, 22:00"
    # alle neuen Seiten nur für Admins
    for rolle in ("lager", "lesen"):
        c2 = client(cfg, rolle)
        for m, url in (("get", "/einstellungen/backup-ordner?pfad=/"), ("post", "/einstellungen/backup-pruefen"),
                       ("post", "/einstellungen/backup-ordner"), ("get", "/einstellungen/backup-wiederherstellen?quelle=x"),
                       ("post", "/einstellungen/backup-wiederherstellen"), ("post", "/einstellungen/backup-hochladen"),
                       ("post", "/einstellungen/backup")):
            assert getattr(c2, m)(url).status_code == 403, (rolle, url)


def test_ordnerauswahl_pruefen_und_anlegen(env, tmp_path):
    cfg, _ = env
    c = client(cfg, "admin")
    (tmp_path / "Ziel A").mkdir()
    (tmp_path / ".versteckt").mkdir()
    (tmp_path / "datei.txt").write_text("x")
    d = c.get("/einstellungen/backup-ordner", params={"pfad": str(tmp_path)}).json()
    assert "Ziel A" in d["ordner"] and ".versteckt" not in d["ordner"] and "datei.txt" not in d["ordner"]
    assert d["eltern"] == str(tmp_path.parent)
    assert c.get("/einstellungen/backup-ordner").json()["laufwerke"]  # Startansicht: Laufwerke
    # Ordner, den es noch nicht gibt: nächster vorhandener übergeordneter Ordner + Hinweis
    d = c.get("/einstellungen/backup-ordner", params={"pfad": str(tmp_path / "neu" / "tiefer")}).json()
    assert d["pfad"] == str(tmp_path) and "noch nicht" in d["hinweis"]
    r = c.post("/einstellungen/backup-ordner", data={"pfad": str(tmp_path), "name": "Lagerbackup"}).json()
    assert r["ok"] and (tmp_path / "Lagerbackup").is_dir()
    for falsch in ("..", "a/b", "a\\b", "c:", "", "x" * 101):
        assert not c.post("/einstellungen/backup-ordner", data={"pfad": str(tmp_path), "name": falsch}).json()["ok"]
    r = c.post("/einstellungen/backup-pruefen", data={"pfad": str(tmp_path / "Lagerbackup" / "neu")}).json()
    assert r["ok"] and "beschreibbar" in r["text"] and not list((tmp_path / "Lagerbackup" / "neu").iterdir())
    (tmp_path / "blockiert").write_text("x")
    r = c.post("/einstellungen/backup-pruefen", data={"pfad": str(tmp_path / "blockiert" / "sub")}).json()
    assert not r["ok"] and r["text"]
    assert not c.post("/einstellungen/backup-pruefen", data={"pfad": ""}).json()["ok"]


def test_startseite_warnt_nur_admins(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    (tmp_path / "blockiert").write_text("x")
    cfg.backup.weitere_ziele = [{"ordner": str(tmp_path / "blockiert" / "sub")}]
    c = client(cfg, "admin")
    from app import db
    sicherung.sichern(cfg, db.engine())
    assert "Datensicherung prüfen" in c.get("/").text
    assert "Datensicherung prüfen" not in client(cfg, "lager").get("/").text


def test_download_nur_aus_speicherorten(env, tmp_path):
    from app.services import sicherung
    cfg, eng = env
    mit_artikel(eng)
    _, usb = zwei_ziele(cfg, tmp_path)
    c = client(cfg, "admin")
    from app import db
    sicherung.sichern(cfg, db.engine())
    name = zips(usb)[0].name
    assert c.get(f"/einstellungen/backup/{name}?ziel=1").status_code == 200
    assert c.get(f"/einstellungen/backup/{name}?ziel=5").status_code == 404
    assert c.get("/einstellungen/backup/..%5Clager.db?ziel=0").status_code == 404


# ------------------------------------------------------------------ Wiederherstellen
def _stand(eng):
    return (anzahl(eng, "SELECT count(*) FROM artikel"), anzahl(eng, "SELECT count(*) FROM bewegungen"))


def test_wiederherstellen_ueber_oberflaeche(env, tmp_path):
    from app import db
    from app.services import sicherung
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    mit_artikel(eng, "1")
    anh = Path(cfg.daten.anhaenge)
    anh.mkdir(parents=True, exist_ok=True)
    (anh / "alt.jpg").write_bytes(b"alt")
    sicherung.sichern(cfg, eng)
    datei = zips(Path(cfg.backup.ordner))[0]
    stand = _stand(eng)
    # danach weitergearbeitet
    mit_artikel(eng, "2")
    (anh / "neu.jpg").write_bytes(b"neu")
    (anh / "alt.jpg").write_bytes(b"geaendert")
    assert _stand(eng) != stand
    seite = c.get(f"/einstellungen/backup-wiederherstellen?quelle={quote(str(datei), safe='')}").text
    assert "Vergleich" in seite and "Wiederherstellen" in seite
    # falsches Passwort / ohne Bestätigung -> nichts passiert
    for daten in ({"quelle": str(datei), "passwort": "falsch", "bestaetigt": "on"}, {"quelle": str(datei), "passwort": PW}):
        assert c.post("/einstellungen/backup-wiederherstellen", data=daten).status_code == 303
        assert _stand(eng) != stand
    assert not zips(Path(cfg.backup.ordner), "vor_wiederherstellung_*.zip")
    # richtig
    r = c.post("/einstellungen/backup-wiederherstellen", data={"quelle": str(datei), "passwort": PW, "bestaetigt": "on"})
    assert r.headers["location"] == "/einstellungen?tab=backup"
    assert _stand(eng)[0] == stand[0]
    assert sorted(p.name for p in anh.iterdir()) == ["alt.jpg"] and (anh / "alt.jpg").read_bytes() == b"alt"
    assert not list(anh.parent.glob(".anhaenge_*"))
    vorher = zips(Path(cfg.backup.ordner), "vor_wiederherstellung_*.zip")
    assert len(vorher) == 1
    with zipfile.ZipFile(vorher[0]) as z:
        assert "anhaenge/neu.jpg" in z.namelist()  # der ersetzte Stand ist gesichert
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Datensicherung wiederhergestellt'") == 1
    # Programm läuft weiter: Seiten, Buchen, Sicherungsstatus des PCs bleibt erhalten
    assert c.get("/artikel").status_code == 200
    with schreib(eng) as con:
        L(con).eingang("1", "C1", 1)
    with eng.connect() as con:
        assert sicherung.status_lesen(con)
    k = sqlite3.connect(cfg.daten.datenbank)
    assert k.execute("PRAGMA journal_mode").fetchone()[0] == "wal" and k.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_wiederherstellen_rueckgaengig(env):
    """Die automatische Sicherung "vor_wiederherstellung" lässt sich selbst wiederherstellen."""
    from app import db
    from app.services import sicherung
    cfg, _ = env
    client(cfg)
    eng = db.engine()
    mit_artikel(eng, "1")
    sicherung.sichern(cfg, eng)
    datei = zips(Path(cfg.backup.ordner))[0]
    mit_artikel(eng, "2")
    stand_neu = _stand(eng)
    r = sicherung.wiederherstellen(cfg, eng, datei, "admin")
    assert _stand(eng) != stand_neu
    sicherung.wiederherstellen(cfg, eng, Path(cfg.backup.ordner) / r["vorher"], "admin")
    assert _stand(eng)[0] == stand_neu[0]


def _zip(tmp_path, name, dateien: dict) -> Path:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for n, inhalt in dateien.items():
            z.writestr(n, inhalt)
    return p


def test_ungueltige_sicherungen_werden_abgelehnt(env, tmp_path):
    from app import db
    from app.services import sicherung
    cfg, _ = env
    client(cfg)
    eng = db.engine()
    mit_artikel(eng)
    sicherung.sichern(cfg, eng)
    gut = zips(Path(cfg.backup.ordner))[0]
    db_bytes = zipfile.ZipFile(gut).read("lager.db")
    # Sicherung ohne Admin
    roh = tmp_path / "ohne_admin.db"
    roh.write_bytes(db_bytes)
    k = sqlite3.connect(roh)
    k.execute("UPDATE users SET rolle='lager'")
    k.commit()
    k.close()
    faelle = {
        "keinzip": tmp_path / "kein.zip",
        "ohnedb": _zip(tmp_path, "ohnedb.zip", {"x.txt": "x"}),
        "keinedb": _zip(tmp_path, "keinedb.zip", {"lager.db": "das ist keine Datenbank" * 100}),
        "pfad": _zip(tmp_path, "pfad.zip", {"lager.db": db_bytes, "anhaenge/../../boese.txt": "x"}),
        "absolut": _zip(tmp_path, "absolut.zip", {"lager.db": db_bytes, "anhaenge/C:/boese.txt": "x"}),
        "ohneadmin": _zip(tmp_path, "ohneadmin.zip", {"lager.db": roh.read_bytes()}),
        "fremd": _zip(tmp_path, "fremd.zip", {"lager.db": _fremde_db(tmp_path)}),
    }
    faelle["keinzip"].write_bytes(b"PK kaputt")
    stand = _stand(eng)
    for name, p in faelle.items():
        with pytest.raises(sicherung.WiederherstellFehler):
            sicherung.wiederherstellen(cfg, eng, p, "admin")
        assert _stand(eng) == stand, name
    assert not zips(Path(cfg.backup.ordner), "vor_wiederherstellung_*.zip")  # Prüfung vor jeder Änderung
    assert not (tmp_path / "boese.txt").exists()
    c = client(cfg, "admin")
    seite = c.get(f"/einstellungen/backup-wiederherstellen?quelle={quote(str(faelle['ohneadmin']), safe='')}").text
    assert "keinen aktiven Administrator" in seite and 'name="passwort"' not in seite
    assert "nicht gefunden" in c.get("/einstellungen/backup-wiederherstellen?quelle=relativ.zip").text


def _fremde_db(tmp_path) -> bytes:
    p = tmp_path / "fremd.db"
    k = sqlite3.connect(p)
    k.execute("CREATE TABLE kunden(x)")
    k.commit()
    k.close()
    return p.read_bytes()


def test_wiederherstellen_per_hochladen(env, tmp_path):
    from app import db
    from app.services import sicherung
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    mit_artikel(eng, "1")
    sicherung.sichern(cfg, eng)
    inhalt = zips(Path(cfg.backup.ordner))[0].read_bytes()
    mit_artikel(eng, "2")
    r = c.post("/einstellungen/backup-hochladen", files={"datei": ("sicherung.zip", io.BytesIO(inhalt), "application/zip")})
    ziel = r.headers["location"]
    assert ziel.startswith("/einstellungen/backup-wiederherstellen?quelle=") and "sicherung.zip" in ziel
    assert "Vergleich" in c.get(ziel).text
    upload = Path(cfg.daten.datenbank).parent / sicherung.UPLOAD
    r = c.post("/einstellungen/backup-wiederherstellen", data={"quelle": str(upload), "passwort": PW, "bestaetigt": "on"})
    assert anzahl(eng, "SELECT count(*) FROM artikel") == 1 and not upload.exists()
    assert c.post("/einstellungen/backup-hochladen", files={"datei": ("leer.zip", b"", "application/zip")}).headers["location"] == "/einstellungen?tab=backup"


def test_wiederherstellen_aeltere_sicherung_ergaenzt_tabellen(env, tmp_path):
    """Sicherung aus einer älteren Version (fehlende Tabelle) -> nach dem Wiederherstellen wieder vollständig."""
    from app import db
    from app.services import sicherung
    cfg, _ = env
    client(cfg)
    eng = db.engine()
    mit_artikel(eng)
    sicherung.sichern(cfg, eng)
    roh = tmp_path / "alt.db"
    roh.write_bytes(zipfile.ZipFile(zips(Path(cfg.backup.ordner))[0]).read("lager.db"))
    k = sqlite3.connect(roh)
    k.execute("DROP TABLE sync_log")
    k.commit()
    k.close()
    alt = _zip(tmp_path, "alt.zip", {"lager.db": roh.read_bytes()})
    sicherung.wiederherstellen(cfg, eng, alt, "admin")
    assert anzahl(eng, "SELECT count(*) FROM sync_log") == 0


def test_status_json_kaputt_stoert_nicht(env):
    from app.services import sicherung
    from app.services.betrieb import set_setting
    cfg, eng = env
    with schreib(eng) as con:
        set_setting(con, sicherung.STATUS, "{kaputt")
    with eng.connect() as con:
        assert sicherung.status_lesen(con) == {}
    with schreib(eng) as con:
        set_setting(con, sicherung.STATUS, json.dumps([1, 2]))
    with eng.connect() as con:
        assert sicherung.status_lesen(con) == {}
