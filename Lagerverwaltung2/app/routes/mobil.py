"""Scanner-App für Handhelds (Zebra TC21) und Smartphones (/m).

Läuft im Browser und lässt sich als App installieren (PWA). Buchungen gehen sofort an den Server;
ohne Verbindung werden sie im Gerät gespeichert und über /m/sync nachgereicht.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import and_, func, insert, select, update

from .. import db
from ..db import artikel, bestand, bestellungen, inventuren, lagerplaetze, lieferanten, reservierungen, sync_log
from ..services import queries
from ..services.lager import BuchungsFehler, audit, fmt_num, parse_num
from ..web import current_user, flash, render, require, templates
from .artikel import etiketten_drucken, form_daten, lager
from .buchen import TYPEN, buchung_ausfuehren
from .lager import inventur_positionen, zaehlung_speichern

router = APIRouter(prefix="/m")
RUECKGAENGIG_MINUTEN = 10


def _merken(request: Request, typ: str, ids: list[int], msg: str) -> None:
    request.session["letzte"] = {"typ": typ, "ids": ids, "zeit": datetime.now().isoformat(), "text": msg}


def _letzte(request: Request) -> dict | None:
    l = request.session.get("letzte")
    if not l:
        return None
    if datetime.now() - datetime.fromisoformat(l["zeit"]) > timedelta(minutes=RUECKGAENGIG_MINUTEN):
        return None
    return l


# ------------------------------------------------------------------ App-Hülle (PWA)
@router.get("/manifest.webmanifest")
def manifest(request: Request):
    firma = request.app.state.cfg.server.firmenname
    return JSONResponse({
        "name": f"Lager {firma}", "short_name": "Lager", "id": "/m", "start_url": "/m", "scope": "/m",
        "display": "standalone", "orientation": "portrait", "background_color": "#EEF1F3", "theme_color": "#1C2A38",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        "shortcuts": [{"name": "Entnahme", "url": "/m/buchen?typ=ausgang"}, {"name": "Eingang", "url": "/m/buchen?typ=eingang"},
                      {"name": "Offline erfassen", "url": "/m/offline"}],
    }, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker(request: Request):
    body = templates.get_template("m/sw.js").render(version=request.app.state.version)
    return Response(body, media_type="application/javascript", headers={"Service-Worker-Allowed": "/m", "Cache-Control": "no-cache"})


@router.get("/ping")
def ping(request: Request):
    return {"ok": True, "angemeldet": bool(current_user(request))}


# ------------------------------------------------------------------ Start
@router.get("")
def start(request: Request):
    require(request)
    with db.engine().connect() as con:
        letzte, _ = queries.bewegungen_liste(con, benutzer=request.session["user"]["username"], limit=6)
        inv = con.execute(select(inventuren).where(inventuren.c.status == "offen").order_by(inventuren.c.id.desc())).mappings().all()
        ausl = len(queries.offene_ausleihen(con))
        res = con.execute(select(func.count()).where(reservierungen.c.status == "offen")).scalar()
        best = con.execute(select(func.count()).where(bestellungen.c.status.in_(["bestellt", "teilgeliefert"]))).scalar()
    return render(request, "m/start.html", letzte=letzte, inventuren=inv, ausleihen=ausl, reserviert=res, bestellt=best,
                  korb=len(request.session.get("korb", [])))


# ------------------------------------------------------------------ Buchen
@router.get("/buchen")
def buchen(request: Request, typ: str = "ausgang", artikel: str = "", platz: str = "", reservierung: str = ""):
    require(request)
    typ = typ if typ in TYPEN else "ausgang"
    a = res = None
    with db.engine().connect() as con:
        if artikel.strip():
            a = queries.artikel_detail(con, artikel.strip())
        if reservierung.isdigit():
            res = con.execute(select(reservierungen).where(reservierungen.c.id == int(reservierung))).mappings().first()
        vs = queries.vorschlaege(con)
    return render(request, "m/buchen.html", typ=typ, a=a, artikel=artikel, platz=platz, vs=vs, TYPEN=TYPEN, res=res,
                  nicht_gefunden=bool(artikel.strip() and not a), letzte=_letzte(request))


@router.post("/buchen")
async def buchen_post(request: Request):
    require(request, "lager")
    f = dict(await request.form())
    nr, typ = (f.get("artikel") or "").strip(), f.get("typ", "")
    try:
        with db.schreiben() as con:
            L = lager(con, request, "mobil")
            msg = buchung_ausfuehren(L, typ, nr, f.get("menge", ""), f.get("lagerort", ""), f.get("ziel", ""), f.get("empfaenger", ""),
                                     f.get("kostenstelle", ""), f.get("zweck", ""), f.get("rueckgabe_bis", ""), f.get("reservierung_id", ""))
            ids = list(L.ids)
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/m/buchen?typ={typ}&artikel={quote(nr)}&platz={quote(f.get('lagerort', ''))}", status_code=303)
    _merken(request, typ, ids, msg)
    flash(request, msg)
    return RedirectResponse(f"/m/buchen?typ={typ}", status_code=303)


@router.post("/rueckgaengig")
def rueckgaengig(request: Request):
    """Letzte eigene Buchung (max. 10 Minuten alt) zurücknehmen."""
    require(request, "lager")
    l = _letzte(request)
    if not l:
        flash(request, "Es gibt keine Buchung, die noch rückgängig gemacht werden kann.", "fehler")
        return RedirectResponse("/m", status_code=303)
    from ..db import bewegungen
    try:
        with db.schreiben() as con:
            L = lager(con, request, "mobil")
            rows = [dict(r) for r in con.execute(select(bewegungen).where(bewegungen.c.id.in_(l["ids"]))).mappings()]
            for r in rows:
                if r["storniert_durch"]:
                    raise BuchungsFehler("Diese Buchung wurde schon zurückgenommen.")
            for r in rows:
                nr = r["artikel_nr"]
                if r["typ"] in ("eingang", "ausgang"):
                    L.storno(r["id"])
                elif r["typ"] == "umbuchung" and r["menge"] > 0:
                    L.umbuchung(nr, r["lagerplatz"], r["text"].split("von ", 1)[1].split(";")[0], r["menge"])
                elif r["typ"] == "inventur":
                    L.inventur(nr, r["lagerplatz"], (r["bestand_nachher"] or 0) - (r["menge"] or 0))
                elif r["typ"] == "ausleihe":
                    L.rueckgabe(r["id"])
            for r in rows:
                con.execute(update(bewegungen).where(bewegungen.c.id == r["id"]).values(storniert_durch=L.ids[-1] if L.ids else None))
            audit(con, request.session["user"]["username"], "Rückgängig (Handheld)", ",".join(str(i) for i in l["ids"]))
    except (BuchungsFehler, IndexError, AttributeError) as e:
        flash(request, f"Rückgängig nicht möglich: {e}", "fehler")
        return RedirectResponse(f"/m/buchen?typ={l['typ']}", status_code=303)
    request.session.pop("letzte", None)
    flash(request, f"Zurückgenommen: {l['text']}")
    return RedirectResponse(f"/m/buchen?typ={l['typ']}", status_code=303)


# ------------------------------------------------------------------ Artikel / Platz / Suche
@router.get("/artikel/{nr}")
def artikel_info(request: Request, nr: str):
    require(request)
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, nr)
        hist, _ = queries.bewegungen_liste(con, artikel_id=a["id"], limit=8) if a else ([], 0)
    if not a:
        return RedirectResponse(f"/m/suche?q={quote(nr)}&neu=1", status_code=303)
    return render(request, "m/artikel.html", a=a, hist=hist)


@router.post("/artikel/{nr}/werte")
async def artikel_werte(request: Request, nr: str):
    """Melde-/Mindestbestand, Bestellmenge, kritisch und Verwendung direkt am Regal pflegen."""
    require(request, "lager")
    f = dict(await request.form())
    try:
        werte = {}
        for k in ("meldebestand", "mindestbestand", "bestellmenge"):
            v = (f.get(k) or "").strip()
            p = parse_num(v) if v else None
            if v and (p is None or p < 0):
                raise BuchungsFehler(f"„{v}“ ist keine gültige Zahl.")
            werte[k] = p
        werte["kritisch"] = f.get("kritisch") == "on"
        werte["verwendung"] = (f.get("verwendung") or "").strip() or None
        with db.schreiben() as con:
            aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar()
            lager(con, request, "mobil").artikel_aendern(aid, werte)
        flash(request, "Artikeldaten gespeichert.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(f"/m/artikel/{quote(nr)}", status_code=303)


@router.post("/artikel/{nr}/etikett")
def artikel_etikett(request: Request, nr: str, anzahl: int = Form(1)):
    require(request, "lager")
    with db.engine().connect() as con:
        bez = con.execute(select(artikel.c.bezeichnung).where(artikel.c.nummer == nr)).scalar() or ""
    from ..services import labels
    try:
        flash(request, etiketten_drucken(request, [(nr, nr, bez, max(1, min(anzahl, 50)))]))
    except labels.DruckFehler as e:
        flash(request, f"Druck fehlgeschlagen: {e}", "fehler")
    return RedirectResponse(f"/m/artikel/{quote(nr)}", status_code=303)


@router.get("/platz")
def platz(request: Request, code: str):
    require(request)
    with db.engine().connect() as con:
        p, rows = queries.platz_inhalt(con, code)
    if not p:
        flash(request, f"Lagerplatz {code} nicht gefunden.", "fehler")
        return RedirectResponse("/m", status_code=303)
    return render(request, "m/platz.html", p=p, rows=rows)


@router.post("/platz/etikett")
def platz_etikett(request: Request, code: str = Form(...)):
    require(request, "lager")
    from ..services import labels
    try:
        flash(request, etiketten_drucken(request, [(code, code, "Lagerplatz", 1)]))
    except labels.DruckFehler as e:
        flash(request, f"Druck fehlgeschlagen: {e}", "fehler")
    return RedirectResponse(f"/m/platz?code={quote(code)}", status_code=303)


@router.get("/suche")
def suche(request: Request, q: str = "", neu: int = 0):
    require(request)
    with db.engine().connect() as con:
        treffer = queries.artikel_liste(con, q=q)[:40] if len(q.strip()) >= 2 else []
    return render(request, "m/suche.html", q=q, treffer=treffer, neu=neu)


# ------------------------------------------------------------------ Neuer Artikel
@router.get("/neu")
def neu_form(request: Request, nummer: str = "", platz: str = ""):
    require(request, "lager")
    with db.engine().connect() as con:
        vs = queries.vorschlaege(con)
        lief = [r[0] for r in con.execute(select(lieferanten.c.name).order_by(lieferanten.c.name))]
        vorschlag = queries.naechste_nummer(con)
    return render(request, "m/neu.html", nummer=nummer or vorschlag, platz=platz, vs=vs, lieferanten=lief)


@router.post("/neu")
async def neu(request: Request):
    require(request, "lager")
    f = dict(await request.form())
    try:
        with db.schreiben() as con:
            daten = form_daten({**f, "nummer": f.get("nummer", "")}, request.app.state.cfg)
            lname = (f.get("lieferant") or "").strip()
            if lname:
                lid = con.execute(select(lieferanten.c.id).where(func.lower(lieferanten.c.name) == lname.lower())).scalar()
                daten["lieferant_id"] = lid or con.execute(insert(lieferanten).values(name=lname)).inserted_primary_key[0]
            a = lager(con, request, "mobil").artikel_anlegen(daten, f.get("platz", ""), f.get("anfangsbestand") or 0)
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/m/neu?nummer={quote(f.get('nummer', ''))}&platz={quote(f.get('platz', ''))}", status_code=303)
    msg = f"Artikel {a['nummer']} angelegt."
    if f.get("etikett") == "on":
        from ..services import labels
        try:
            msg += " " + etiketten_drucken(request, [(a["nummer"], a["nummer"], a["bezeichnung"], 1)])
        except labels.DruckFehler as e:
            msg += f" Etikett nicht gedruckt: {e}"
    flash(request, msg)
    return RedirectResponse(f"/m/artikel/{quote(a['nummer'])}", status_code=303)


# ------------------------------------------------------------------ Sammelentnahme (Korb)
@router.get("/korb")
def korb(request: Request, artikel: str = ""):
    require(request)
    a = None
    with db.engine().connect() as con:
        if artikel.strip():
            a = queries.artikel_detail(con, artikel.strip())
        vs = queries.vorschlaege(con)
    return render(request, "m/korb.html", korb=request.session.get("korb", []), a=a, artikel=artikel, vs=vs,
                  nicht_gefunden=bool(artikel.strip() and not a))


@router.post("/korb/neu")
def korb_neu(request: Request, nr: str = Form(..., alias="artikel"), lagerort: str = Form(...), menge: str = Form("1")):
    require(request, "lager")
    m = parse_num(menge)
    with db.engine().connect() as con:
        a = con.execute(select(artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit).where(artikel.c.nummer == nr.strip())).mappings().first()
    if not a or not m or m <= 0 or not lagerort.strip():
        flash(request, "Artikel, Lagerplatz und Menge prüfen.", "fehler")
        return RedirectResponse(f"/m/korb?artikel={quote(nr)}", status_code=303)
    k = request.session.get("korb", [])
    k.append({"nr": a["nummer"], "bez": a["bezeichnung"], "einheit": a["einheit"], "platz": " ".join(lagerort.split()), "menge": m})
    request.session["korb"] = k
    flash(request, f"{fmt_num(m)} × {a['nummer']} in die Liste übernommen.")
    return RedirectResponse("/m/korb", status_code=303)


@router.post("/korb/entfernen/{i}")
def korb_entfernen(request: Request, i: int):
    require(request)
    k = request.session.get("korb", [])
    if 0 <= i < len(k):
        k.pop(i)
    request.session["korb"] = k
    return RedirectResponse("/m/korb", status_code=303)


@router.post("/korb/buchen")
def korb_buchen(request: Request, empfaenger: str = Form(""), kostenstelle: str = Form(""), zweck: str = Form("")):
    require(request, "lager")
    k = request.session.get("korb", [])
    if not k:
        return RedirectResponse("/m/korb", status_code=303)
    try:
        with db.schreiben() as con:
            L = lager(con, request, "mobil")
            for pos in k:
                L.ausgang(pos["nr"], pos["platz"], pos["menge"], empfaenger=empfaenger, kostenstelle=kostenstelle, zweck=zweck)
            ids = list(L.ids)
    except BuchungsFehler as e:
        flash(request, f"Nichts gebucht: {e}", "fehler")
        return RedirectResponse("/m/korb", status_code=303)
    msg = f"Sammelentnahme: {len(k)} Positionen gebucht."
    _merken(request, "ausgang", ids, msg)
    request.session["korb"] = []
    flash(request, msg)
    return RedirectResponse("/m/korb", status_code=303)


# ------------------------------------------------------------------ Reservierungen, Wareneingang, Rückgabe
@router.get("/reservierungen")
def reservierungen_liste(request: Request):
    require(request)
    with db.engine().connect() as con:
        rows = [dict(r) for r in con.execute(select(reservierungen, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit)
                                             .join(artikel, artikel.c.id == reservierungen.c.artikel_id)
                                             .where(reservierungen.c.status == "offen").order_by(reservierungen.c.bis.is_(None), reservierungen.c.bis)).mappings()]
        orte = queries.orte_je_artikel(con)
    for r in rows:
        r["orte"] = [o for o in orte.get(r["artikel_id"], []) if o[1] > 0]
    return render(request, "m/reservierungen.html", rows=rows)


@router.get("/wareneingang")
def wareneingang(request: Request):
    require(request)
    with db.engine().connect() as con:
        rows = [dict(r) for r in con.execute(
            select(bestellungen, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, lieferanten.c.name.label("lieferant"))
            .select_from(bestellungen.join(artikel, artikel.c.id == bestellungen.c.artikel_id).outerjoin(lieferanten, lieferanten.c.id == bestellungen.c.lieferant_id))
            .where(bestellungen.c.status.in_(["bestellt", "teilgeliefert", "offen"])).order_by(lieferanten.c.name, bestellungen.c.id)).mappings()]
        haupt = {}
        for aid, code in con.execute(select(bestand.c.artikel_id, lagerplaetze.c.code).join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id).order_by(bestand.c.menge)):
            haupt[aid] = code
        vs = queries.vorschlaege(con)
    return render(request, "m/wareneingang.html", rows=rows, haupt=haupt, vs=vs)


@router.get("/rueckgabe")
def rueckgabe(request: Request):
    require(request)
    with db.engine().connect() as con:
        rows = queries.offene_ausleihen(con)
    return render(request, "m/rueckgabe.html", rows=rows)


@router.post("/rueckgabe/{bid}")
def rueckgabe_post(request: Request, bid: int, menge: str = Form(""), platz: str = Form("")):
    require(request, "lager")
    try:
        with db.schreiben() as con:
            e = lager(con, request, "mobil").rueckgabe(bid, menge or None, platz or None)
        flash(request, f"Zurückgebucht: {e.artikel_nr} auf {e.platz}")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse("/m/rueckgabe", status_code=303)


# ------------------------------------------------------------------ Inventur
@router.get("/inventur/{iid}")
def inventur(request: Request, iid: int, platz: str = ""):
    require(request)
    with db.engine().connect() as con:
        inv = con.execute(select(inventuren).where(inventuren.c.id == iid)).mappings().first()
        if not inv:
            return RedirectResponse("/m", status_code=303)
        pos = inventur_positionen(con, iid, platz=platz.strip()) if platz.strip() else []
        offen = len(inventur_positionen(con, iid, nur_offen=True))
    return render(request, "m/inventur.html", inv=inv, pos=pos, platz=platz.strip(), offen=offen)


@router.post("/inventur/{iid}")
async def inventur_post(request: Request, iid: int):
    require(request, "lager")
    f = await request.form()
    platz = (f.get("platz") or "").strip()
    werte = {int(k[4:]): parse_num(v) for k, v in f.items() if k.startswith("ist_") and str(v).strip() != "" and parse_num(v) is not None}
    neu = None
    if (f.get("neu_artikel") or "").strip() and parse_num(f.get("neu_ist")) is not None:
        neu = (f["neu_artikel"].strip(), platz, parse_num(f["neu_ist"]))
    try:
        with db.schreiben() as con:
            n = zaehlung_speichern(con, iid, request.session["user"]["username"], werte, neu)
        flash(request, f"{n} Zählung(en) für {platz} gespeichert.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/m/inventur/{iid}?platz={quote(platz)}", status_code=303)
    return RedirectResponse(f"/m/inventur/{iid}", status_code=303)


# ------------------------------------------------------------------ Offline-Modus
@router.get("/offline")
def offline(request: Request):
    require(request)
    return render(request, "m/offline.html", TYPEN={k: v for k, v in TYPEN.items() if k != "ausleihe"})


@router.get("/katalog.json")
def katalog(request: Request):
    """Artikelstamm mit Beständen für die Offline-Erfassung (wird im Gerät zwischengespeichert)."""
    require(request)
    with db.engine().connect() as con:
        arts = queries.artikel_liste(con)
        orte = queries.orte_je_artikel(con)
        plaetze = queries.vorschlaege(con)["plaetze"]
    return {"stand": datetime.now().strftime("%d.%m.%Y %H:%M"), "plaetze": plaetze,
            "artikel": {a["nummer"]: {"b": a["bezeichnung"], "e": a["einheit"], "o": orte.get(a["id"], [])} for a in arts}}


@router.post("/sync")
async def sync(request: Request):
    """Nimmt offline erfasste Buchungen entgegen. Jede hat eine UUID; bereits übertragene werden übersprungen."""
    u = current_user(request)
    if not u:
        return JSONResponse({"fehler": "nicht angemeldet"}, status_code=401)
    if u["rolle"] == "lesen":
        return JSONResponse({"fehler": "keine Berechtigung"}, status_code=403)
    daten = await request.json()
    ergebnis = {}
    for it in daten.get("items", [])[:500]:
        uid = str(it.get("uuid") or "")[:64]
        if not uid:
            continue
        with db.engine().connect() as con:
            schon = con.execute(select(sync_log.c.meldung).where(sync_log.c.uuid == uid)).scalar()
        if schon is not None:
            ergebnis[uid] = {"ok": True, "meldung": schon, "doppelt": True}
            continue
        try:
            erfasst = datetime.fromisoformat(str(it.get("erfasst", "")).replace("Z", "+00:00")).astimezone().strftime("%d.%m. %H:%M")
        except ValueError:
            erfasst = "?"
        try:
            with db.schreiben() as con:
                if con.execute(select(sync_log.c.uuid).where(sync_log.c.uuid == uid)).first():
                    ergebnis[uid] = {"ok": True, "doppelt": True}
                    continue
                L = lager(con, request, "offline")
                L.hinweis = f"offline erfasst {erfasst}"
                msg = buchung_ausfuehren(L, it.get("typ", ""), str(it.get("artikel", "")).strip(), str(it.get("menge", "")), it.get("lagerort", ""),
                                         it.get("ziel", ""), it.get("empfaenger", ""), it.get("kostenstelle", ""), it.get("zweck", ""))
                con.execute(insert(sync_log).values(uuid=uid, benutzer=u["username"], erfasst_am=str(it.get("erfasst", ""))[:40], meldung=msg[:300]))
            ergebnis[uid] = {"ok": True, "meldung": msg}
        except BuchungsFehler as e:
            ergebnis[uid] = {"ok": False, "meldung": str(e)}
    return ergebnis
