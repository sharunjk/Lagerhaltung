"""Instandhaltung als App fürs Handy (ab 2.9.0): Startseite /ih/m, Manifest und Service Worker mit Gültigkeit /ih/.

Alle Seiten der Instandhaltung sind auf dem Handy bedienbar; die App ist eine installierbare Hülle mit eigener Startseite,
eigenem Symbol und einer Leiste unten (base.html). Ohne Verbindung zeigt sie den Hinweis auf das Papierformular.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select

from .. import db
from ..db import ih_auftraege, ih_plaetze
from ..services import schichtbuch as sb
from ..web import render, require_recht, templates

router = APIRouter(prefix="/ih")


@router.get("/m")
def start(request: Request):
    me = require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        team = sb.team_von(con, me["id"])
        schicht = uebergaben = offene = None
        if sb.grunddaten_vorhanden(con):
            d, z = sb.laufender_slot(con, datetime.now())
            schicht = sb.schicht(con, datum=d, zeit_id=z["id"]) or {"text": sb.bezeichnung(d, z), "begonnen_am": None, "beendet_am": None, "team": None}
            uebergaben = len(sb.offene_uebergaben(con))
            offene = len(sb.offene(con))
        auftraege = con.execute(select(func.count()).select_from(ih_auftraege).where(ih_auftraege.c.status.in_(("freigegeben", "in_arbeit")))).scalar()
    return render(request, "ih/m_start.html", team=team, schicht=schicht, uebergaben=uebergaben, offene=offene, auftraege=auftraege)


@router.get("/m/suche")
def suche(request: Request, q: str = ""):
    """Tag-Nr. gescannt oder eingetippt: bei genau einem Treffer direkt zur Anlage."""
    require_recht(request, "ih.ansehen")
    from ..services.asset_import import schluessel
    q = " ".join(q.split())
    if q:
        with db.engine().connect() as con:
            pid = con.execute(select(ih_plaetze.c.id).where(ih_plaetze.c.schluessel == schluessel(q))).scalar()
        if pid:
            return RedirectResponse(f"/ih/anlagen/{pid}", status_code=303)
    return RedirectResponse(f"/ih/anlagen?q={quote(q)}" if q else "/ih/m", status_code=303)


@router.get("/manifest.webmanifest")
def manifest(request: Request):
    firma = request.app.state.cfg.server.firmenname
    return JSONResponse({
        "name": f"Instandhaltung {firma}", "short_name": "Instandhaltung", "id": "/ih/m", "start_url": "/ih/m", "scope": "/ih/",
        "display": "standalone", "orientation": "portrait", "background_color": "#EEF1F3", "theme_color": "#1F5FAE",
        "icons": [{"src": "/static/icon-ih-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-ih-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/static/icon-ih-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        "shortcuts": [{"name": "Neue Meldung", "url": "/ih/schichtbuch/neu"}, {"name": "Schichtbuch", "url": "/ih/schichtbuch"},
                      {"name": "Aufträge", "url": "/ih/auftraege"}],
    }, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker(request: Request):
    body = templates.get_template("ih/sw.js").render(version=request.app.state.static_v)
    return Response(body, media_type="application/javascript", headers={"Service-Worker-Allowed": "/ih/", "Cache-Control": "no-cache"})
