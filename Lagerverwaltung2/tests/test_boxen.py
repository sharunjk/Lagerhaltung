"""2.4.0: Sichtlagerboxen als Unterplätze (C1-R2-3-B1 …) und Weinrot-Markierung für Plätze mit Nachbestellbedarf."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select, update

from test_pruefung import L, anzahl, client, schreib


def codes(eng):
    with eng.connect() as con:
        from app.db import lagerplaetze
        return sorted(r[0] for r in con.execute(select(lagerplaetze.c.code)))


def kacheln(html: str) -> list[str]:
    """Codes der Kacheln in der Übersicht (ohne die Legende)."""
    return re.findall(r'<span class="bintag[^"]*">([^<]+)</span><span class="text-sm text-muted', html)


def test_boxen_anlegen_und_nummerieren(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Schraube M8"}, "C1-R2-3", 0)
    r = c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "3"})
    assert r.headers["location"].endswith("#boxen")
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "2"})
    assert [x for x in codes(eng) if x.startswith("C1-R2-3-")] == ["C1-R2-3-B1", "C1-R2-3-B2", "C1-R2-3-B3", "C1-R2-3-B4", "C1-R2-3-B5"]
    # ungültig: 0, 51, Text, Box in Box, unbekannter Platz
    for daten in ({"code": "C1-R2-3", "anzahl": "0"}, {"code": "C1-R2-3", "anzahl": "51"}, {"code": "C1-R2-3", "anzahl": "x"},
                  {"code": "C1-R2-3-B1", "anzahl": "2"}, {"code": "C9-GIBTS-NICHT", "anzahl": "2"}):
        c.post("/lagerplaetze/boxen", data=daten)
    assert len(codes(eng)) == 6
    assert client(cfg, "lesen").post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "1"}).status_code == 403
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Sichtlagerboxen angelegt'") == 2
    # Box-Bereich wie der Platz
    assert anzahl(eng, "SELECT count(*) FROM lagerplaetze WHERE code LIKE 'C1-R2-3-B%' AND bereich='C1'") == 5


def test_box_ist_ein_normaler_lagerplatz(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Schraube M8"}, "C1-R2-3", 0)
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "2"})
    c.post("/lagerplaetze/speichern", data={"alt": "C1-R2-3-B2", "code": "C1-R2-3-B2", "beschreibung": "Schrauben M8",
                                            "weiter": "/lagerplaetze/ansicht?code=C1-R2-3#boxen"})
    with schreib(eng) as con:
        L(con).eingang("1", "C1-R2-3-B2", 40)
    # Scannen des Box-Etiketts öffnet die Box
    assert c.get("/scan?code=c1-r2-3-b2").headers["location"] == "/lagerplaetze/ansicht?code=C1-R2-3-B2"
    assert c.get("/scan?code=C1-R2-3-B2&m=1").headers["location"] == "/m/platz?code=C1-R2-3-B2"
    box = c.get("/lagerplaetze/ansicht?code=C1-R2-3-B2").text
    assert "Inhalt der Box" in box and 'href="/lagerplaetze/ansicht?code=C1-R2-3#boxen"' in box and "Sichtlagerboxen" not in box
    platz = c.get("/lagerplaetze/ansicht?code=C1-R2-3").text
    assert 'id="boxen"' in platz and 'value="Schrauben M8"' in platz and "C1-R2-3-B1" in platz and "Alle 2 Box-Etiketten drucken" in platz
    m = c.get("/m/platz?code=C1-R2-3").text
    assert "Sichtlagerboxen" in m and "Schrauben M8" in m and "1 (40)" in m
    assert "gehört zu" in c.get("/m/platz?code=C1-R2-3-B2").text
    # Übersicht: Box nicht als eigene Kachel, Artikel des Platzes inkl. Boxen, Suche nach Box-Inhalt findet den Platz
    t = c.get("/lagerplaetze").text
    assert kacheln(t) == ["C1-R2-3"] and "1 Art. · 2 Boxen" in t and "2 Sichtlagerboxen" in t
    assert kacheln(c.get("/lagerplaetze?q=schrauben").text) == ["C1-R2-3"]
    # kein "abweichende Schreibweise"
    assert "Abweichende Schreibweisen" not in c.get("/lagerplaetze?leer=1").text


def test_umbenennen_nimmt_boxen_mit(env):
    from app import db
    from app.db import bewegungen
    cfg, _ = env
    c = client(cfg, "lager")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Schraube"}, "C1-R2-3", 0)
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "2"})
    with schreib(eng) as con:
        L(con).eingang("1", "C1-R2-3-B1", 5)
    c.post("/lagerplaetze/speichern", data={"alt": "C1-R2-3", "code": "C1-R2-4"})
    assert [x for x in codes(eng) if x.startswith("C1-R2")] == ["C1-R2-4", "C1-R2-4-B1", "C1-R2-4-B2"]
    with eng.connect() as con:
        assert {r[0] for r in con.execute(select(bewegungen.c.lagerplatz).where(bewegungen.c.typ == "eingang"))} == {"C1-R2-4-B1"}
    # Konflikt: Ziel-Box existiert schon -> nichts geändert
    c.post("/lagerplaetze/speichern", data={"code": "C1-R2-5-B1"})
    c.post("/lagerplaetze/speichern", data={"alt": "C1-R2-4", "code": "C1-R2-5"})
    assert "C1-R2-4-B1" in codes(eng) and "C1-R2-5" not in codes(eng)


def test_loeschen_mit_boxen(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    c.post("/lagerplaetze/speichern", data={"code": "C1-R2-3"})
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "1"})
    assert "Zuerst die Boxen leeren" in c.get("/lagerplaetze/ansicht?code=C1-R2-3").text
    c.post("/lagerplaetze/loeschen", data={"code": "C1-R2-3", "bestaetigung": "C1-R2-3"})
    assert "C1-R2-3" in codes(eng)
    r = c.post("/lagerplaetze/loeschen", data={"code": "C1-R2-3-B1", "bestaetigung": "C1-R2-3-B1"})
    assert r.headers["location"] == "/lagerplaetze/ansicht?code=C1-R2-3#boxen" and codes(eng) == ["C1-R2-3"]
    c.post("/lagerplaetze/loeschen", data={"code": "C1-R2-3", "bestaetigung": "C1-R2-3"})
    assert codes(eng) == []


def test_box_etiketten_mit_inhalt(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    c.post("/lagerplaetze/speichern", data={"code": "C1-R2-3"})
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "2"})
    c.post("/lagerplaetze/speichern", data={"alt": "C1-R2-3-B1", "code": "C1-R2-3-B1", "beschreibung": "Dichtungen DN50"})
    vorher = set(Path(cfg.drucker.datei_ordner).glob("*")) if Path(cfg.drucker.datei_ordner).exists() else set()
    c.post("/lagerplaetze/etikett", data={"code": ["C1-R2-3-B1", "C1-R2-3-B2"]})
    neu = set(Path(cfg.drucker.datei_ordner).glob("*")) - vorher
    roh = b"".join(f.read_bytes() for f in neu)
    assert b'"C1-R2-3-B1"' in roh and b'"C1-R2-3-B2"' in roh and b"Dichtungen DN50" in roh and b"Sichtlagerbox" in roh
    t = c.get("/etiketten/druckansicht?platz=C1-R2-3-B1&platz=C1-R2-3-B2").text
    assert "Dichtungen DN50" in t and "Sichtlagerbox" in t
    assert db.engine() is not None


def test_weinrot_bei_nachbestellbedarf(env):
    from app import db
    from app.db import artikel
    cfg, _ = env
    c = client(cfg, "lesen")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil", "meldebestand": 5}, "C1-R1-1", 3)
        L(con).artikel_anlegen({"nummer": "2", "bezeichnung": "Filter", "mindestbestand": 2}, "C1-R1-2", 10)
        L(con).artikel_anlegen({"nummer": "3", "bezeichnung": "Dichtung", "meldebestand": 4}, "C2-R1-1", 0)
        L(con).eingang("3", "C2-R1-1", 1)
    t = c.get("/lagerplaetze").text
    rot = re.findall(r'<span class="bintag bintag-nachbestellen">([^<]+)</span><span class="text-sm', t)
    assert rot == ["C1-R1-1", "C2-R1-1"] and "2</b> Plätze mit Nachbestellbedarf" in t
    assert 'title="Nachbestellen: 1"' in t
    d = c.get("/lagerplaetze/ansicht?code=C1-R1-1").text
    assert "Nachbestellung nötig" in d and "bintag bintag-nachbestellen text-3xl" in d
    assert "Nachbestellung nötig" not in c.get("/lagerplaetze/ansicht?code=C1-R1-2").text
    assert "Nachbestellung nötig" in c.get("/m/platz?code=C1-R1-1").text
    # aufgefüllt -> nicht mehr rot
    with schreib(eng) as con:
        L(con).eingang("1", "C1-R1-1", 10)
        L(con).eingang("3", "C2-R1-1", 10)
    assert "bintag-nachbestellen" not in c.get("/lagerplaetze").text
    # Platz, an dem der Artikel gerade 0 Stück hat (dort wird nachgefüllt), bleibt markiert
    with schreib(eng) as con:
        L(con).ausgang("2", "C1-R1-2", 10)
    assert re.findall(r'<span class="bintag bintag-nachbestellen">([^<]+)</span><span class="text-sm', c.get("/lagerplaetze?leer=1").text) == ["C1-R1-2"]
    # archivierte Artikel zählen nicht
    with schreib(eng) as con:
        con.execute(update(artikel).where(artikel.c.nummer == "2").values(aktiv=False))
    assert "bintag-nachbestellen" not in c.get("/lagerplaetze?leer=1").text


def test_weinrot_wenn_eine_box_betroffen_ist(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lager")
    eng = db.engine()
    c.post("/lagerplaetze/speichern", data={"code": "C1-R2-3"})
    c.post("/lagerplaetze/boxen", data={"code": "C1-R2-3", "anzahl": "3"})
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "7", "bezeichnung": "Schraube M8", "meldebestand": 50}, "C1-R2-3-B2", 20)
    t = c.get("/lagerplaetze").text
    assert re.findall(r'<span class="bintag bintag-nachbestellen">([^<]+)</span><span class="text-sm', t) == ["C1-R2-3"]
    d = c.get("/lagerplaetze/ansicht?code=C1-R2-3").text
    assert 'class="bintag bintag-nachbestellen">C1-R2-3-B2</a>' in d and 'class="bintag bintag-leer">C1-R2-3-B1</a>' in d
