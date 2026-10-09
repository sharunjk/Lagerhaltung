"""Lagerplätze: Unterteilung nach Regal, Löschen mit Bestätigung, Zurück-Knopf."""
from __future__ import annotations

import re

from sqlalchemy import insert, select

from test_pruefung import L, anzahl, client, schreib


def plaetze(eng, *codes):
    from app.db import lagerplaetze
    with schreib(eng) as con:
        for c in codes:
            con.execute(insert(lagerplaetze).values(code=c, bereich=c.split("-")[0] if "-" in c else None, aktiv=True))


def test_natuerliche_sortierung():
    from app.routes.lager import natuerlich
    codes = ["C1-R10-1", "C1-R2-1", "C1-R1-10", "C1-R1-2", "C10-R1-1", "C2-R1-1", "c1-r1-3"]
    assert sorted(codes, key=natuerlich) == ["C1-R1-2", "c1-r1-3", "C1-R1-10", "C1-R2-1", "C1-R10-1", "C2-R1-1", "C10-R1-1"]


def test_uebersicht_nach_bereich_und_regal(env):
    from app import db
    cfg, _ = env
    c = client(cfg, "lesen")
    plaetze(db.engine(), "C1-F2", "C1-F1", "C1-R10-1", "C1-R2-2", "C1-R2-1", "C1-R1-1", "C2-R1-1", "Werkstatt")
    t = c.get("/lagerplaetze?leer=1").text
    reihen = re.findall(r'<span class="font-semibold">([^<]+)</span>', t)
    assert reihen == ["Einzelplätze", "R1", "R2", "R10", "R1"]  # C1: Einzelplätze, R1, R2, R10 – C2: R1; "Sonstige" ohne Unterteilung
    reihenfolge = re.findall(r'<span class="bintag[^"]*">([^<]+)</span>', t)
    assert reihenfolge == ["C1-F1", "C1-F2", "C1-R1-1", "C1-R2-1", "C1-R2-2", "C1-R10-1", "C2-R1-1", "Werkstatt"]
    assert "Sonstige" in t


def test_platz_loeschen_mit_bestaetigung(env):
    from app import db
    from app.db import bewegungen, lagerplaetze
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1-R1-1", 5)
        L(con).umbuchung("1", "C1-R1-1", "C1-RR1-1", 5)  # Tippfehler-Platz, danach wieder geleert
        L(con).umbuchung("1", "C1-RR1-1", "C1-R1-1", 5)
    seite = c.get("/lagerplaetze/ansicht?code=C1-RR1-1").text
    assert "Platz löschen" in seite and 'name="bestaetigung"' in seite
    # falsche Bestätigung -> nichts passiert
    c.post("/lagerplaetze/loeschen", data={"code": "C1-RR1-1", "bestaetigung": "c1-rr1-1"})
    assert anzahl(eng, "SELECT count(*) FROM lagerplaetze WHERE code='C1-RR1-1'") == 1
    # Platz mit Bestand -> abgelehnt, auch mit richtiger Bestätigung; kein Löschformular auf der Seite
    r = c.post("/lagerplaetze/loeschen", data={"code": "C1-R1-1", "bestaetigung": "C1-R1-1"})
    assert anzahl(eng, "SELECT count(*) FROM lagerplaetze WHERE code='C1-R1-1'") == 1
    assert 'name="bestaetigung"' not in c.get("/lagerplaetze/ansicht?code=C1-R1-1").text
    # richtig
    r = c.post("/lagerplaetze/loeschen", data={"code": "C1-RR1-1", "bestaetigung": "C1-RR1-1"})
    assert r.headers["location"] == "/lagerplaetze"
    with eng.connect() as con:
        assert con.execute(select(lagerplaetze).where(lagerplaetze.c.code == "C1-RR1-1")).first() is None
        hist = con.execute(select(bewegungen.c.lagerplatz, bewegungen.c.lagerplatz_id).where(bewegungen.c.lagerplatz == "C1-RR1-1")).all()
    assert len(hist) == 2 and all(pid is None for _, pid in hist)  # Historie bleibt mit dem Code als Text
    assert "C1-RR1-1" in c.get("/bewegungen?platz=C1-RR1-1").text
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Lagerplatz gelöscht' AND objekt='C1-RR1-1'") == 1
    assert anzahl(eng, "SELECT sum(menge) FROM bestand") == 5
    # später wieder anlegbar (z. B. durch eine Buchung)
    with schreib(eng) as con:
        L(con).umbuchung("1", "C1-R1-1", "C1-RR1-1", 1)
    assert anzahl(eng, "SELECT count(*) FROM lagerplaetze WHERE code='C1-RR1-1'") == 1


def test_platz_loeschen_nur_admin(env):
    from app import db
    cfg, _ = env
    client(cfg)
    plaetze(db.engine(), "C9-X")
    for rolle in ("lager", "lesen"):
        c = client(cfg, rolle)
        assert c.post("/lagerplaetze/loeschen", data={"code": "C9-X", "bestaetigung": "C9-X"}).status_code == 403
        assert "Platz löschen" not in c.get("/lagerplaetze/ansicht?code=C9-X").text
    assert anzahl(db.engine(), "SELECT count(*) FROM lagerplaetze WHERE code='C9-X'") == 1


def test_platz_loeschen_und_inventur(env):
    from app import db
    from app.db import artikel, inventur_pos, inventuren, lagerplaetze
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Ventil"}, "C1-R1-1", 0)
    plaetze(eng, "C9-OFFEN", "C9-GEZAEHLT", "C9-NULL")
    with schreib(eng) as con:
        aid = con.execute(select(artikel.c.id)).scalar()
        pid = {r.code: r.id for r in con.execute(select(lagerplaetze.c.code, lagerplaetze.c.id))}
        offen = con.execute(insert(inventuren).values(name="Herbst", status="offen")).inserted_primary_key[0]
        zu = con.execute(insert(inventuren).values(name="Frühjahr", status="abgeschlossen")).inserted_primary_key[0]
        con.execute(insert(inventur_pos).values(inventur_id=offen, artikel_id=aid, lagerplatz_id=pid["C9-OFFEN"], soll=0))
        con.execute(insert(inventur_pos).values(inventur_id=zu, artikel_id=aid, lagerplatz_id=pid["C9-GEZAEHLT"], soll=0, ist=3))
        con.execute(insert(inventur_pos).values(inventur_id=zu, artikel_id=aid, lagerplatz_id=pid["C9-NULL"], soll=0, ist=0))
    for code in ("C9-OFFEN", "C9-GEZAEHLT", "C9-NULL"):
        c.post("/lagerplaetze/loeschen", data={"code": code, "bestaetigung": code})
    rest = {r[0] for r in eng.connect().execute(select(lagerplaetze.c.code))}
    assert "C9-OFFEN" in rest and "C9-GEZAEHLT" in rest and "C9-NULL" not in rest
    assert anzahl(eng, "SELECT count(*) FROM inventur_pos") == 2


def test_zurueck_knopf(env):
    cfg, _ = env
    c = client(cfg, "lager")
    assert "lvZurueck('/')" not in c.get("/").text
    assert "lvZurueck('/')" in c.get("/lagerplaetze").text
    assert "lvZurueck('/m')" not in c.get("/m").text
    assert "lvZurueck('/m')" in c.get("/m/suche").text
