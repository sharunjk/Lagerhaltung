from __future__ import annotations

import csv
import io
from urllib.parse import quote
from datetime import date, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import insert, select, update

from .. import db
from ..db import artikel, reservierungen
from ..services import queries
from ..services.excel import tabelle_xlsx
from ..services.lager import BuchungsFehler, Lager, audit, fmt_num, parse_num
from ..web import flash, render, require, sicheres_ziel, zurueck
from .artikel import lager

router = APIRouter()

TYPEN = {"ausgang": "Entnahme", "eingang": "Eingang", "umbuchung": "Umbuchen", "inventur": "Zählen", "ausleihe": "Ausleihe"}


def _d(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def buchung_ausfuehren(L: Lager, typ: str, nr: str, menge: str, platz: str, ziel: str = "", empfaenger: str = "",
                       kostenstelle: str = "", zweck: str = "", rueckgabe_bis: str = "", reservierung_id: str = "") -> str:
    """Gemeinsame Buchungsfunktion für PC, Handy und API. Gibt eine Erfolgsmeldung zurück (IDs stehen in ``L.ids``)."""
    m = parse_num(menge)
    ext = dict(empfaenger=empfaenger, kostenstelle=kostenstelle, zweck=zweck)
    if typ == "eingang":
        e = L.eingang(nr, platz, m, **ext)
        return f"Eingang: {fmt_num(m)} × {nr} auf {e.platz} (jetzt {fmt_num(e.bestand_nachher)})"
    if typ == "ausgang":
        e = L.ausgang(nr, platz, m, reservierung_id=int(reservierung_id) if str(reservierung_id).isdigit() else None, **ext)
        return f"Entnahme: {fmt_num(m)} × {nr} von {e.platz} (Rest {fmt_num(e.bestand_nachher)})"
    if typ == "umbuchung":
        e1, e2 = L.umbuchung(nr, platz, ziel, m)
        return f"Umgebucht: {fmt_num(m)} × {nr} von {e1.platz} nach {e2.platz}"
    if typ == "inventur":
        e = L.inventur(nr, platz, menge)
        return f"Gezählt: {nr} auf {e.platz} = {fmt_num(e.bestand_nachher)} (Differenz {'+' if e.menge > 0 else ''}{fmt_num(e.menge)})"
    if typ == "ausleihe":
        L.ausleihe(nr, platz, m, empfaenger, _d(rueckgabe_bis), kostenstelle=kostenstelle, zweck=zweck)
        return f"Ausgeliehen: {fmt_num(m)} × {nr} an {empfaenger.strip()}"
    raise BuchungsFehler("Unbekannte Buchungsart.")


@router.get("/buchen")
def buchen_seite(request: Request, artikel: str = "", typ: str = "ausgang", ort: str = "", reservierung: str = ""):
    require(request)
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, artikel.strip()) if artikel.strip() else None
        vs = queries.vorschlaege(con)
        letzte, _ = queries.bewegungen_liste(con, benutzer=request.session["user"]["username"], limit=8)
    typ = typ if typ in TYPEN else "ausgang"
    return render(request, "buchen.html", a=a, artikel=artikel, typ=typ, vs=vs, letzte=letzte, ort=ort, reservierung=reservierung,
                  nicht_gefunden=bool(artikel.strip() and not a), TYPEN=TYPEN)


@router.get("/buchen/panel", response_class=HTMLResponse)
def panel(request: Request, artikel: str = "", typ: str = "ausgang", ort: str = ""):
    require(request)
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, artikel.strip()) if artikel.strip() else None
        vs = queries.vorschlaege(con)
    return render(request, "partials/buchen_panel.html", a=a, artikel=artikel, typ=typ if typ in TYPEN else "ausgang", vs=vs, ort=ort,
                  reservierung="", nicht_gefunden=bool(artikel.strip() and not a), TYPEN=TYPEN)


@router.post("/buchen")
async def buchen(request: Request):
    require(request, "lager")
    f = dict(await request.form())
    nr, typ = (f.get("artikel") or "").strip(), f.get("typ", "")
    try:
        with db.schreiben() as con:
            msg = buchung_ausfuehren(lager(con, request), typ, nr, f.get("menge", ""), f.get("lagerort", ""), f.get("ziel", ""),
                                     f.get("empfaenger", ""), f.get("kostenstelle", ""), f.get("zweck", ""), f.get("rueckgabe_bis", ""),
                                     f.get("reservierung_id", ""))
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/buchen?artikel={quote(nr)}&typ={quote(typ)}", status_code=303)
    flash(request, msg)
    return RedirectResponse(sicheres_ziel(f.get("weiter"), f"/buchen?typ={quote(typ)}"), status_code=303)


# ------------------------------------------------------------------ Bewegungen
@router.get("/bewegungen")
def liste(request: Request, q: str = "", typ: str = "", benutzer: str = "", platz: str = "", von: str = "", bis: str = "", seite: int = 1):
    require(request)
    pro = 100
    with db.engine().connect() as con:
        rows, total = queries.bewegungen_liste(con, typ=typ, benutzer=benutzer, platz=platz, von=_d(von), bis=_d(bis), q=q,
                                               limit=pro, offset=(max(1, seite) - 1) * pro)
        nutzer = queries.benutzernamen(con)
    return render(request, "bewegungen.html", rows=rows, total=total, seite=seite, seiten=max(1, (total - 1) // pro + 1),
                  q=q, typ=typ, benutzer=benutzer, platz=platz, von=von, bis=bis, nutzer=nutzer)


@router.get("/bewegungen/export.{fmt}")
def export(request: Request, fmt: str, q: str = "", typ: str = "", benutzer: str = "", platz: str = "", von: str = "", bis: str = ""):
    require(request)
    with db.engine().connect() as con:
        rows, _ = queries.bewegungen_liste(con, typ=typ, benutzer=benutzer, platz=platz, von=_d(von), bis=_d(bis), q=q, limit=1_000_000)
    kopf = ["Nr.", "Zeit", "Artikel", "Bezeichnung", "Lagerplatz", "Menge", "Bestand danach", "Art", "Benutzer", "Empfänger", "Kostenstelle", "Zweck", "Info"]
    z = [[r["id"], r["zeit"], r["artikel_nr"], r["bezeichnung"], r["lagerplatz"], r["menge"], r["bestand_nachher"],
          queries.TYP_TEXT.get(r["typ"], r["typ"]), r["benutzer"], r["empfaenger"], r["kostenstelle"], r["zweck"], r["text"]] for r in rows]
    name = f"Bewegungen_{date.today():%Y-%m-%d}"
    if fmt == "xlsx":
        return Response(tabelle_xlsx("Bewegungen", kopf, z), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(kopf)
    for r in z:
        w.writerow(["" if v is None else (fmt_num(v) if isinstance(v, float) else (v.strftime("%d.%m.%Y %H:%M") if isinstance(v, datetime) else v)) for v in r])
    return Response(buf.getvalue().encode("cp1252", errors="replace"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.post("/bewegungen/{bid}/storno")
def storno(request: Request, bid: int):
    require(request, "lager")
    try:
        with db.schreiben() as con:
            lager(con, request).storno(bid)
            audit(con, request.session["user"]["username"], "Storno", str(bid))
        flash(request, f"Buchung {bid} storniert (Gegenbuchung angelegt).")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(zurueck(request, "/bewegungen"), status_code=303)


# ------------------------------------------------------------------ Ausleihen
@router.get("/ausleihen")
def ausleihen(request: Request):
    require(request)
    with db.engine().connect() as con:
        rows = queries.offene_ausleihen(con)
    return render(request, "ausleihen.html", rows=rows)


@router.post("/ausleihen/{bid}/rueckgabe")
def rueckgabe(request: Request, bid: int, menge: str = Form(""), platz: str = Form("")):
    require(request, "lager")
    try:
        with db.schreiben() as con:
            e = lager(con, request).rueckgabe(bid, menge or None, platz or None)
        flash(request, f"Rückgabe gebucht: {fmt_num(e.menge)} × {e.artikel_nr} auf {e.platz}.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(zurueck(request, "/ausleihen"), status_code=303)


# ------------------------------------------------------------------ Reservierungen
@router.get("/reservierungen")
def reservierungen_liste(request: Request, status: str = "offen"):
    require(request)
    r = reservierungen
    with db.engine().connect() as con:
        q = select(r, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit).join(artikel, artikel.c.id == r.c.artikel_id)
        if status == "offen":
            q = q.where(r.c.status == "offen")
        rows = [dict(x) for x in con.execute(q.order_by(r.c.bis.is_(None), r.c.bis, r.c.id.desc()).limit(500)).mappings()]
        best = {a["id"]: a for a in queries.artikel_liste(con)}
    for x in rows:
        a = best.get(x["artikel_id"])
        x["bestand"] = a["bestand"] if a else 0
        x["orte"] = a["orte"] if a else []
    return render(request, "reservierungen.html", rows=rows, status=status, heute=date.today())


@router.post("/reservierungen/neu")
def reservierung_neu(request: Request, artikel_nr: str = Form(...), menge: str = Form(...), fuer: str = Form(...), person: str = Form(""), bis: str = Form("")):
    require(request, "lager")
    m = parse_num(menge)
    weiter = zurueck(request, "/reservierungen")
    try:
        if not m or m <= 0:
            raise BuchungsFehler("Bitte eine Menge größer 0 angeben.")
        if not fuer.strip():
            raise BuchungsFehler("Bitte angeben, wofür reserviert wird (z. B. Auftrag oder Anlage).")
        with db.schreiben() as con:
            aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == artikel_nr.strip())).scalar()
            if not aid:
                raise BuchungsFehler(f"Artikel {artikel_nr} gibt es nicht.")
            L = lager(con, request)
            frei = L.gesamt(aid) - L.reserviert(aid)
            con.execute(insert(reservierungen).values(artikel_id=aid, menge=m, fuer=fuer.strip(), person=person.strip() or None, bis=_d(bis),
                                                      status="offen", erstellt_von=request.session["user"]["username"]))
            audit(con, request.session["user"]["username"], "Reservierung", artikel_nr, {"menge": m, "fuer": fuer})
        flash(request, f"{fmt_num(m)} × {artikel_nr} reserviert für {fuer.strip()}." + (f" Achtung: nur {fmt_num(frei)} frei verfügbar." if frei < m else ""),
              "ok" if frei >= m else "fehler")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(weiter, status_code=303)


@router.post("/reservierungen/{rid}/status")
def reservierung_status(request: Request, rid: int, status: str = Form(...)):
    require(request, "lager")
    if status in ("storniert", "entnommen"):
        with db.schreiben() as con:
            con.execute(update(reservierungen).where(reservierungen.c.id == rid).values(status=status))
            audit(con, request.session["user"]["username"], f"Reservierung {status}", str(rid))
        flash(request, "Reservierung aktualisiert.")
    return RedirectResponse(zurueck(request, "/reservierungen"), status_code=303)
