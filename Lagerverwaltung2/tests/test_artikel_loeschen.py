"""2.4.0: Artikel endgültig löschen (nur Admin, Nummer eintippen, nur ohne Bestand und offene Vorgänge)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import insert, select

from test_pruefung import L, anzahl, client, schreib


def artikel_da(eng, nr):
    return anzahl(eng, "SELECT count(*) FROM artikel WHERE nummer=:n", n=nr) == 1


def test_loeschen_mit_bestaetigung_historie_bleibt(env):
    from app import db
    from app.db import bewegungen
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "99", "bezeichnung": "Falsch angelegt"}, "C1-R1-1", 3)
        L(con).ausgang("99", "C1-R1-1", 3)
    c.post("/artikel/99/anhang", files={"datei": ("foto.jpg", b"\xff\xd8bild", "image/jpeg")})
    datei = next(Path(cfg.daten.anhaenge).iterdir())
    seite = c.get("/artikel/99").text
    assert "Artikel endgültig löschen" in seite and 'name="bestaetigung"' in seite
    # falsche Bestätigung -> nichts
    c.post("/artikel/99/loeschen", data={"bestaetigung": "9"})
    assert artikel_da(eng, "99") and datei.exists()
    r = c.post("/artikel/99/loeschen", data={"bestaetigung": "99"})
    assert r.headers["location"] == "/artikel" and not artikel_da(eng, "99")
    assert not datei.exists()  # Foto weg
    assert anzahl(eng, "SELECT count(*) FROM anhaenge") == 0 and anzahl(eng, "SELECT count(*) FROM bestand") == 0
    with eng.connect() as con:
        hist = con.execute(select(bewegungen.c.artikel_nr, bewegungen.c.artikel_id)).all()
    assert len(hist) == 2 and all(nr == "99" and aid is None for nr, aid in hist)
    assert "99" in c.get("/bewegungen").text  # Historie zeigt die Nummer weiter
    assert anzahl(eng, "SELECT count(*) FROM audit WHERE aktion='Artikel gelöscht' AND objekt='99'") == 1
    # Nummer ist danach wieder frei
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "99", "bezeichnung": "Richtig angelegt"}, "C1-R1-1", 1)
    assert artikel_da(eng, "99")


def test_loeschen_nur_ohne_bestand_und_offene_vorgaenge(env):
    from app import db
    from app.db import artikel, bestellungen, inventur_pos, inventuren, lagerplaetze, reservierungen
    cfg, _ = env
    c = client(cfg, "admin")
    eng = db.engine()
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "1", "bezeichnung": "Mit Bestand"}, "C1-R1-1", 2)
        for nr in ("2", "3", "4", "5"):
            L(con).artikel_anlegen({"nummer": nr, "bezeichnung": f"Artikel {nr}"}, "C1-R1-1", 0)
        aid = {nr: con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar() for nr in ("2", "3", "4", "5")}
        pid = con.execute(select(lagerplaetze.c.id).where(lagerplaetze.c.code == "C1-R1-1")).scalar()
        con.execute(insert(reservierungen).values(artikel_id=aid["2"], menge=1, fuer="Auftrag", status="offen"))
        con.execute(insert(bestellungen).values(artikel_id=aid["3"], menge=5, status="bestellt"))
        inv = con.execute(insert(inventuren).values(name="Herbst", status="offen")).inserted_primary_key[0]
        con.execute(insert(inventur_pos).values(inventur_id=inv, artikel_id=aid["5"], lagerplatz_id=pid, soll=0))
        L(con).eingang("4", "C1-R1-1", 1)
        L(con).ausleihe("4", "C1-R1-1", 1, empfaenger="Monteur")
    assert 'name="bestaetigung"' not in c.get("/artikel/1").text  # mit Bestand kein Löschfeld
    for nr, grund in (("1", "noch Bestand"), ("2", "Reservierungen"), ("3", "Bestellungen"), ("4", "ausgeliehen"), ("5", "Inventur")):
        r = c.post(f"/artikel/{nr}/loeschen", data={"bestaetigung": nr}, follow_redirects=True)
        assert artikel_da(eng, nr) and grund in r.text, nr
    # erledigte Bestellung blockiert nicht
    with schreib(eng) as con:
        con.execute(bestellungen.update().where(bestellungen.c.artikel_id == aid["3"]).values(status="geliefert"))
    c.post("/artikel/3/loeschen", data={"bestaetigung": "3"})
    assert not artikel_da(eng, "3") and anzahl(eng, "SELECT count(*) FROM bestellungen") == 0


def test_loeschen_nur_admin(env):
    from app import db
    cfg, _ = env
    client(cfg)
    with schreib(db.engine()) as con:
        L(con).artikel_anlegen({"nummer": "7", "bezeichnung": "X"}, "C1-R1-1", 0)
    for rolle in ("lager", "lesen"):
        c = client(cfg, rolle)
        assert c.post("/artikel/7/loeschen", data={"bestaetigung": "7"}).status_code == 403
        assert "endgültig löschen" not in c.get("/artikel/7").text
    assert artikel_da(db.engine(), "7")
    assert "gibt es nicht" in client(cfg, "admin").post("/artikel/0815/loeschen", data={"bestaetigung": "0815"}, follow_redirects=True).text
