from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, insert, select, update

from .. import db
from ..db import artikel, lagerplaetze, users
from ..services import queries
from ..services.betrieb import check_pw, hash_pw
from ..services.lager import audit
from ..web import flash, pw_kennung, render, require, sicheres_ziel

router = APIRouter()


def _hat_admin() -> bool:
    with db.engine().connect() as con:
        return bool(con.execute(select(func.count()).select_from(users).where(users.c.pw_hash.isnot(None))).scalar())


def ist_mobil(request: Request) -> bool:
    ua = request.headers.get("user-agent", "").lower()
    return any(k in ua for k in ("android", "iphone", "mobile"))


@router.get("/login")
def login_form(request: Request, weiter: str = "/"):
    if not _hat_admin():
        return RedirectResponse("/einrichtung", status_code=303)
    return render(request, "login.html", weiter=weiter)


@router.post("/login")
def login(request: Request, username: str = Form(...), passwort: str = Form(""), weiter: str = Form("/")):
    with db.schreiben() as con:
        u = con.execute(select(users).where(func.lower(users.c.username) == username.strip().lower())).mappings().first()
        if not u or not u["aktiv"] or not u["pw_hash"] or not check_pw(passwort, u["pw_hash"]):
            return render(request, "login.html", weiter=weiter, fehler="Benutzername oder Passwort ist falsch.", username=username)
        con.execute(update(users).where(users.c.id == u["id"]).values(letzter_login=datetime.now()))
    request.session["user"] = {"id": u["id"], "username": u["username"], "name": u["anzeigename"] or u["username"], "rolle": u["rolle"],
                               "pw": pw_kennung(u["pw_hash"])}
    weiter = sicheres_ziel(weiter, "/")
    if weiter == "/" and ist_mobil(request):
        weiter = "/m"
    return RedirectResponse(weiter, status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/einrichtung")
def setup_form(request: Request):
    if _hat_admin():
        return RedirectResponse("/login", status_code=303)
    return render(request, "einrichtung.html")


@router.post("/einrichtung")
def setup(request: Request, username: str = Form(...), anzeigename: str = Form(""), passwort: str = Form(...), passwort2: str = Form(...)):
    if _hat_admin():
        return RedirectResponse("/login", status_code=303)
    if len(passwort) < 6 or passwort != passwort2:
        return render(request, "einrichtung.html", fehler="Passwörter stimmen nicht überein oder sind kürzer als 6 Zeichen.",
                      username=username, anzeigename=anzeigename)
    with db.schreiben() as con:
        vorhanden = con.execute(select(users.c.id).where(func.lower(users.c.username) == username.strip().lower())).scalar()
        werte = dict(anzeigename=anzeigename.strip() or username.strip(), pw_hash=hash_pw(passwort), rolle="admin", aktiv=True)
        if vorhanden:
            con.execute(update(users).where(users.c.id == vorhanden).values(**werte))
        else:
            con.execute(insert(users).values(username=username.strip(), **werte))
        audit(con, username, "Einrichtung", "Benutzer", {"admin": username})
    flash(request, "Administrator angelegt. Bitte anmelden.")
    return RedirectResponse("/login", status_code=303)


@router.get("/")
def dashboard(request: Request):
    require(request)
    with db.engine().connect() as con:
        d = queries.dashboard(con)
        letzte, _ = queries.bewegungen_liste(con, limit=12)
        leer = not con.execute(select(func.count()).select_from(artikel)).scalar()
    return render(request, "dashboard.html", d=d, letzte=letzte, last_id=letzte[0]["id"] if letzte else 0, leer=leer)


@router.get("/live", response_class=HTMLResponse)
def live(request: Request, seit: int = 0, n: int = 12):
    require(request)
    with db.engine().connect() as con:
        rows, _ = queries.bewegungen_liste(con, limit=max(1, min(n, 50)))
    return render(request, "partials/live.html", rows=rows, seit=seit, last_id=rows[0]["id"] if rows else 0)


@router.get("/scan")
def scan(request: Request, code: str = ""):
    """Universelles Scan-Ziel: Artikelnummer oder Lagerplatz erkennen."""
    require(request)
    code = code.strip()
    mobil = request.query_params.get("m") == "1"
    if not code:
        return RedirectResponse("/m" if mobil else "/", status_code=303)
    with db.engine().connect() as con:
        if con.execute(select(artikel.c.id).where(artikel.c.nummer == code)).first():
            return RedirectResponse(f"/m/artikel/{code}" if mobil else f"/buchen?artikel={code}", status_code=303)
        p = con.execute(select(lagerplaetze.c.code).where(func.lower(lagerplaetze.c.code) == code.lower())).scalar()
        if p:
            return RedirectResponse(f"/m/platz?code={p}" if mobil else f"/lagerplaetze/ansicht?code={p}", status_code=303)
    return RedirectResponse(f"/m/suche?q={code}" if mobil else f"/artikel?q={code}", status_code=303)


@router.get("/manifest.webmanifest")
def manifest(request: Request):
    """Desktop-App: in Edge/Chrome über „App installieren“ als eigenes Fenster mit Startmenü-Eintrag."""
    from fastapi.responses import JSONResponse
    firma = request.app.state.cfg.server.firmenname
    return JSONResponse({
        "name": f"Lagerverwaltung {firma}", "short_name": "Lagerverwaltung", "id": "/", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#EEF1F3", "theme_color": "#1C2A38",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}],
        "shortcuts": [{"name": "Buchen", "url": "/buchen"}, {"name": "Artikel", "url": "/artikel"}, {"name": "Bewegungen", "url": "/bewegungen"}],
    }, media_type="application/manifest+json")


@router.get("/arbeitsplatz.bat")
def arbeitsplatz(request: Request):
    """Skript für weitere Büro-PCs: legt eine Desktop-Verknüpfung an, die die Lagerverwaltung als eigenes Fenster öffnet."""
    from fastapi.responses import Response
    require(request)
    host = request.headers.get("host", "localhost:8080")
    if host.split(":")[0] in ("localhost", "127.0.0.1"):
        from ..services.zertifikat import lokale_adressen
        ips = [a for a in lokale_adressen() if a != "127.0.0.1"]
        host = f"{ips[0] if ips else 'localhost'}:{request.app.state.cfg.server.port}"
    url = f"http://{host}/"
    ps = f"""
$url = '{url}'
$ordner = Join-Path $env:LOCALAPPDATA 'Lagerverwaltung'
New-Item -ItemType Directory -Force -Path $ordner | Out-Null
$ico = Join-Path $ordner 'lager.ico'
try {{ Invoke-WebRequest -UseBasicParsing ($url + 'static/lager.ico') -OutFile $ico }} catch {{ }}
$edge = @("${{env:ProgramFiles(x86)}}\\Microsoft\\Edge\\Application\\msedge.exe", "$env:ProgramFiles\\Microsoft\\Edge\\Application\\msedge.exe") | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
if (-not $edge) {{ $edge = 'msedge.exe' }}
$sh = New-Object -ComObject WScript.Shell
foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
  $l = $sh.CreateShortcut((Join-Path $d 'Lagerverwaltung.lnk'))
  $l.TargetPath = $edge
  $l.Arguments = "--app=$url --window-size=1400,900"
  if (Test-Path $ico) {{ $l.IconLocation = $ico }}
  $l.Description = 'Lagerverwaltung'
  $l.Save()
}}
Write-Host 'Verknuepfung Lagerverwaltung auf dem Desktop und im Startmenue angelegt.'
"""
    import base64
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    bat = ("@echo off\r\nrem Legt auf diesem PC eine Verknuepfung \"Lagerverwaltung\" an (Desktop und Startmenue).\r\n"
           "rem Die Lagerverwaltung laeuft auf dem Lager-PC, hier wird nichts installiert.\r\n"
           f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {enc}\r\npause\r\n")
    return Response(bat.encode("cp1252"), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="Lagerverwaltung_Arbeitsplatz.bat"'})


@router.get("/zertifikat.crt")
def zertifikat(request: Request):
    """CA-Zertifikat zum Installieren auf Handhelds/Smartphones (öffentlich, enthält keinen Schlüssel)."""
    from fastapi.responses import Response
    from ..services.zertifikat import ca_pfade, ca_sicherstellen
    cfg = request.app.state.cfg
    ca_sicherstellen(cfg.path("daten"))
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    der = x509.load_pem_x509_certificate(ca_pfade(cfg.path("daten"))[0].read_bytes()).public_bytes(serialization.Encoding.DER)
    return Response(der, media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="Lagerverwaltung-CA.crt"'})


@router.get("/suche", response_class=HTMLResponse)
def schnellsuche(request: Request, q: str = ""):
    require(request)
    treffer = []
    if len(q.strip()) >= 2:
        with db.engine().connect() as con:
            treffer = queries.artikel_liste(con, q=q)[:8]
    return render(request, "partials/suche.html", treffer=treffer, q=q)
