"""2.4.0: Fotos beim Anlegen (PC und Handy), Anlegen direkt am Lagerplatz, Lieferant als Freitext, Etiketten-Schriftgröße."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import insert

from test_pruefung import L, anzahl, client, schreib

JPG = b"\xff\xd8\xff\xe0bild"


def anhaenge_von(eng, nr):
    return anzahl(eng, "SELECT count(*) FROM anhaenge h JOIN artikel a ON a.id=h.artikel_id WHERE a.nummer=:n", n=nr)


def lieferant_von(eng, nr):
    return anzahl(eng, "SELECT l.name FROM artikel a LEFT JOIN lieferanten l ON l.id=a.lieferant_id WHERE a.nummer=:n", n=nr)


# ------------------------------------------------------------------ Fotos beim Anlegen
def test_pc_anlegen_mit_fotos(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    assert 'enctype="multipart/form-data"' in c.get("/artikel/neu").text
    r = c.post("/artikel/neu", data={"nummer": "500", "bezeichnung": "Pumpe", "platz": "C1-R1-1", "anfangsbestand": "2"},
               files=[("dateien", ("vorne.jpg", JPG, "image/jpeg")), ("dateien", ("typenschild.jpg", JPG, "image/jpeg")),
                      ("dateien", ("", b"", "application/octet-stream"))])  # leeres Auswahlfeld wird übergangen
    assert r.status_code == 303 and r.headers["location"] == "/artikel/500"
    eng = db.engine()
    assert anhaenge_von(eng, "500") == 2 and len(list(Path(cfg.daten.anhaenge).iterdir())) == 2
    assert anzahl(eng, "SELECT count(*) FROM anhaenge WHERE ist_bild=1") == 2
    assert "2 Foto(s)/Datei(en) gespeichert" in c.get("/artikel/500").text


def test_pc_anlegen_fehler_keine_verwaisten_fotos(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    with schreib(db.engine()) as con:
        L(con).artikel_anlegen({"nummer": "500", "bezeichnung": "Schon da"})
    r = c.post("/artikel/neu", data={"nummer": "500", "bezeichnung": "Doppelt"}, files=[("dateien", ("a.jpg", JPG, "image/jpeg"))])
    assert r.status_code == 200 and "bereits vergeben" in r.text and "erneut auswählen" in r.text
    assert anzahl(db.engine(), "SELECT count(*) FROM anhaenge") == 0
    assert not Path(cfg.daten.anhaenge).exists() or not list(Path(cfg.daten.anhaenge).iterdir())


def test_mobil_anlegen_mit_foto_und_galerie(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    seite = c.get("/m/neu?platz=C1-R1-1").text
    assert 'enctype="multipart/form-data"' in seite and "Foto aufnehmen" in seite and "Aus Galerie" in seite
    assert "Foto danach auf der Artikelseite" not in seite
    r = c.post("/m/neu", data={"nummer": "600", "bezeichnung": "Sensor", "platz": "C1-R1-1", "anfangsbestand": "1"},
               files=[("dateien", ("kamera.jpg", JPG, "image/jpeg")), ("dateien", ("galerie.png", b"\x89PNG", "image/png"))])
    assert r.status_code == 303 and r.headers["location"] == "/m/artikel/600"
    assert anhaenge_von(db.engine(), "600") == 2
    assert "2 Foto(s) gespeichert" in c.get("/m/artikel/600").text


def test_mobil_anlegen_fehler_behaelt_eingaben(env):
    cfg, _ = env
    c = client(cfg, "lager")
    r = c.post("/m/neu", data={"nummer": "601", "bezeichnung": "Ventil XY", "lieferant": "Neu GmbH", "platz": "C1-R1-1", "anfangsbestand": "abc"})
    assert r.status_code == 200 and "Ventil XY" in r.text and "Neu GmbH" in r.text and "keine gültige Zahl" in r.text
    from app import db
    assert anzahl(db.engine(), "SELECT count(*) FROM lieferanten") == 0  # zurückgerollt


def test_mobile_artikelseite_kamera_und_galerie(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    with schreib(db.engine()) as con:
        L(con).artikel_anlegen({"nummer": "700", "bezeichnung": "X"})
    seite = c.get("/m/artikel/700").text
    assert 'capture="environment"' in seite and 'name="dateien" accept="image/*" multiple' in seite
    r = c.post("/artikel/700/anhang?weiter=/m/artikel/700", files=[("dateien", ("a.jpg", JPG, "image/jpeg")), ("dateien", ("b.jpg", JPG, "image/jpeg"))])
    assert r.headers["location"] == "/m/artikel/700" and anhaenge_von(db.engine(), "700") == 2
    c.post("/artikel/700/anhang", files={"datei": ("c.jpg", JPG, "image/jpeg")})  # bisheriger Weg (ein Foto) geht weiter
    assert anhaenge_von(db.engine(), "700") == 3
    c.post("/artikel/700/anhang", files={"datei": ("leer.jpg", b"", "image/jpeg")})
    assert anhaenge_von(db.engine(), "700") == 3


# ------------------------------------------------------------------ Anlegen am Lagerplatz
def test_artikel_am_lagerplatz_und_in_box_anlegen(env):
    from app import db
    from app.db import lagerplaetze
    cfg, _ = env
    with schreib(db.engine()) as con:
        L(con).platz("C1-R2-3", anlegen=True)
        con.execute(insert(lagerplaetze).values(code="C1-R2-3-B1", bereich="C1", beschreibung="Schrauben", aktiv=True))
    c = client(cfg, "lager")
    for code in ("C1-R2-3", "C1-R2-3-B1"):
        seite = c.get(f"/lagerplaetze/ansicht?code={code}").text
        assert f'href="/artikel/neu?platz={code}"' in seite and "Artikel hier anlegen" in seite
        form = c.get(f"/artikel/neu?platz={code}").text
        assert re.search(rf'name="platz"[^>]*value="{code}"', form)
    c.post("/artikel/neu", data={"nummer": "800", "bezeichnung": "Schraube", "platz": "C1-R2-3-B1", "anfangsbestand": "50"})
    assert anzahl(db.engine(), "SELECT b.menge FROM bestand b JOIN lagerplaetze p ON p.id=b.lagerplatz_id WHERE p.code='C1-R2-3-B1'") == 50
    assert "Artikel hier anlegen" not in client(cfg, "lesen").get("/lagerplaetze/ansicht?code=C1-R2-3").text


# ------------------------------------------------------------------ Lieferant als Freitext
def test_lieferant_freitext_mit_vorschlaegen_und_neuanlage(env):
    from app import db
    from app.db import lieferanten
    cfg, _ = env
    eng = db.engine()
    with schreib(eng) as con:
        con.execute(insert(lieferanten).values(name="Messtechnik Süd KG"))
    c = client(cfg, "lager")
    form = c.get("/artikel/neu").text
    assert 'name="lieferant" list="lieferanten"' in form and '<option value="Messtechnik Süd KG">' in form and 'name="lieferant_id"' not in form
    # vorhandener Name, andere Schreibweise -> kein Duplikat
    c.post("/artikel/neu", data={"nummer": "1", "bezeichnung": "A", "lieferant": "  MESSTECHNIK  SÜD kg "})
    assert lieferant_von(eng, "1") == "Messtechnik Süd KG" and anzahl(eng, "SELECT count(*) FROM lieferanten") == 1
    # neuer Name -> automatisch unter Lieferanten
    c.post("/artikel/neu", data={"nummer": "2", "bezeichnung": "B", "lieferant": "Armaturen Nord GmbH"})
    assert lieferant_von(eng, "2") == "Armaturen Nord GmbH" and anzahl(eng, "SELECT count(*) FROM lieferanten") == 2
    assert "Armaturen Nord GmbH" in c.get("/lieferanten").text
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Lieferant angelegt'") == 1
    # bearbeiten: Name vorbelegt, ändern auf neuen, leeren entfernt den Lieferanten
    assert 'value="Armaturen Nord GmbH"' in c.get("/artikel/2/bearbeiten").text
    c.post("/artikel/2/bearbeiten", data={"nummer": "2", "bezeichnung": "B", "lieferant": "Normteile Direkt"})
    assert lieferant_von(eng, "2") == "Normteile Direkt" and anzahl(eng, "SELECT count(*) FROM lieferanten") == 3
    c.post("/artikel/2/bearbeiten", data={"nummer": "2", "bezeichnung": "B", "lieferant": ""})
    assert lieferant_von(eng, "2") is None
    # Handy: gleiche Logik
    c.post("/m/neu", data={"nummer": "3", "bezeichnung": "C", "lieferant": "normteile direkt"})
    assert lieferant_von(eng, "3") == "Normteile Direkt" and anzahl(eng, "SELECT count(*) FROM lieferanten") == 3


# ------------------------------------------------------------------ Etiketten-Schriftgröße
LANG = "Testetikett Kugelhahn DN15 PN40 Edelstahl, Flanschanschluss"


def _texte(roh: bytes):
    return [re.match(r'TEXT (\d+),(\d+),"(\d)",0,1,1,"(.*)"', z).groups() for z in roh.decode("cp1252").split("\r\n") if z.startswith("TEXT")]


@pytest.mark.parametrize("fmt,breite,hoehe", [("45x23", 360, 184), ("60x20", 480, 160)])
def test_schrift_automatisch_nichts_abgeschnitten(fmt, breite, hoehe):
    from app.services.labels import FONTS, etikett_tspl
    texte = _texte(etikett_tspl("10001", "10001", LANG, fmt))
    zeile2 = texte[1:]
    assert " ".join(t[3] for t in zeile2) == LANG  # vollständig, auf zwei Zeilen
    for x, y, f, t in texte:
        fb, fh = FONTS[f]
        assert int(x) + len(t) * fb <= breite and int(y) + fh <= hoehe, (fmt, t)
    # kurzer Text bleibt in der Standardschrift, einzeilig
    kurz = _texte(etikett_tspl("10001", "10001", "Kugelhahn", fmt))
    assert len(kurz) == 2 and kurz[1][2] == kurz[0][2]


def test_schrift_feste_groessen():
    from app.services.labels import LAYOUTS, etikett_tspl, text_layout
    L = LAYOUTS["45x23"]
    assert text_layout(L, "Kugelhahn", "gross")[0] == "3" and text_layout(L, "Kugelhahn", "klein")[0] == "1"
    assert text_layout(L, "Kugelhahn", "normal")[0] == "2" and text_layout(L, "Kugelhahn", "auto")[0] == "2"
    f, zeilen = text_layout(L, LANG, "gross")
    assert len(zeilen) == 1 and zeilen[0].endswith("…") and len(zeilen[0]) * 16 <= 360
    assert _texte(etikett_tspl("1", "1", "Kugelhahn", "45x23", schrift="gross"))[1][2] == "3"
    f, zeilen = text_layout(L, "x" * 200, "auto")  # extrem lang: zwei Zeilen, Rest gekürzt
    assert f == "1" and len(zeilen) == 2 and zeilen[1].endswith("…")
    assert text_layout(L, "", "auto") == ("2", [])


def test_schrift_einstellung_und_druck(env):
    from app import config as config_mod
    cfg, _ = env
    c = client(cfg, "admin")
    seite = c.get("/einstellungen?tab=drucker").text
    assert 'name="schrift"' in seite and "Automatisch" in seite
    c.post("/einstellungen/drucker", data={"modus": "datei", "standard_format": "45x23", "barcode": "128", "schrift": "gross", "aktion": "speichern"})
    assert cfg.drucker.schrift == "gross" or c.app.state.cfg.drucker.schrift == "gross"
    assert 'schrift = "gross"' in config_mod.CONFIG_PATH.read_text(encoding="utf-8")
    c.post("/einstellungen/drucker", data={"modus": "datei", "schrift": "riesig", "aktion": "speichern"})
    assert c.app.state.cfg.drucker.schrift == "auto"  # Unsinn -> automatisch
    from app import db
    with schreib(db.engine()) as con:
        L(con).artikel_anlegen({"nummer": "42", "bezeichnung": LANG})
    detail = c.get("/artikel/42").text
    assert 'name="schrift"' in detail and 'id="etikett-vorschau"' in detail
    c.post("/artikel/42/etikett", data={"anzahl": "1", "schrift": "klein"})
    druck = sorted(Path(cfg.drucker.datei_ordner).iterdir())[-1].read_bytes()
    assert {t[2] for t in _texte(druck)[1:]} == {"1"}
    v = c.get("/etikett/vorschau", params={"code": "42", "z1": "42", "z2": LANG, "schrift": "auto"}).text
    assert v.count("<text") == 3 and "Flanschanschluss" in v
