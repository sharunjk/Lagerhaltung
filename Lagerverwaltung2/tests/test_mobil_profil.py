"""Scanner-App: Profil (Abmelden, Benutzer wechseln, Passwort, Geräteeinstellungen), Wechsel PC ↔ Scanner-Ansicht."""
from __future__ import annotations

from urllib.parse import unquote

from sqlalchemy import insert

from test_pruefung import client

PW = "Lager-Test-2026"
HANDY = {"user-agent": "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"}


def test_profil_und_leiste(env):
    cfg, _ = env
    c = client(cfg, "lager")
    start = c.get("/m").text
    assert 'href="/m/profil"' in start and "grid-cols-5" in start
    assert '>PC</a>' not in start  # kein PC-Knopf mehr oben rechts
    t = c.get("/m/profil").text
    for text in ("Abmelden / Benutzer wechseln", 'href="/m/passwort"', "PC-Ansicht öffnen", 'href="/"', "Ton beim Scannen", "Vibration",
                 "Offline-Daten", "Darstellung", "lager · Lager"):
        assert text in t, text


def test_anmelden_innerhalb_der_app(env):
    cfg, _ = env
    c = client(cfg)
    r = c.get("/m/profil")
    assert r.status_code == 303 and r.headers["location"] == "/m/login?weiter=%2Fm%2Fprofil"
    seite = c.get(r.headers["location"]).text
    assert 'name="weiter" value="/m/profil"' in seite
    r = c.post("/login", data={"username": "lager", "passwort": PW, "weiter": "/m/profil"})
    assert r.headers["location"] == "/m/profil"
    # fremde Ziele werden nicht übernommen
    assert c.get("/m/login?weiter=/m/suche").headers["location"] == "/m/suche"  # schon angemeldet
    assert 'name="weiter" value="/m"' in client(cfg).get("/m/login?weiter=https://boese.example").text
    # PC-Seiten weiterhin über /login
    assert c.get("/logout").headers["location"] == "/login"
    assert client(cfg).get("/artikel").headers["location"].startswith("/login?")


def test_abmelden_und_benutzer_wechseln(env):
    cfg, _ = env
    c = client(cfg, "lager")
    r = c.get("/logout?weiter=/m")
    assert r.headers["location"] == "/m/login?weiter=%2Fm"
    assert c.get("/m").status_code == 303  # abgemeldet
    assert c.get("/logout?weiter=https://boese.example").headers["location"] == "/login"
    c.post("/login", data={"username": "admin", "passwort": PW, "weiter": "/m"})
    assert "admin · Administrator" in c.get("/m/profil").text


def test_passwort_in_der_app(env):
    cfg, _ = env
    c = client(cfg, "lager")
    t = c.get("/m/passwort").text
    assert 'name="weiter" value="/m/profil"' in t and "grid-cols-5" in t
    r = c.post("/passwort", data={"alt": "falsch", "neu": "Neues-Passwort-1", "neu2": "Neues-Passwort-1", "weiter": "/m/profil"})
    assert "Aktuelles Passwort ist falsch" in r.text and "grid-cols-5" in r.text  # Fehler in der App-Ansicht
    r = c.post("/passwort", data={"alt": PW, "neu": "Neues-Passwort-1", "neu2": "Neues-Passwort-1", "weiter": "/m/profil"})
    assert r.headers["location"] == "/m/profil"
    # am PC wie bisher
    c2 = client(cfg, "admin")
    r = c2.post("/passwort", data={"alt": PW, "neu": "Neues-Passwort-2", "neu2": "Neues-Passwort-2"})
    assert r.headers["location"] == "/"
    r = c2.post("/passwort", data={"alt": "x", "neu": "a", "neu2": "a", "weiter": "https://boese.example"})
    assert "flash-fehler" in r.text and "grid-cols-5" not in r.text


def test_kurzes_passwort_am_handy_fuehrt_in_die_app(env):
    from app import db
    from app.db import users
    from app.services.betrieb import hash_pw
    cfg, _ = env
    c = client(cfg)
    with db.engine().execution_options(schreiben=True).begin() as con:
        con.execute(insert(users).values(username="alt", anzeigename="Alt", pw_hash=hash_pw("kurz"), rolle="lager", aktiv=True))
    r = c.post("/login", data={"username": "alt", "passwort": "kurz", "weiter": "/m"})
    assert r.headers["location"] == "/m/passwort"
    r = client(cfg).post("/login", data={"username": "alt", "passwort": "kurz", "weiter": "/"}, headers=HANDY)
    assert r.headers["location"] == "/m/passwort"
    assert client(cfg).post("/login", data={"username": "alt", "passwort": "kurz"}).headers["location"] == "/passwort"


def test_pc_ansicht_hat_weg_zurueck(env):
    cfg, _ = env
    c = client(cfg, "lager")
    t = c.get("/", headers=HANDY).text
    knopf = [z for z in t.splitlines() if 'href="/m"' in z and "Scanner-Ansicht" in z]
    assert knopf and "hidden md:inline-flex" not in knopf[0]  # auch auf dem Handy sichtbar
    assert t.count('href="/m"') >= 2  # Kopfzeile und Menü


def test_dateiversion_aendert_sich_mit_dem_inhalt(env, monkeypatch, tmp_path):
    import app.main as m
    cfg, _ = env
    c = client(cfg, "lager")
    v = c.app.state.static_v
    assert v.startswith(m.VERSION + "-") and f"app.css?v={v}" in c.get("/m").text and f"app.css?v={v}" in c.get("/").text
    assert f"?v={v}" in c.get("/m/sw.js").text
    assert unquote(v) == v
