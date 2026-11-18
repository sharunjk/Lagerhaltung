"""Schichtbuch-Ergänzungen (ab 2.13.0): EX-Handys (Nummer, SIM-PIN hinter Passwort) und Aufgaben (To-do-Liste).

Rechte: ansehen = ih.schichtbuch.ansehen; Aufgaben anlegen/erledigen und PIN anzeigen = ih.schichtbuch.schreiben;
Handys pflegen und Aufgaben löschen = ih.schichtbuch.einrichten (Aufgaben auch, wer sie angelegt hat).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from .. import db
from ..db import ih_plaetze, sb_aufgaben, users
from ..rechte import hat_recht
from ..services import aufgaben as aufg
from ..services import handys as hy
from ..services import schichtbuch as sb
from ..services.betrieb import check_pw
from ..services.excel import tabelle_xlsx
from ..services.lager import audit
from ..web import current_user, flash, render, require_recht

router = APIRouter(prefix="/ih/schichtbuch")


def _geheim(request) -> str:
    return request.app.state.cfg.server.secret_key or ""


# ------------------------------------------------------------------ EX-Handys
@router.get("/handys")
def handys(request: Request, bearbeiten: int = 0):
    require_recht(request, "ih.schichtbuch.ansehen")
    with db.engine().connect() as con:
        liste = hy.liste(con, alle=True)
        for h in liste:
            h["verlauf"] = hy.verlauf(con, h["id"], 8)
    return render(request, "ih/sb_handys.html", handys=liste, bearbeiten=bearbeiten)


@router.post("/handys")
async def handy_speichern(request: Request):
    me = require_recht(request, "ih.schichtbuch.einrichten")
    f = await request.form()
    hid = int(f["id"]) if (f.get("id") or "").isdigit() else None
    # leer = unverändert lassen; „löschen“ angehakt = entfernen
    pin = "" if f.get("pin_loeschen") == "on" else ((f.get("pin") or "").strip() or None)
    puk = "" if f.get("puk_loeschen") == "on" else ((f.get("puk") or "").strip() or None)
    try:
        with db.schreiben() as con:
            hid = hy.speichern(con, hid, f.get("name") or "", f.get("nummer") or "", pin, puk, f.get("bemerkung") or "",
                               f.get("aktiv", "on") == "on", _geheim(request), me["username"])
            audit(con, me["username"], "EX-Handy gespeichert", f.get("name") or str(hid),
                  {"pin_geaendert": pin is not None, "puk_geaendert": puk is not None})
    except ValueError as e:
        flash(request, str(e), "fehler")
        return RedirectResponse("/ih/schichtbuch/handys?bearbeiten=1", status_code=303)
    flash(request, "EX-Handy gespeichert.")
    return RedirectResponse("/ih/schichtbuch/handys", status_code=303)


@router.post("/handys/{hid}/anzeigen")
async def handy_geheim(request: Request, hid: int):
    """PIN/PUK anzeigen – nur nach Eingabe des eigenen Passworts (mit Sperre nach Fehlversuchen). Wird protokolliert."""
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    feld = f.get("feld") if f.get("feld") in ("pin", "puk") else "pin"
    sperre, ip = request.app.state.anmeldesperre, (request.client.host if request.client else "?")
    if sperre.sperre_sekunden(ip, me["username"]):
        return JSONResponse({"fehler": "Zu viele Fehlversuche. Bitte später erneut versuchen."}, status_code=429)
    with db.engine().connect() as con:
        u = con.execute(select(users.c.pw_hash).where(users.c.id == me["id"])).scalar()
        if not u or not check_pw(f.get("passwort") or "", u):
            sperre.fehlschlag(ip, me["username"])
            return JSONResponse({"fehler": "Passwort ist falsch."}, status_code=403)
        wert = hy.geheimnis(con, hid, feld, _geheim(request))
        name = con.execute(select(hy.sb_handys.c.name).where(hy.sb_handys.c.id == hid)).scalar()
    if not name:
        return JSONResponse({"fehler": "EX-Handy nicht gefunden."}, status_code=404)
    with db.schreiben() as con:
        audit(con, me["username"], f"EX-Handy: {feld.upper()} angezeigt", name)
    if wert is None:
        return JSONResponse({"fehler": f"Keine {feld.upper()} gespeichert (oder nicht lesbar – bitte neu eintragen)."}, status_code=404)
    return JSONResponse({"wert": wert}, headers={"Cache-Control": "no-store"})


@router.post("/handys/{hid}/uebergeben")
async def handy_uebergeben(request: Request, hid: int):
    """EX-Handy außerhalb der Schichtübergabe weitergeben (z. B. Tausch innerhalb der Schicht)."""
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            d, z = sb.laufender_slot(con)
            s = sb.schicht(con, datum=d, zeit_id=z["id"])
            hy.uebergabe_speichern(con, hid, s["id"] if s else None, me["name"], f.get("an") or "", me["username"])
            audit(con, me["username"], "EX-Handy übergeben", str(hid), {"an": f.get("an")})
    except ValueError as e:
        flash(request, str(e), "fehler")
    else:
        flash(request, f"EX-Handy an {f.get('an')} übergeben.")
    return RedirectResponse("/ih/schichtbuch/handys", status_code=303)


# ------------------------------------------------------------------ Aufgaben (To-do-Liste)
def _ctx(con, **extra) -> dict:
    return dict(teams=sb.teams(con), PRIO=aufg.PRIO, STATUS=aufg.STATUS,
                tags=[(r.code, r.bezeichnung or "") for r in con.execute(select(ih_plaetze.c.code, ih_plaetze.c.bezeichnung)
                                                                        .where(ih_plaetze.c.aktiv, ih_plaetze.c.art == "platz").order_by(ih_plaetze.c.code))],
                **extra)


def _darf_loeschen(request, a: dict) -> bool:
    me = current_user(request)
    return bool(me) and (hat_recht(me, "ih.schichtbuch.einrichten", request.app.state.cfg) or a["erstellt_von"] == me["username"])


@router.get("/aufgaben")
def aufgaben(request: Request, status: str = "offen", team: str = "", q: str = "", nur: str = ""):
    require_recht(request, "ih.schichtbuch.ansehen")
    sb_ok = _grund()
    with db.engine().connect() as con:
        rows = aufg.liste(con, status, team, q, nur)
        return render(request, "ih/sb_aufgaben.html", rows=rows, fl={"status": status, "team": team, "q": q, "nur": nur},
                      query=request.url.query, **_ctx(con, sb_ok=sb_ok))


def _grund() -> bool:
    with db.engine().connect() as con:
        if sb.grunddaten_vorhanden(con):
            return True
    with db.schreiben() as con:
        sb.sicherstellen(con)
    return True


@router.get("/aufgaben/export.xlsx")
def aufgaben_export(request: Request, status: str = "offen", team: str = "", q: str = "", nur: str = ""):
    require_recht(request, "ih.schichtbuch.ansehen")
    with db.engine().connect() as con:
        rows = aufg.liste(con, status, team, q, nur, limit=100_000)
    kopf = ["Nr.", "Titel", "Beschreibung", "Team", "Priorität", "Fällig", "Status", "Anlage", "Wiederholen (Tage)", "Angelegt", "Angelegt von",
            "Erledigt", "Erledigt von", "Erledigt-Notiz"]
    z = [[a["id"], a["titel"], a["beschreibung"], a["team"] or "alle Teams", aufg.PRIO.get(a["prioritaet"]), a["faellig"], aufg.STATUS.get(a["status"]),
          a["asset"], a["wiederholen_tage"], a["erstellt_am"], a["erstellt_von"], a["erledigt_am"], a["erledigt_von"], a["erledigt_text"]] for a in rows]
    return Response(tabelle_xlsx("Aufgaben", kopf, z), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Aufgaben_{date.today():%Y-%m-%d}.xlsx"'})


@router.get("/aufgaben/neu")
def aufgabe_neu_form(request: Request, team: str = ""):
    require_recht(request, "ih.schichtbuch.schreiben")
    _grund()
    with db.engine().connect() as con:
        return render(request, "ih/sb_aufgabe_form.html", a={"team_id": int(team) if team.isdigit() else None, "prioritaet": "mittel"}, neu=True, **_ctx(con))


@router.post("/aufgaben/neu")
async def aufgabe_neu(request: Request):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            aid = aufg.anlegen(con, aufg.werte(con, f), me["username"])
            audit(con, me["username"], "Aufgabe angelegt", f"Aufgabe {aid}", {"titel": f.get("titel")})
    except aufg.AufgabenFehler as e:
        with db.engine().connect() as con:
            return render(request, "ih/sb_aufgabe_form.html", a=dict(f), neu=True, fehler=str(e), **_ctx(con))
    flash(request, f"Aufgabe „{f.get('titel')}“ angelegt.")
    return RedirectResponse("/ih/schichtbuch/aufgaben" if f.get("weiter") != "neu" else "/ih/schichtbuch/aufgaben/neu", status_code=303)


@router.get("/aufgaben/{aid}")
def aufgabe(request: Request, aid: int, bearbeiten: int = 0):
    require_recht(request, "ih.schichtbuch.ansehen")
    with db.engine().connect() as con:
        a = aufg.holen(con, aid)
        if not a:
            return render(request, "fehler.html", titel="Aufgabe nicht gefunden", text="Diese Aufgabe gibt es nicht (mehr).")
        if bearbeiten and hat_recht(current_user(request), "ih.schichtbuch.schreiben", request.app.state.cfg):
            return render(request, "ih/sb_aufgabe_form.html", a=a, neu=False, **_ctx(con))
        return render(request, "ih/sb_aufgabe.html", a=a, darf_loeschen=_darf_loeschen(request, a), **_ctx(con))


@router.post("/aufgaben/{aid}")
async def aufgabe_speichern(request: Request, aid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            aufg.aendern(con, aid, aufg.werte(con, f), me["username"])
    except aufg.AufgabenFehler as e:
        with db.engine().connect() as con:
            return render(request, "ih/sb_aufgabe_form.html", a={**dict(f), "id": aid}, neu=False, fehler=str(e), **_ctx(con))
    flash(request, "Aufgabe gespeichert.")
    return RedirectResponse(f"/ih/schichtbuch/aufgaben/{aid}", status_code=303)


@router.post("/aufgaben/{aid}/status")
async def aufgabe_status(request: Request, aid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            nid = aufg.status_setzen(con, aid, f.get("status") or "", me["username"], f.get("text") or "")
            audit(con, me["username"], "Aufgabe: Status", f"Aufgabe {aid}", {"status": f.get("status")})
    except aufg.AufgabenFehler as e:
        flash(request, str(e), "fehler")
    else:
        flash(request, f"Aufgabe {aufg.STATUS.get(f.get('status'), '').lower()}." + (f" Nächste Wiederholung als Aufgabe Nr. {nid} angelegt." if nid else ""))
    return RedirectResponse("/ih/schichtbuch#aufgaben" if f.get("weiter") == "dashboard" else f"/ih/schichtbuch/aufgaben/{aid}", status_code=303)


@router.post("/aufgaben/{aid}/kommentar")
async def aufgabe_kommentar(request: Request, aid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            aufg.kommentar(con, aid, me["username"], f.get("text") or "")
    except aufg.AufgabenFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(f"/ih/schichtbuch/aufgaben/{aid}", status_code=303)


@router.post("/aufgaben/{aid}/loeschen")
def aufgabe_loeschen(request: Request, aid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    with db.schreiben() as con:
        a = aufg.holen(con, aid)
        if not a:
            return RedirectResponse("/ih/schichtbuch/aufgaben", status_code=303)
        if not _darf_loeschen(request, a):
            flash(request, "Löschen darf, wer die Aufgabe angelegt hat, oder Schichtführer/Manager.", "fehler")
            return RedirectResponse(f"/ih/schichtbuch/aufgaben/{aid}", status_code=303)
        con.execute(sb_aufgaben.delete().where(sb_aufgaben.c.id == aid))
        audit(con, me["username"], "Aufgabe gelöscht", f"Aufgabe {aid}", {"titel": a["titel"]})
    flash(request, f"Aufgabe „{a['titel']}“ gelöscht.")
    return RedirectResponse("/ih/schichtbuch/aufgaben", status_code=303)
