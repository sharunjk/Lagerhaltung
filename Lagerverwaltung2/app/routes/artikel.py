from __future__ import annotations

import csv
import io
import mimetypes
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, insert, select

from .. import db
from ..db import anhaenge, artikel, lieferanten
from ..services import labels, queries
from ..services.excel import tabelle_xlsx
from ..services.lager import BuchungsFehler, Lager, audit, fmt_num, parse_num
from ..web import flash, render, require

router = APIRouter()

TEXT_FELDER = ["bezeichnung", "typ", "kategorie", "hersteller", "hersteller_nr", "lieferant_artnr", "einheit", "verwendung", "notiz"]
ZAHL_FELDER = ["preis", "meldebestand", "mindestbestand", "bestellmenge"]


def lager(con, request, quelle: str = "pc") -> Lager:
    cfg = request.app.state.cfg
    return Lager(con, request.session["user"]["username"], quelle, cfg.lager.negative_bestaende_erlauben,
                 cfg.lager.lagerplaetze_automatisch_anlegen)


def form_daten(form: dict, cfg) -> dict:
    d = {f: ((form.get(f) or "").strip() or None) for f in TEXT_FELDER}
    d["einheit"] = d["einheit"] or cfg.lager.standard_einheit
    for f in ZAHL_FELDER:
        v = (form.get(f) or "").strip()
        p = parse_num(v) if v else None
        if v and (p is None or p < 0):
            raise BuchungsFehler(f"„{v}“ ist keine gültige Zahl.")
        d[f] = p
    lid = form.get("lieferant_id") or ""
    d["lieferant_id"] = int(lid) if str(lid).isdigit() else None
    d["kritisch"] = form.get("kritisch") in ("on", "1", "ja", "true", True)
    if "nummer" in form:
        d["nummer"] = (form.get("nummer") or "").strip()
    return d


def _form_ctx(con):
    return dict(lieferanten=[dict(r) for r in con.execute(select(lieferanten).order_by(lieferanten.c.name)).mappings()],
                vs=queries.vorschlaege(con))


@router.get("/artikel")
def liste(request: Request, q: str = "", filter: str = "", kategorie: str = "", platz: str = "", sort: str = "nr", seite: int = 1, archiv: int = 0):
    require(request)
    with db.engine().connect() as con:
        arts = queries.artikel_liste(con, q, filter, kategorie, platz, sort, archiv=bool(archiv))
        kats = queries.vorschlaege(con)["kategorien"]
    pro = 100
    gesamt = len(arts)
    seiten = max(1, (gesamt - 1) // pro + 1)
    seite = max(1, min(seite, seiten))
    spalten = request.session.get("spalten2") or ["orte", "kategorie", "lieferant", "status"]
    tpl = "partials/artikel_tabelle.html" if request.headers.get("hx-request") else "artikel_liste.html"
    return render(request, tpl, arts=arts[(seite - 1) * pro: seite * pro], gesamt=gesamt, seite=seite, seiten=seiten, q=q, filter=filter,
                  kategorie=kategorie, platz=platz, sort=sort, spalten=spalten, kategorien=kats, archiv=archiv)


@router.post("/artikel/spalten")
async def spalten(request: Request):
    require(request)
    request.session["spalten2"] = (await request.form()).getlist("spalten")
    return RedirectResponse(request.headers.get("referer") or "/artikel", status_code=303)


@router.get("/artikel/export.{fmt}")
def export(request: Request, fmt: str, q: str = "", filter: str = "", kategorie: str = "", platz: str = ""):
    require(request)
    with db.engine().connect() as con:
        arts = queries.artikel_liste(con, q, filter, kategorie, platz)
    kopf = ["Artikelnummer", "Bezeichnung", "Typenbezeichnung", "Gruppe", "Bestand", "Reserviert", "Einheit", "Lagerplätze", "Meldebestand",
            "Mindestbestand", "Status", "Lieferant", "Lieferanten-Art.-Nr.", "Hersteller", "Hersteller-Nr.", "Preis", "Kritisch", "Verwendung", "Notiz"]
    z = [[a["nummer"], a["bezeichnung"], a["typ"], a["kategorie"], a["bestand"], a["reserviert"], a["einheit"],
          ", ".join(f"{o} ({fmt_num(n)})" for o, n in a["orte"]), a["meldebestand"], a["mindestbestand"],
          {"ok": "OK", "melden": "Nachbestellen", "kritisch": "Kritisch"}[a["status"]], a["lieferant"], a["lieferant_artnr"],
          a["hersteller"], a["hersteller_nr"], a["preis"], "ja" if a["kritisch"] else "", a["verwendung"], a["notiz"]] for a in arts]
    name = f"Artikel_{date.today():%Y-%m-%d}"
    if fmt == "xlsx":
        return Response(tabelle_xlsx("Artikel", kopf, z), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(kopf)
    for r in z:
        w.writerow(["" if v is None else (fmt_num(v) if isinstance(v, float) else v) for v in r])
    return Response(buf.getvalue().encode("cp1252", errors="replace"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/artikel/neu")
def neu_form(request: Request, kopie: str = ""):
    require(request, "lager")
    with db.engine().connect() as con:
        a = {"nummer": queries.naechste_nummer(con), "einheit": request.app.state.cfg.lager.standard_einheit}
        if kopie and (src := queries.artikel_detail(con, kopie)):
            a = {**src, "nummer": a["nummer"]}
        return render(request, "artikel_form.html", a=a, neu=True, **_form_ctx(con))


@router.post("/artikel/neu")
async def neu(request: Request):
    require(request, "lager")
    form = dict(await request.form())
    try:
        with db.schreiben() as con:
            daten = form_daten(form, request.app.state.cfg)
            a = lager(con, request).artikel_anlegen(daten, form.get("platz", ""), form.get("anfangsbestand") or 0)
    except BuchungsFehler as e:
        with db.engine().connect() as con:
            return render(request, "artikel_form.html", a=form, neu=True, fehler=str(e), **_form_ctx(con))
    flash(request, f"Artikel {a['nummer']} angelegt.")
    return RedirectResponse(f"/artikel/{a['nummer']}" + ("?etikett=1" if form.get("etikett") == "on" else ""), status_code=303)


@router.get("/artikel/{nr}")
def detail(request: Request, nr: str, etikett: int = 0):
    require(request)
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, nr)
        if not a:
            return render(request, "fehler.html", titel="Artikel nicht gefunden", text=f"Artikel {nr} gibt es nicht.")
        hist, total = queries.bewegungen_liste(con, artikel_id=a["id"], limit=50)
        verlauf = queries.bestandsverlauf(con, a["id"], a["bestand"])
    d = request.app.state.cfg.drucker
    return render(request, "artikel_detail.html", a=a, hist=hist, hist_total=total, verlauf=verlauf, zeige_etikett=etikett,
                  etikett_svg=labels.etikett_svg(a["nummer"], a["nummer"], a["bezeichnung"], d.standard_format, d.barcode, scale=1.6))


@router.get("/artikel/{nr}/bearbeiten")
def bearbeiten_form(request: Request, nr: str):
    require(request, "lager")
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, nr)
        if not a:
            return RedirectResponse("/artikel", status_code=303)
        return render(request, "artikel_form.html", a=a, neu=False, **_form_ctx(con))


@router.post("/artikel/{nr}/bearbeiten")
async def bearbeiten(request: Request, nr: str):
    require(request, "lager")
    form = dict(await request.form())
    try:
        with db.schreiben() as con:
            aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar()
            daten = form_daten(form, request.app.state.cfg)
            if not daten.get("bezeichnung"):
                raise BuchungsFehler("Bitte eine Bezeichnung angeben.")
            lager(con, request).artikel_aendern(aid, daten)
    except BuchungsFehler as e:
        with db.engine().connect() as con:
            return render(request, "artikel_form.html", a={**form, "nummer": form.get("nummer") or nr, "_alt": nr}, neu=False, fehler=str(e), **_form_ctx(con))
    flash(request, "Änderungen gespeichert.")
    return RedirectResponse(f"/artikel/{daten.get('nummer') or nr}", status_code=303)


@router.post("/artikel/{nr}/archivieren")
def archivieren(request: Request, nr: str, zurueck: int = Form(0)):
    require(request, "admin")
    try:
        with db.schreiben() as con:
            aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar()
            lager(con, request).artikel_archivieren(aid, archiv=not zurueck)
        flash(request, f"Artikel {nr} " + ("wieder aktiviert." if zurueck else "archiviert. Er bleibt in der Historie sichtbar."))
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(f"/artikel/{nr}", status_code=303)


# ------------------------------------------------------------------ Anhänge
def _anhang_ordner(request) -> Path:
    p = request.app.state.cfg.path(request.app.state.cfg.daten.anhaenge)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/artikel/{nr}/anhang")
async def anhang_hochladen(request: Request, nr: str, datei: UploadFile = File(...)):
    require(request, "lager")
    inhalt = await datei.read()
    weiter = request.query_params.get("weiter") or f"/artikel/{nr}#anhaenge"
    if not inhalt or len(inhalt) > 25 * 1024 * 1024:
        flash(request, "Datei ist leer oder größer als 25 MB.", "fehler")
        return RedirectResponse(weiter, status_code=303)
    endung = Path(datei.filename or "").suffix.lower()[:10]
    speicher = f"{uuid.uuid4().hex}{endung}"
    (_anhang_ordner(request) / speicher).write_bytes(inhalt)
    typ = datei.content_type or mimetypes.guess_type(datei.filename or "")[0] or "application/octet-stream"
    with db.schreiben() as con:
        aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar()
        con.execute(insert(anhaenge).values(artikel_id=aid, dateiname=Path(datei.filename or "datei").name, speichername=speicher, typ=typ,
                                            groesse=len(inhalt), ist_bild=typ.startswith("image/"), hochgeladen_von=request.session["user"]["username"]))
        audit(con, request.session["user"]["username"], "Anhang hochgeladen", nr, {"datei": datei.filename})
    flash(request, "Datei gespeichert.")
    return RedirectResponse(weiter, status_code=303)


@router.get("/anhang/{aid}")
def anhang(request: Request, aid: int, download: int = 0):
    require(request)
    with db.engine().connect() as con:
        a = con.execute(select(anhaenge).where(anhaenge.c.id == aid)).mappings().first()
    if not a:
        return Response(status_code=404)
    return FileResponse(_anhang_ordner(request) / a["speichername"], media_type=a["typ"], filename=a["dateiname"],
                        content_disposition_type="attachment" if download else "inline")


@router.post("/anhang/{aid}/loeschen")
def anhang_loeschen(request: Request, aid: int):
    require(request, "lager")
    with db.schreiben() as con:
        a = con.execute(select(anhaenge, artikel.c.nummer).join(artikel, artikel.c.id == anhaenge.c.artikel_id).where(anhaenge.c.id == aid)).mappings().first()
        if a:
            con.execute(delete(anhaenge).where(anhaenge.c.id == aid))
            (_anhang_ordner(request) / a["speichername"]).unlink(missing_ok=True)
            audit(con, request.session["user"]["username"], "Anhang gelöscht", a["nummer"], {"datei": a["dateiname"]})
    flash(request, "Anhang gelöscht.")
    return RedirectResponse(f"/artikel/{a['nummer']}#anhaenge" if a else "/artikel", status_code=303)


# ------------------------------------------------------------------ Etiketten
@router.get("/etikett/vorschau", response_class=HTMLResponse)
def etikett_vorschau(request: Request, code: str, z1: str = "", z2: str = "", format: str = "", barcode: str = ""):
    require(request)
    d = request.app.state.cfg.drucker
    return HTMLResponse(labels.etikett_svg(code, z1, z2, format or d.standard_format, barcode or d.barcode, scale=1.6))


def etiketten_drucken(request, eintraege: list[tuple[str, str, str, int]], format_: str | None = None) -> str:
    cfg = request.app.state.cfg
    d = cfg.drucker
    daten = b"".join(labels.etikett_tspl(c, z1, z2, format_ or d.standard_format, d.barcode, n, d.versatz_x_mm, d.versatz_y_mm,
                                         d.dichte, d.geschwindigkeit, d.luecke_mm) for c, z1, z2, n in eintraege)
    return labels.senden(d, daten, cfg.path)


@router.post("/artikel/{nr}/etikett")
def etikett_drucken(request: Request, nr: str, anzahl: int = Form(1), format: str = Form("")):
    require(request, "lager")
    with db.engine().connect() as con:
        bez = con.execute(select(artikel.c.bezeichnung).where(artikel.c.nummer == nr)).scalar() or ""
    try:
        flash(request, etiketten_drucken(request, [(nr, nr, bez, max(1, min(anzahl, 99)))], format or None))
    except labels.DruckFehler as e:
        flash(request, f"Druck fehlgeschlagen: {e}", "fehler")
    return RedirectResponse(request.query_params.get("weiter") or f"/artikel/{nr}", status_code=303)


@router.post("/etiketten/sammeldruck")
async def sammeldruck(request: Request):
    require(request, "lager")
    form = await request.form()
    nrs = form.getlist("nr")
    if not nrs:
        flash(request, "Keine Artikel ausgewählt.", "fehler")
        return RedirectResponse(request.headers.get("referer") or "/artikel", status_code=303)
    if form.get("ziel") == "browser":
        return RedirectResponse("/etiketten/druckansicht?" + "&".join(f"nr={n}" for n in nrs), status_code=303)
    with db.engine().connect() as con:
        bez = dict(con.execute(select(artikel.c.nummer, artikel.c.bezeichnung).where(artikel.c.nummer.in_(nrs))).all())
    try:
        flash(request, f"{len(nrs)} Etiketten: " + etiketten_drucken(request, [(n, n, bez.get(n, ""), 1) for n in nrs], form.get("format") or None))
    except labels.DruckFehler as e:
        flash(request, f"Druck fehlgeschlagen: {e}", "fehler")
    return RedirectResponse(request.headers.get("referer") or "/artikel", status_code=303)


@router.get("/etiketten/druckansicht")
def druckansicht(request: Request, format: str = ""):
    """Druck über den Windows-Druckertreiber (Browser-Druck), falls Direktdruck nicht geht."""
    require(request)
    nrs = request.query_params.getlist("nr")
    plaetze = request.query_params.getlist("platz")
    d = request.app.state.cfg.drucker
    fmt = format or d.standard_format
    with db.engine().connect() as con:
        bez = dict(con.execute(select(artikel.c.nummer, artikel.c.bezeichnung).where(artikel.c.nummer.in_(nrs))).all()) if nrs else {}
    svgs = [labels.etikett_svg(n, n, bez.get(n, ""), fmt, d.barcode) for n in nrs]
    svgs += [labels.etikett_svg(p, p, "Lagerplatz", fmt, d.barcode) for p in plaetze]
    L = labels.LAYOUTS[fmt]
    return render(request, "druckansicht.html", svgs=svgs, breite=L.breite, hoehe=L.hoehe)
