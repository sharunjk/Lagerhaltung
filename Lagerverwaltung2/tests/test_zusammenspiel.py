"""Zusammenspiel Lagerverwaltung ↔ Instandhaltung und Arbeiten mit mehreren Benutzern (Gesamtprüfung 2.8.0).
Alle Daten erfunden."""
from __future__ import annotations

import threading

from sqlalchemy import select

from test_cmms_phase0 import cmms_an, ih_benutzer
from test_pruefung import L, anzahl, client, schreib
from test_wartung_260 import _anlagen, _plan_uebernehmen


def _als(cfg, name):
    c = client(cfg)
    assert c.post("/login", data={"username": name, "passwort": "Lager-Test-2026"}).status_code == 303
    return c


def _grund(env):
    """Anlagen, Plan, Ersatzteil 4711 (5 Stk.) an beiden Pumpen, Techniker ohne Lagerrolle, freigegebener S-Auftrag."""
    from app.db import ih_auftraege
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    with schreib(eng) as con:
        L(con).artikel_anlegen({"nummer": "4711", "bezeichnung": "Gleitringdichtung", "preis": 80.0}, "C1-R1-1", 5)
    ih_benutzer(eng, "tech", "techniker")              # Lager: kein Zugriff
    ih_benutzer(eng, "ing", "ingenieur", rolle="lager")  # beide Bereiche
    admin = client(cfg, "admin")
    _plan_uebernehmen(admin)
    admin.post("/ih/anlagen/2/ersatzteile", data={"artikel_nr": "4711", "menge": "1"})
    admin.post("/ih/anlagen/3/ersatzteile", data={"artikel_nr": "4711", "menge": "1"})
    admin.post("/ih/wartung/auftraege-anlegen")
    with eng.connect() as con:
        s = con.execute(select(ih_auftraege.c.id).where(ih_auftraege.c.massnahme == "S")).scalar()
    admin.post(f"/ih/auftraege/{s}/status", data={"aktion": "freigeben"})
    return cfg, eng, admin, s


def test_storno_im_lager_nimmt_entnahme_aus_dem_auftrag(env):
    cfg, eng, admin, s = _grund(env)
    tech = _als(cfg, "tech")
    tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "2"})
    assert "Material bisher 160,00" in tech.get(f"/ih/auftraege/{s}").text
    bid = anzahl(eng, f"SELECT id FROM bewegungen WHERE auftrag_id={s}")
    # Lager storniert die Entnahme (z. B. falsch gebucht): Bestand zurück, Auftrag zählt sie nicht mehr
    lager = _als(cfg, "ing")
    lager.post(f"/bewegungen/{bid}/storno")
    assert anzahl(eng, "SELECT sum(menge) FROM bestand") == 5
    seite = tech.get(f"/ih/auftraege/{s}").text
    assert "Material bisher" not in seite and anzahl(eng, f"SELECT storniert_durch IS NOT NULL FROM bewegungen WHERE id={bid}") == 1


def test_artikel_aenderungen_im_lager_wirken_in_der_instandhaltung(env):
    cfg, eng, admin, s = _grund(env)
    # Artikelnummer umbenennen: Zuordnung hängt an der ID und bleibt
    admin.post("/artikel/4711/bearbeiten", data={"nummer": "4711-A", "bezeichnung": "Gleitringdichtung neu", "einheit": "Stk"})
    assert "4711-A" in admin.get("/ih/anlagen/2").text and "4711-A" in admin.get(f"/ih/auftraege/{s}").text
    # Bestand 0 -> im Auftrag „nicht vorrätig“, Entnahme verweigert, kein Minusbestand
    with schreib(eng) as con:
        L(con).ausgang("4711-A", "C1-R1-1", 5)
    tech = _als(cfg, "tech")
    assert "nicht vorrätig" in tech.get(f"/ih/auftraege/{s}").text
    r = tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711-A", "platz": "C1-R1-1", "menge": "1"}, follow_redirects=True)
    assert "liegen nur 0" in r.text and anzahl(eng, "SELECT min(menge) FROM bestand") == 0
    # archivieren: an der Anlage gekennzeichnet, Entnahme verweigert
    admin.post("/artikel/4711-A/archivieren")
    assert "(archiviert)" in admin.get("/ih/anlagen/2").text
    r = tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711-A", "platz": "C1-R1-1", "menge": "1"}, follow_redirects=True)
    assert "archiviert" in r.text
    # löschen: Zuordnung verschwindet, Seiten laufen weiter
    admin.post("/artikel/4711-A/archivieren", data={"zurueck": "1"})
    admin.post("/artikel/4711-A/loeschen", data={"bestaetigung": "4711-A"})
    assert anzahl(eng, "SELECT count(*) FROM artikel") == 0 and anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 0
    for pfad in ("/ih/anlagen/2", f"/ih/auftraege/{s}", "/ih/ersatzteile/vorschlaege"):
        assert admin.get(pfad).status_code == 200, pfad


def test_anlage_archiviert_wirkt_auf_plan_stueckliste_und_schichtbuch(env):
    cfg, eng, admin, s = _grund(env)
    admin.post("/ih/schichtbuch/neu", data={"titel": "Pumpe B vibriert", "asset": "P -10401 B"})
    admin.post("/ih/anlagen/3/archivieren")
    # Artikel zeigt die Tag-Nr. weiter (Historie), Meldung bleibt lesbar, neue Aufträge ohne das Bauteil
    assert "P -10401 B" in admin.get("/artikel/4711").text
    mid = anzahl(eng, "SELECT id FROM sb_meldungen")
    assert "Pumpe B vibriert" in admin.get(f"/ih/schichtbuch/meldung/{mid}").text
    from app.services import wartung as w
    with eng.connect() as con:
        k = next(x for x in w.lage(con) if x["schluessel"] == "S-Pumpe")
        assert [t["code"] for t in w.bauteile_kampagne(con, k)] == ["P -10401 A"]
    # Artikel speichern lässt die Zuordnung zur archivierten Anlage stehen
    admin.post("/artikel/4711/bearbeiten", data={"nummer": "4711", "bezeichnung": "Gleitringdichtung", "einheit": "Stk", "tags_bearbeitet": "1",
                                                 "tag": ["P -10401 A", "P -10401 B"]})
    assert anzahl(eng, "SELECT count(*) FROM ih_stueckliste") == 2


def test_rollen_und_bereiche(env):
    cfg, eng, admin, s = _grund(env)
    tech, ing = _als(cfg, "tech"), _als(cfg, "ing")
    # Techniker ohne Lagerrolle: Lager gesperrt, Entnahme über den Auftrag erlaubt, keine Links ins Lager
    assert tech.get("/artikel").status_code == 403 and tech.get("/buchen").status_code == 403
    seite = tech.get("/ih/anlagen/2").text
    assert "4711" in seite and 'href="/artikel/4711"' not in seite
    assert tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "1"}).status_code == 303
    assert anzahl(eng, f"SELECT benutzer FROM bewegungen WHERE auftrag_id={s}") == "tech"
    # Ingenieur mit beiden Bereichen: Links in beide Richtungen
    assert 'href="/artikel/4711"' in ing.get("/ih/anlagen/2").text
    assert 'href="/ih/anlagen/2"' in ing.get("/artikel/4711").text
    # Lager-Benutzer ohne CMMS-Rolle: Tag-Nr. als Text, kein Link in die Instandhaltung, /ih gesperrt
    lager = client(cfg, "lager")
    detail = lager.get("/artikel/4711").text
    assert "P -10401 A" in detail and 'href="/ih/anlagen/2"' not in detail and lager.get("/ih").status_code == 403
    # Rolle wird während der Sitzung entzogen -> nächste Aktion gesperrt, ohne neue Anmeldung
    uid = anzahl(eng, "SELECT id FROM users WHERE username='tech'")
    admin.post("/benutzer/speichern", data={"id": str(uid), "username": "tech", "rolle": "keine", "rolle_ih": "lesen", "aktiv": "on"})
    assert tech.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "1"}).status_code == 403
    assert tech.get("/ih/schichtbuch").status_code == 200 and tech.post("/ih/schichtbuch/neu", data={"titel": "x"}).status_code == 403
    # Benutzer deaktiviert -> abgemeldet
    admin.post("/benutzer/speichern", data={"id": str(uid), "username": "tech", "rolle": "keine", "rolle_ih": "lesen"})
    assert tech.get("/ih/schichtbuch").status_code in (302, 303)


def test_benutzer_speichern_bei_ausgeschaltetem_cmms_behaelt_rolle(env):
    cfg, eng = env
    ih_benutzer(eng, "tech", "techniker")
    uid = anzahl(eng, "SELECT id FROM users WHERE username='tech'")
    cfg.cmms.aktiv = False
    admin = client(cfg, "admin")
    admin.post("/benutzer/speichern", data={"id": str(uid), "username": "tech", "rolle": "keine", "passwort": "Neues-Passwort-1", "aktiv": "on"})
    assert anzahl(eng, f"SELECT rolle FROM benutzer_rollen WHERE user_id={uid}") == "techniker"
    cfg.cmms.aktiv = True
    admin.post("/benutzer/speichern", data={"id": str(uid), "username": "tech", "rolle": "keine", "rolle_ih": "", "rolle_ih_feld": "1",
                                            "aktiv": "on"})
    assert anzahl(eng, f"SELECT count(*) FROM benutzer_rollen WHERE user_id={uid}") == 0
    assert 'name="rolle_ih_feld"' in admin.get("/einstellungen?tab=benutzer").text


def test_parallel_entnahmen_lager_und_auftrag(env):
    """Lager-Entnahmen und Auftrags-Entnahmen gleichzeitig auf denselben Platz: nie mehr als vorhanden, nie Minusbestand."""
    cfg, eng, admin, s = _grund(env)
    ergebnisse = []

    def lager_entnahme(c):
        r = c.post("/buchen", data={"artikel": "4711", "typ": "ausgang", "menge": "1", "lagerort": "C1-R1-1"})
        ergebnisse.append(r.status_code)

    def auftrag_entnahme(c):
        r = c.post(f"/ih/auftraege/{s}/entnahme", data={"artikel_nr": "4711", "platz": "C1-R1-1", "menge": "1"})
        ergebnisse.append(r.status_code)
    threads = []  # je Thread ein eigener angemeldeter Benutzer-Client (wie getrennte Browser)
    for i in range(12):
        if i % 3 == 0:
            threads.append(threading.Thread(target=auftrag_entnahme, args=(_als(cfg, "tech"),)))
        else:
            threads.append(threading.Thread(target=lager_entnahme, args=(_als(cfg, "ing") if i % 3 == 1 else client(cfg, "lager"),)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(x == 303 for x in ergebnisse), ergebnisse
    assert anzahl(eng, "SELECT menge FROM bestand") == 0
    assert anzahl(eng, "SELECT -sum(menge) FROM bewegungen WHERE typ='ausgang'") == 5
    assert anzahl(eng, "SELECT count(*) FROM bewegungen WHERE typ='ausgang' AND bestand_nachher < 0") == 0


def test_parallel_schichtbeginn_und_meldungen(env):
    """Zwei Benutzer beginnen gleichzeitig dieselbe Schicht und melden parallel: eine Schicht, alle Meldungen, kein Fehler."""
    cfg, eng = env
    cmms_an(cfg)
    ih_benutzer(eng, "a", "operator")
    ih_benutzer(eng, "b", "schichtfuehrer")
    ca, cb = _als(cfg, "a"), _als(cfg, "b")
    codes = []

    def arbeit(c, name):
        codes.append(c.post("/ih/schichtbuch/beginnen", data={"schichtfuehrer": name}).status_code)
        for i in range(5):
            codes.append(c.post("/ih/schichtbuch/neu", data={"titel": f"{name} {i}"}).status_code)
    ts = [threading.Thread(target=arbeit, args=(ca, "a")), threading.Thread(target=arbeit, args=(cb, "b"))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(x == 303 for x in codes), codes
    assert anzahl(eng, "SELECT count(*) FROM sb_schichten") == 1 and anzahl(eng, "SELECT count(*) FROM sb_meldungen") == 10
    assert anzahl(eng, "SELECT count(DISTINCT erstellt_von) FROM sb_meldungen") == 2
    # Übergabe: zwei übernehmen gleichzeitig -> genau eine Übernahme
    mid = anzahl(eng, "SELECT min(id) FROM sb_meldungen")
    sid = anzahl(eng, "SELECT id FROM sb_schichten")
    ca.post("/ih/schichtbuch/beenden", data={"schicht_id": sid, "ueb": str(mid)})
    ts = [threading.Thread(target=lambda c=c: c.post(f"/ih/schichtbuch/meldung/{mid}/uebernehmen")) for c in (ca, cb)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert anzahl(eng, f"SELECT count(*) FROM sb_verlauf WHERE meldung_id={mid} AND art='uebernahme'") == 1


def test_parallel_auftraege_anlegen_und_status(env):
    """Zwei Planer legen gleichzeitig die fälligen Aufträge an und ändern gleichzeitig den Status: keine Doppelten, klarer Endzustand."""
    cfg, eng = env
    cmms_an(cfg)
    _anlagen(eng)
    ih_benutzer(eng, "p1", "ingenieur")
    ih_benutzer(eng, "p2", "manager")
    _plan_uebernehmen(client(cfg, "admin"))
    p1, p2 = _als(cfg, "p1"), _als(cfg, "p2")
    codes = []
    ts = [threading.Thread(target=lambda c=c: codes.append(c.post("/ih/wartung/auftraege-anlegen").status_code)) for c in (p1, p2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert codes == [303, 303] and anzahl(eng, "SELECT count(*) FROM ih_auftraege") == 4
    aid = anzahl(eng, "SELECT min(id) FROM ih_auftraege")
    ts = [threading.Thread(target=lambda: codes.append(p1.post(f"/ih/auftraege/{aid}/status", data={"aktion": "freigeben"}).status_code)),
          threading.Thread(target=lambda: codes.append(p2.post(f"/ih/auftraege/{aid}/status", data={"aktion": "stornieren", "text": "doppelt"}).status_code))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(x == 303 for x in codes)
    assert anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={aid}") in ("freigegeben", "storniert")
    # Verlauf passt zum Endzustand
    assert anzahl(eng, f"SELECT nach FROM ih_statuslog WHERE auftrag_id={aid} ORDER BY id DESC LIMIT 1") == \
        anzahl(eng, f"SELECT status FROM ih_auftraege WHERE id={aid}")
