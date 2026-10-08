"""Rollen-Matrix: jede Route als Gast/lesen/lager/admin aufrufen und die tatsächlich nötige Rolle bestimmen."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
tmp = tempfile.mkdtemp()
os.environ["LV_HOME"] = tmp
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402

import app.config as C  # noqa: E402
from app import db  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import users  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.betrieb import hash_pw  # noqa: E402
from app.services.lager import Lager  # noqa: E402

cfg = Config()
cfg.daten.datenbank = f"{tmp}/lager.db"
cfg.daten.anhaenge = f"{tmp}/anh"
cfg.server.secret_key = "x" * 32
cfg.drucker.modus = "datei"
cfg.drucker.datei_ordner = f"{tmp}/druck"
cfg.backup.ordner = f"{tmp}/bk"
C.CONFIG_PATH = Path(tmp) / "config.toml"
app = create_app(cfg, start_scheduler=False)
with db.schreiben() as con:
    for r in ("lesen", "lager", "admin"):
        con.execute(insert(users).values(username=r, anzeigename=r, pw_hash=hash_pw("geheim1"), rolle=r, aktiv=True, api_token=f"tok_{r}"))
    Lager(con, "admin").artikel_anlegen({"nummer": "10001", "bezeichnung": "Test"}, "C1-R1-1", 5)

SAMPLE = {"nr": "10001", "fmt": "csv", "art": "verbrauch", "name": "x.zip", "uid": "999"}


import base64  # noqa: E402
FORM = {"artikel_nr": "10001", "artikel": "10001", "menge": "1", "fuer": "x", "status": "offen", "code": "C9-TEST", "von": "C9-X", "nach": "C9-Y",
        "username": "neu_x", "passwort": "", "alt": "falsch", "neu": "geheim2", "neu2": "geheim2", "payload": base64.b64encode(b"[]").decode(),
        "lagerort": "C1-R1-1", "name": "Inv", "typ": "eingang"}


def pfad(p):
    return re.sub(r"\{(\w+)\}", lambda m: SAMPLE.get(m.group(1), "1"), p)


def klasse(r):
    loc = r.headers.get("location", "")
    if r.status_code == 401 or (r.status_code in (302, 303, 307) and loc.startswith("/login")) or r.headers.get("hx-redirect") == "/login":
        return "login"
    if r.status_code >= 500:
        return "FEHLER"
    if r.status_code == 403 or "Keine Berechtigung" in r.text or "keine Berechtigung" in r.text or "darf nicht" in r.text:
        return "verboten"
    return "ok"


clients = {}
for r in (None, "lesen", "lager", "admin"):
    c = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    if r:
        assert c.post("/login", data={"username": r, "passwort": "geheim1"}).status_code == 303
    clients[r] = c

rows = []
def alle_routen(routes):
    for r in routes:
        if hasattr(r, "original_router"):
            pre = getattr(r, "include_context", None)
            prefix = getattr(pre, "prefix", "") if pre is not None else ""
            for pre2, x in alle_routen(r.original_router.routes):
                yield prefix + pre2, x
        else:
            yield "", r


for prefix, route in alle_routen(app.routes):
    p = prefix + getattr(route, "path", "")
    if not p or p.startswith("/static") or p in ("/logout", "/login", "/einrichtung"):
        continue
    for m in sorted(getattr(route, "methods", []) or []):
        if m == "HEAD":
            continue
        res = {}
        # admin zuletzt, damit zerstörende Aktionen (Archivieren usw.) die anderen Aufrufe nicht beeinflussen
        for r in (None, "lesen", "lager", "admin"):
            c = clients[r]
            url = pfad(p)
            if p.startswith("/api/"):
                h = {"Authorization": f"Bearer tok_{r}"} if r else {}
                body = {"typ": "eingang", "artikel": "10001", "menge": 1, "lagerplatz": "C1-R1-1", "fuer": "x"} if m == "POST" else None
                resp = c.request(m, url, headers=h, json=body)
            else:
                if m == "POST" and p == "/m/sync":
                    resp = c.request(m, url, json={"items": []})
                elif m == "POST":
                    resp = c.request(m, url, data=FORM, files={"datei": ("x.txt", b"x", "text/plain")})
                else:
                    resp = c.request(m, url, params={"code": "C1-R1-1"})
            res[r or "gast"] = f"{klasse(resp)}({resp.status_code})"
        noetig = next((r for r in ("gast", "lesen", "lager", "admin") if res[r].startswith("ok")), "keiner")
        rows.append((m, p, noetig, res))
json.dump(rows, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
for m, p, n, res in rows:
    print(f"{m:5} {p:45} min={n:6} " + " ".join(f"{k}={v}" for k, v in res.items()))
