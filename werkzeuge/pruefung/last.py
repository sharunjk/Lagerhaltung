"""Lasttest mit mehreren Benutzern gleichzeitig gegen einen laufenden Demo-Server (demo_start.sh).

Aufruf: python last.py <baseUrl> <lager.db> [sekunden] [real]   (Server mit [cmms] aktiv = true in config.toml)
Legt Benutzer, Anlagen, Zuordnungen und eine eigene Kampagne an, dann arbeiten 10 Benutzer parallel:
Lager-Entnahmen und -Eingänge, Auftrags-Entnahmen, Schichtbuch-Meldungen und -Ergänzungen, lesende Seiten.
Am Ende: keine Serverfehler, Bestand = Summe der Buchungen je Artikel und Platz, kein Minusbestand, Antwortzeiten.
Nur erfundene Demodaten.
"""
from __future__ import annotations

import random
import re
import sqlite3
import statistics
import sys
import threading
import time
from datetime import date

import httpx

BASE, DB = sys.argv[1], sys.argv[2]
DAUER = int(sys.argv[3]) if len(sys.argv) > 3 else 60
PAUSE = (2.0, 6.0) if len(sys.argv) > 4 and sys.argv[4] == "real" else (0.02, 0.15)  # „real“: Denkpause wie am Arbeitsplatz
PW = "Last-Test-2026!"
fehler: list[str] = []
zeiten: dict[str, list[float]] = {}
zaehler: dict[str, int] = {}
sperre = threading.Lock()


def neu_client() -> httpx.Client:
    return httpx.Client(base_url=BASE, follow_redirects=False, timeout=60)


def login(name: str, pw: str = PW) -> httpx.Client:
    c = neu_client()
    r = c.post("/login", data={"username": name, "passwort": pw})
    assert r.status_code == 303, (name, r.status_code)
    return c


def mess(art: str, c: httpx.Client, methode: str, pfad: str, **kw):
    t = time.perf_counter()
    r = getattr(c, methode)(pfad, **kw)
    d = time.perf_counter() - t
    with sperre:
        zeiten.setdefault(art, []).append(d)
        zaehler[art] = zaehler.get(art, 0) + 1
        if r.status_code >= 500 or r.status_code == 403:
            fehler.append(f"{art} {methode.upper()} {pfad} -> {r.status_code}")
    return r


def vorbereiten():
    admin = login("admin", "Demo-Passwort-1")
    benutzer = [("lager1", "lager", ""), ("lager2", "lager", ""), ("tech1", "keine", "techniker"), ("tech2", "keine", "techniker"),
                ("op1", "keine", "operator"), ("op2", "keine", "operator"), ("sf1", "keine", "schichtfuehrer"), ("ing1", "lager", "ingenieur")]
    for name, rolle, ih in benutzer:
        admin.post("/benutzer/speichern", data={"username": name, "anzeigename": name.upper(), "rolle": rolle, "passwort": PW, "aktiv": "on",
                                                "rolle_ih": ih, "rolle_ih_feld": "1"})
    for code in ("P -30101 A", "P -30101 B", "V -30102"):
        admin.post("/ih/anlagen/neu", data={"code": code, "art": "platz", "bezeichnung": f"Last {code}"})
    for nr in ("10001", "10003", "10005"):
        for code in ("P -30101 A", "P -30101 B"):
            pid = re.search(r'href="/ih/anlagen/(\d+)"', admin.get("/ih/anlagen", params={"q": code}).text)
            admin.post(f"/ih/anlagen/{pid.group(1)}/ersatzteile", data={"artikel_nr": nr, "menge": "1"})
    for nr, platz in (("10001", "C1-R1-1"), ("10003", "C1-R2-1"), ("10005", "B0-R1-2")):
        admin.post("/buchen", data={"artikel": nr, "typ": "eingang", "menge": "40", "lagerort": platz})
    admin.post("/ih/wartung/kampagne/neu", data={"massnahme": "W", "ziel": "bauteile", "tag": ["P -30101 A", "P -30101 B"],
                                                  "taetigkeit": "Lasttest-Wartung", "erster_termin": str(date.today()), "intervall_monate": "6"})
    kid = re.search(r"/ih/wartung/kampagne/(\d+)", admin.get("/ih/wartung").text).group(1)
    termin = re.search(r'name="termin" value="([0-9-]+)"', admin.get(f"/ih/wartung/kampagne/{kid}").text).group(1)
    r = admin.post(f"/ih/wartung/kampagne/{kid}/auftrag", data={"termin": termin})
    aid = int(re.search(r"/ih/auftraege/(\d+)", r.headers["location"]).group(1))
    admin.post(f"/ih/auftraege/{aid}/status", data={"aktion": "freigeben"})
    return aid


def arbeiter(name: str, rolle: str, aid: int, ende: float):
    c = login(name)
    rnd = random.Random(name)
    teile = [("10001", "C1-R1-1"), ("10003", "C1-R2-1"), ("10005", "B0-R1-2")]
    while time.time() < ende:
        nr, platz = rnd.choice(teile)
        if rolle == "lager":
            if rnd.random() < 0.6:
                mess("Lager-Entnahme", c, "post", "/buchen", data={"artikel": nr, "typ": "ausgang", "menge": "1", "lagerort": platz,
                                                                    "empfaenger": name})
            else:
                mess("Lager-Eingang", c, "post", "/buchen", data={"artikel": nr, "typ": "eingang", "menge": "1", "lagerort": platz})
            mess("Seite Artikel", c, "get", f"/artikel/{nr}")
        elif rolle == "tech":
            mess("Auftrags-Entnahme", c, "post", f"/ih/auftraege/{aid}/entnahme", data={"artikel_nr": nr, "platz": platz, "menge": "1"})
            mess("Seite Auftrag", c, "get", f"/ih/auftraege/{aid}")
        elif rolle == "schicht":
            if rnd.random() < 0.15:
                mess("Schicht beginnen", c, "post", "/ih/schichtbuch/beginnen", data={"schichtfuehrer": name})
            r = mess("Meldung anlegen", c, "post", "/ih/schichtbuch/neu", data={"titel": f"Last {name} {rnd.randint(1, 9999)}",
                                                                               "asset": "P -30101 A", "prioritaet": rnd.choice(["hoch", "mittel"])})
            m = re.search(r"/meldung/(\d+)", r.headers.get("location", ""))
            if m:
                mess("Meldung ergänzen", c, "post", f"/ih/schichtbuch/meldung/{m.group(1)}/ergaenzen",
                     data={"text": "erledigt", "status": rnd.choice(["in_arbeit", "erledigt"])})
            mess("Seite Schichtbuch", c, "get", "/ih/schichtbuch")
        else:  # lesend: Planer
            seiten = ["/ih/wartung", "/ih/wartung/kalender?wochen=52", "/ih/anlagen", "/ih", "/ih/schichtbuch/meldungen"]
            if name == "ing1":  # hat auch eine Lagerrolle
                seiten += ["/", "/bewegungen", "/artikel"]
            for pfad in seiten:
                mess("Seite lesen", c, "get", pfad)
        time.sleep(rnd.uniform(*PAUSE))


def pruefen():
    con = sqlite3.connect(DB)
    bad = con.execute("""SELECT b.artikel_id, b.lagerplatz_id, b.menge, coalesce(s.summe, 0) FROM bestand b
                         LEFT JOIN (SELECT artikel_id, lagerplatz_id, sum(menge) summe FROM bewegungen
                                    WHERE typ IN ('eingang','ausgang','inventur','anlage','umbuchung','ausleihe','rueckgabe') GROUP BY 1, 2) s
                         ON s.artikel_id = b.artikel_id AND s.lagerplatz_id = b.lagerplatz_id
                         WHERE abs(b.menge - coalesce(s.summe, 0)) > 1e-9""").fetchall()
    neg = con.execute("SELECT count(*) FROM bestand WHERE menge < 0").fetchone()[0]
    sch = con.execute("SELECT datum, zeit_id, count(*) FROM sb_schichten GROUP BY 1, 2 HAVING count(*) > 1").fetchall()
    ent = con.execute("SELECT count(*), -sum(menge) FROM bewegungen WHERE auftrag_id IS NOT NULL").fetchone()
    meld = con.execute("SELECT count(*) FROM sb_meldungen").fetchone()[0]
    verlauf_ohne = con.execute("SELECT count(*) FROM sb_meldungen m WHERE NOT EXISTS (SELECT 1 FROM sb_verlauf v WHERE v.meldung_id = m.id)").fetchone()[0]
    return bad, neg, sch, ent, meld, verlauf_ohne


if __name__ == "__main__":
    aid = vorbereiten()
    ende = time.time() + DAUER
    rollen = [("lager1", "lager"), ("lager2", "lager"), ("ing1", "lager"), ("tech1", "tech"), ("tech2", "tech"),
              ("op1", "schicht"), ("op2", "schicht"), ("sf1", "schicht"), ("ing1", "lesen"), ("sf1", "lesen")]
    ts = [threading.Thread(target=arbeiter, args=(n, r, aid, ende)) for n, r in rollen]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    bad, neg, sch, ent, meld, ohne = pruefen()
    print(f"Dauer {DAUER} s, 10 Benutzer gleichzeitig")
    for art in sorted(zeiten):
        z = sorted(zeiten[art])
        p95 = z[int(len(z) * 0.95) - 1] if len(z) > 1 else z[0]
        print(f"  {art:20s} {zaehler[art]:5d} Anfragen  Median {statistics.median(z)*1000:6.0f} ms  95 % {p95*1000:6.0f} ms  max {z[-1]*1000:6.0f} ms")
    print(f"Serverfehler/403: {len(fehler)}", *fehler[:10], sep="\n  ")
    print(f"Bestand = Summe der Buchungen: {'ja' if not bad else 'NEIN ' + str(bad[:5])}")
    print(f"Minusbestände: {neg}")
    print(f"Doppelte Schichten: {len(sch)}")
    print(f"Auftrags-Entnahmen: {ent[0]} Buchungen, {ent[1]} Stück")
    print(f"Schichtbuch-Meldungen: {meld}, ohne Verlauf: {ohne}")
    ok = not fehler and not bad and not neg and not sch and not ohne
    print("ERGEBNIS:", "OK" if ok else "FEHLER")
    sys.exit(0 if ok else 1)
