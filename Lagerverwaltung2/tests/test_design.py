"""2.11.0: Design-Umschalter Standard / Corporate Identity (Farben, Schrift Barlow Regular/Bold, Logo, App-Symbole)."""
from __future__ import annotations

import re
from pathlib import Path

from test_cmms_phase0 import cmms_an
from test_pruefung import client

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
ALLGEMEIN = {"firmenname": "CAPHENIA", "port": "8080", "https_port": "8443", "standard_einheit": "Stk", "live_abfrage_sekunden": "10",
             "programmname": "Lagerverwaltung", "cmms_aktiv": "on"}


def _html_klasse(text: str) -> str:
    return re.search(r'<html lang="de" class="([^"]*)"', text).group(1)


def test_standard_bleibt_unveraendert(env):
    cfg, eng = env
    cmms_an(cfg)
    admin = client(cfg, "admin")
    seite = admin.get("/artikel").text
    assert cfg.server.design == "standard" and _html_klasse(seite) == "" and "logo-ci" not in seite
    assert admin.get("/manifest.webmanifest").json()["icons"][0]["src"] == "/static/icon-192.png"
    assert "logo-ci" not in client(cfg).get("/login").text


def test_ci_umschalten_und_zurueck(env):
    cfg, eng = env
    cmms_an(cfg)
    admin = client(cfg, "admin")
    assert 'name="design" value="ci"' in admin.get("/einstellungen?tab=allgemein").text
    admin.post("/einstellungen/allgemein", data={**ALLGEMEIN, "design": "ci"})
    assert cfg.server.design == "ci"
    from app.config import CONFIG_PATH
    import tomllib
    assert tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))["server"]["design"] == "ci"
    # PC (Lager und Instandhaltung), Scanner-App, Anmeldung
    lager = admin.get("/artikel").text
    assert _html_klasse(lager) == "ci" and 'src="/static/logo-ci.svg"' in lager and 'href="/static/logo-ci.svg"' in lager
    ih = admin.get("/ih/schichtbuch").text
    assert _html_klasse(ih) == "ci" and 'href="/static/logo-ci-ih.svg"' in ih and "apple-touch-icon-ci-ih.png" in ih
    assert _html_klasse(admin.get("/m").text) == "ci"
    login = client(cfg).get("/login").text
    assert "Lager und Instandhaltung." in login and "logo-ci.svg" in login
    # App-Symbole je Design
    assert admin.get("/manifest.webmanifest").json()["icons"][0]["src"] == "/static/icon-ci-192.png"
    assert admin.get("/m/manifest.webmanifest").json()["icons"][2]["src"] == "/static/icon-ci-maskable-512.png"
    assert admin.get("/ih/manifest.webmanifest").json()["icons"][0]["src"] == "/static/icon-ci-ih-192.png"
    for name in ("logo-ci.svg", "logo-ci-ih.svg", "icon-ci-192.png", "icon-ci-512.png", "icon-ci-maskable-512.png", "icon-ci-ih-192.png",
                 "icon-ci-ih-512.png", "icon-ci-ih-maskable-512.png", "apple-touch-icon-ci.png", "apple-touch-icon-ci-ih.png",
                 "fonts/barlow-latin-700-normal.woff2"):
        assert client(cfg).get(f"/static/{name}").status_code == 200, name
    # unbekannter Wert -> Standard
    admin.post("/einstellungen/allgemein", data={**ALLGEMEIN, "design": "lila"})
    assert cfg.server.design == "standard" and _html_klasse(admin.get("/artikel").text) == ""


def test_ci_stylesheet():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for regel in (".ci{", ".ci.dark{", "--primary:197 22 32", "--ink:38 59 73", "--bg:236 237 235", '--font-cond:"Barlow"',
                  "barlow-latin-700-normal.woff2", ".ci .st-kritisch", ".ci .status.text-primary", "font-family:var(--font-cond)"):
        assert regel in css.replace(", ", ","), regel
