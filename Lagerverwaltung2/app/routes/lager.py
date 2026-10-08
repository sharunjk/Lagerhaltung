from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import and_, delete, func, insert, select, update

from .. import db
from ..db import artikel, bestand, bestellungen, bewegungen, inventur_pos, inventuren, lagerplaetze, lieferanten
from ..services import labels, queries
from ..services.excel import tabelle_xlsx
from ..services.lager import BuchungsFehler, audit, fmt_num, parse_num
from ..web import flash, render, require
from .artikel import etiketten_drucken, lager

router = APIRouter()


# ------------------------------------------------------------------ Lagerplätze
@router.get("/lagerplaetze")
def lagerplaetze_liste(request: Request, q: str = "", leer: int = 0):
    require(request)
    with db.engine().connect() as con:
        orte = queries.lagerplaetze_uebersicht(con)
    if q:
        orte = [o for o in orte if q.lower() in o["code"].lower() or q.lower() in (o["beschreibung"] or "").lower()]
    if not leer:
        sichtbar = [o for o in orte if o["artikel"] or o["beschreibung"]]
    else:
        sichtbar = orte
    bereiche: dict[str, list] = {}
    for o in sichtbar:
        bereiche.setdefault(o["bereich"] or "Sonstige", []).append(o)
    return render(request, "lagerplaetze.html", bereiche=dict(sorted(bereiche.items(), key=lambda x: (x[0] == "Sonstige", x[0]))),
                  anzahl=len(orte), leere=len(orte) - len([o for o in orte if o["artikel"]]), q=q, leer=leer)


@router.get("/lagerplaetze/ansicht")
def lagerplatz(request: Request, code: str):
    require(request)
    with db.engine().connect() as con:
        p, rows = queries.platz_inhalt(con, code)
        alle = queries.vorschlaege(con)["plaetze"]
    if not p:
        return render(request, "fehler.html", titel="Lagerplatz nicht gefunden", text=f"Den Lagerplatz {code} gibt es nicht.")
    d = request.app.state.cfg.drucker
    return render(request, "lagerplatz.html", p=p, rows=rows, alle=alle,
                  svg=labels.etikett_svg(p["code"], p["code"], p["beschreibung"] or "Lagerplatz", d.standard_format, d.barcode, 1.6))


@router.post("/lagerplaetze/speichern")
def platz_speichern(request: Request, code: str = Form(...), bereich: str = Form(""), beschreibung: str = Form(""), alt: str = Form("")):
    require(request, "lager")
    code = " ".join(code.split())
    if not code or len(code) > 60:
        flash(request, "Ungültiger Lagerplatz-Code (1–60 Zeichen).", "fehler")
        return RedirectResponse("/lagerplaetze", status_code=303)
    with db.schreiben() as con:
        werte = dict(code=code, bereich=bereich.strip() or (code.split("-")[0] if "-" in code else None), beschreibung=beschreibung.strip() or None)
        vorhanden = con.execute(select(lagerplaetze.c.id).where(func.lower(lagerplaetze.c.code) == code.lower())).scalar()
        if alt:
            pid = con.execute(select(lagerplaetze.c.id).where(lagerplaetze.c.code == alt)).scalar()
            if vorhanden and vorhanden != pid:
                flash(request, f"Den Platz {code} gibt es schon. Zum Zusammenlegen „Zusammenführen“ verwenden.", "fehler")
                return RedirectResponse(f"/lagerplaetze/ansicht?code={alt}", status_code=303)
            con.execute(update(lagerplaetze).where(lagerplaetze.c.id == pid).values(**werte))
            if alt != code:
                con.execute(update(bewegungen).where(bewegungen.c.lagerplatz_id == pid).values(lagerplatz=code))
        elif vorhanden:
            con.execute(update(lagerplaetze).where(lagerplaetze.c.id == vorhanden).values(**werte))
        else:
            con.execute(insert(lagerplaetze).values(aktiv=True, **werte))
        audit(con, request.session["user"]["username"], "Lagerplatz gespeichert", code, {**werte, "alt": alt})
    flash(request, f"Lagerplatz {code} gespeichert.")
    return RedirectResponse(f"/lagerplaetze/ansicht?code={code}", status_code=303)


@router.post("/lagerplaetze/zusammenfuehren")
def zusammenfuehren(request: Request, von: str = Form(...), nach: str = Form(...)):
    """Alle Bestände eines Platzes (z. B. Tippfehler) per Umbuchung auf einen anderen Platz übertragen und alten Platz löschen."""
    require(request, "admin")
    n = 0
    try:
        with db.schreiben() as con:
            L = lager(con, request)
            pv = L.platz(von, anlegen=False)
            pn = L.platz(nach)
            if pv["id"] == pn["id"]:
                raise BuchungsFehler("Quell- und Zielplatz sind identisch.")
            for aid, menge in con.execute(select(bestand.c.artikel_id, bestand.c.menge).where(bestand.c.lagerplatz_id == pv["id"])).all():
                if menge > 0:
                    L.umbuchung(aid, pv["code"], pn["code"], menge)
                    n += 1
                elif L.menge_am_platz(aid, pn["id"]) is None:
                    con.execute(insert(bestand).values(artikel_id=aid, lagerplatz_id=pn["id"], menge=0))
            con.execute(delete(bestand).where(and_(bestand.c.lagerplatz_id == pv["id"], bestand.c.menge == 0)))
            rest = con.execute(select(func.count()).select_from(bestand).where(bestand.c.lagerplatz_id == pv["id"])).scalar()
            if not rest:
                con.execute(update(lagerplaetze).where(lagerplaetze.c.id == pv["id"]).values(aktiv=False))
            audit(con, request.session["user"]["username"], "Lagerplatz zusammengeführt", von, {"nach": nach, "artikel": n})
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/lagerplaetze/ansicht?code={von}", status_code=303)
    flash(request, f"{n} Artikel von {von} nach {nach} umgebucht. {von} ist jetzt deaktiviert.")
    return RedirectResponse(f"/lagerplaetze/ansicht?code={nach}", status_code=303)


@router.post("/lagerplaetze/etikett")
async def platz_etikett(request: Request):
    require(request, "lager")
    f = await request.form()
    codes = f.getlist("code")
    try:
        flash(request, etiketten_drucken(request, [(c, c, f.get("text") or "Lagerplatz", max(1, min(int(f.get("anzahl") or 1), 99))) for c in codes]))
    except labels.DruckFehler as e:
        flash(request, f"Druck fehlgeschlagen: {e}", "fehler")
    return RedirectResponse(request.headers.get("referer") or "/lagerplaetze", status_code=303)


# ------------------------------------------------------------------ Nachbestellung / Bestellungen
@router.get("/nachbestellung")
def nachbestellung(request: Request):
    require(request)
    with db.engine().connect() as con:
        arts = queries.artikel_liste(con, filter_="melden", sort="status")
        offen = {a: float(m or 0) for a, m in con.execute(select(bestellungen.c.artikel_id, func.sum(bestellungen.c.menge - bestellungen.c.geliefert))
                                                          .where(bestellungen.c.status.in_(["offen", "bestellt", "teilgeliefert"])).group_by(bestellungen.c.artikel_id))}
        ohne_werte = con.execute(select(func.count()).select_from(artikel).where(and_(artikel.c.aktiv == True, artikel.c.meldebestand.is_(None),  # noqa: E712
                                                                                       artikel.c.mindestbestand.is_(None)))).scalar()
    for a in arts:
        a["offen"] = offen.get(a["id"], 0)
        ziel = max(a["meldebestand"] or 0, a["mindestbestand"] or 0)
        vorschlag = a["bestellmenge"] or max(1.0, ziel * 2 - a["bestand"])
        a["vorschlag"] = max(0.0, vorschlag - a["offen"])
    return render(request, "nachbestellung.html", arts=arts, ohne_werte=ohne_werte)


@router.post("/bestellungen/anlegen")
async def bestellungen_anlegen(request: Request):
    require(request, "lager")
    form = await request.form()
    n = 0
    with db.schreiben() as con:
        for aid in form.getlist("aid"):
            m = parse_num(form.get(f"menge_{aid}"))
            if not m or m <= 0:
                continue
            lid = con.execute(select(artikel.c.lieferant_id).where(artikel.c.id == int(aid))).scalar()
            con.execute(insert(bestellungen).values(artikel_id=int(aid), menge=m, geliefert=0, lieferant_id=lid, status="offen",
                                                    erstellt_von=request.session["user"]["username"]))
            n += 1
        audit(con, request.session["user"]["username"], "Bestellpositionen angelegt", str(n))
    flash(request, f"{n} Bestellposition(en) angelegt." if n else "Keine Position ausgewählt.", "ok" if n else "fehler")
    return RedirectResponse("/bestellungen", status_code=303)


@router.post("/bestellungen/einzeln")
def bestellung_einzeln(request: Request, artikel_nr: str = Form(...), menge: str = Form(...)):
    require(request, "lager")
    m = parse_num(menge)
    with db.schreiben() as con:
        a = con.execute(select(artikel.c.id, artikel.c.lieferant_id).where(artikel.c.nummer == artikel_nr)).first()
        if a and m and m > 0:
            con.execute(insert(bestellungen).values(artikel_id=a[0], menge=m, geliefert=0, lieferant_id=a[1], status="offen",
                                                    erstellt_von=request.session["user"]["username"]))
            flash(request, f"Bestellposition für {artikel_nr} angelegt.")
        else:
            flash(request, "Artikel oder Menge ungültig.", "fehler")
    return RedirectResponse(request.headers.get("referer") or "/bestellungen", status_code=303)


def _bestell_query(status: str = "aktiv", lieferant_id: int | None = None):
    b = bestellungen
    q = (select(b, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, artikel.c.lieferant_artnr, artikel.c.hersteller,
                artikel.c.hersteller_nr, artikel.c.preis, lieferanten.c.name.label("lieferant"))
         .select_from(b.join(artikel, artikel.c.id == b.c.artikel_id).outerjoin(lieferanten, lieferanten.c.id == b.c.lieferant_id)))
    if status == "aktiv":
        q = q.where(b.c.status.in_(["offen", "bestellt", "teilgeliefert"]))
    if lieferant_id:
        q = q.where(b.c.lieferant_id == lieferant_id)
    return q


@router.get("/bestellungen")
def bestellungen_liste(request: Request, status: str = "aktiv"):
    require(request)
    with db.engine().connect() as con:
        rows = [dict(r) for r in con.execute(_bestell_query(status).order_by(lieferanten.c.name, bestellungen.c.id.desc()).limit(500)).mappings()]
        haupt = {}
        for aid, code in con.execute(select(bestand.c.artikel_id, lagerplaetze.c.code).join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id)
                                     .order_by(bestand.c.menge)):
            haupt[aid] = code
        plaetze = queries.vorschlaege(con)["plaetze"]
    gruppen: dict[str, list] = {}
    for r in rows:
        gruppen.setdefault(r["lieferant"] or "Ohne Lieferant", []).append(r)
    return render(request, "bestellungen.html", gruppen=gruppen, status=status, haupt=haupt, plaetze=plaetze, anzahl=len(rows))


@router.post("/bestellungen/{bid}/status")
def bestellung_status(request: Request, bid: int, status: str = Form(...), bestellnummer: str = Form("")):
    require(request, "lager")
    if status in ("offen", "bestellt", "storniert"):
        werte = {"status": status}
        if status == "bestellt":
            werte["bestellt_am"] = datetime.now()
            if bestellnummer.strip():
                werte["bestellnummer"] = bestellnummer.strip()
        with db.schreiben() as con:
            con.execute(update(bestellungen).where(bestellungen.c.id == bid).values(**werte))
            audit(con, request.session["user"]["username"], f"Bestellung {status}", str(bid), werte)
        flash(request, "Bestellstatus aktualisiert.")
    return RedirectResponse("/bestellungen", status_code=303)


@router.post("/bestellungen/lieferant/{lid}/bestellt")
def lieferant_bestellt(request: Request, lid: int, bestellnummer: str = Form("")):
    require(request, "lager")
    with db.schreiben() as con:
        con.execute(update(bestellungen).where(and_(bestellungen.c.lieferant_id == lid, bestellungen.c.status == "offen"))
                    .values(status="bestellt", bestellt_am=datetime.now(), bestellnummer=bestellnummer.strip() or None))
    flash(request, "Alle offenen Positionen des Lieferanten als bestellt markiert.")
    return RedirectResponse("/bestellungen", status_code=303)


@router.post("/bestellungen/{bid}/wareneingang")
def wareneingang(request: Request, bid: int, menge: str = Form(...), lagerort: str = Form(...), weiter: str = Form("")):
    require(request, "lager")
    m = parse_num(menge)
    try:
        with db.schreiben() as con:
            best = con.execute(select(bestellungen, artikel.c.nummer).join(artikel, artikel.c.id == bestellungen.c.artikel_id)
                               .where(bestellungen.c.id == bid)).mappings().first()
            if not best:
                raise BuchungsFehler("Bestellung nicht gefunden.")
            lager(con, request, "mobil" if weiter.startswith("/m") else "pc").eingang(best["nummer"], lagerort, m, bestellung_id=bid,
                                        zweck=f"Wareneingang Bestellung {best['bestellnummer'] or bid}")
            geliefert = float(best["geliefert"] or 0) + m
            status = "geliefert" if geliefert >= float(best["menge"]) - 1e-9 else "teilgeliefert"
            con.execute(update(bestellungen).where(bestellungen.c.id == bid).values(geliefert=geliefert, status=status,
                                                                                    geliefert_am=datetime.now() if status == "geliefert" else None))
        flash(request, f"Wareneingang: {fmt_num(m)} × {best['nummer']} auf {lagerort}.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(weiter if weiter.startswith("/") else "/bestellungen", status_code=303)


@router.get("/bestellungen/export.xlsx")
def bestellungen_export(request: Request, lieferant: int = 0):
    require(request)
    with db.engine().connect() as con:
        rows = con.execute(_bestell_query("aktiv", lieferant or None).order_by(lieferanten.c.name, bestellungen.c.id)).mappings().all()
    kopf = ["Pos", "Lieferant", "Artikelnummer", "Bezeichnung", "Lieferanten-Art.-Nr.", "Hersteller", "Hersteller-Nr.", "Menge", "Einheit",
            "Geliefert", "Einzelpreis", "Gesamt", "Status", "Bestellnummer"]
    z = [[r["id"], r["lieferant"], r["nummer"], r["bezeichnung"], r["lieferant_artnr"], r["hersteller"], r["hersteller_nr"], r["menge"],
          r["einheit"], r["geliefert"], r["preis"], (r["preis"] or 0) * r["menge"] if r["preis"] else None, r["status"], r["bestellnummer"]] for r in rows]
    return Response(tabelle_xlsx("Bestellliste", kopf, z), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Bestellliste_{date.today():%Y-%m-%d}.xlsx"'})


# ------------------------------------------------------------------ Inventur
@router.get("/inventur")
def inventur_liste(request: Request):
    require(request)
    with db.engine().connect() as con:
        rows = con.execute(select(inventuren, func.count(inventur_pos.c.id).label("pos"), func.count(inventur_pos.c.ist).label("gezaehlt"))
                           .select_from(inventuren.outerjoin(inventur_pos, inventur_pos.c.inventur_id == inventuren.c.id))
                           .group_by(inventuren.c.id).order_by(inventuren.c.id.desc())).mappings().all()
        bereiche = [r[0] for r in con.execute(select(lagerplaetze.c.bereich).distinct().where(lagerplaetze.c.bereich.isnot(None)).order_by(lagerplaetze.c.bereich))]
    return render(request, "inventuren.html", rows=rows, bereiche=bereiche)


@router.post("/inventur/neu")
def inventur_neu(request: Request, name: str = Form(""), bereich: str = Form("")):
    require(request, "lager")
    with db.schreiben() as con:
        iid = con.execute(insert(inventuren).values(name=name.strip() or f"Inventur {date.today():%d.%m.%Y}" + (f" {bereich}" if bereich else ""),
                                                    bereich=bereich or None, status="offen", erstellt_von=request.session["user"]["username"])).inserted_primary_key[0]
        q = select(bestand.c.artikel_id, bestand.c.lagerplatz_id, bestand.c.menge).join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id)\
            .join(artikel, artikel.c.id == bestand.c.artikel_id).where(artikel.c.aktiv == True)  # noqa: E712
        if bereich:
            q = q.where(lagerplaetze.c.bereich == bereich)
        pos = [dict(inventur_id=iid, artikel_id=a, lagerplatz_id=p, soll=m) for a, p, m in con.execute(q)]
        if pos:
            con.execute(insert(inventur_pos), pos)
        audit(con, request.session["user"]["username"], "Inventur angelegt", str(iid), {"bereich": bereich, "positionen": len(pos)})
    flash(request, f"Inventur mit {len(pos)} Positionen angelegt.")
    return RedirectResponse(f"/inventur/{iid}", status_code=303)


def inventur_positionen(con, iid: int, nur_offen: bool = False, platz: str = ""):
    q = (select(inventur_pos, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, lagerplaetze.c.code, bestand.c.menge.label("aktuell"))
         .select_from(inventur_pos.join(artikel, artikel.c.id == inventur_pos.c.artikel_id)
                      .join(lagerplaetze, lagerplaetze.c.id == inventur_pos.c.lagerplatz_id)
                      .outerjoin(bestand, and_(bestand.c.artikel_id == inventur_pos.c.artikel_id, bestand.c.lagerplatz_id == inventur_pos.c.lagerplatz_id)))
         .where(inventur_pos.c.inventur_id == iid))
    if nur_offen:
        q = q.where(inventur_pos.c.ist.is_(None))
    if platz:
        q = q.where(lagerplaetze.c.code == platz)
    return [dict(r) for r in con.execute(q.order_by(lagerplaetze.c.code, artikel.c.nummer)).mappings()]


@router.get("/inventur/{iid}")
def inventur(request: Request, iid: int, nur_offen: int = 0):
    require(request)
    with db.engine().connect() as con:
        inv = con.execute(select(inventuren).where(inventuren.c.id == iid)).mappings().first()
        if not inv:
            return RedirectResponse("/inventur", status_code=303)
        pos = inventur_positionen(con, iid, bool(nur_offen))
    return render(request, "inventur.html", inv=inv, pos=pos, nur_offen=nur_offen)


def zaehlung_speichern(con, iid: int, user: str, werte: dict[int, float], neu: tuple[str, str, float] | None = None) -> int:
    inv = con.execute(select(inventuren).where(inventuren.c.id == iid)).mappings().first()
    if not inv or inv["status"] != "offen":
        raise BuchungsFehler("Diese Inventur ist abgeschlossen.")
    n = 0
    for pid, val in werte.items():
        con.execute(update(inventur_pos).where(and_(inventur_pos.c.id == pid, inventur_pos.c.inventur_id == iid))
                    .values(ist=val, gezaehlt_von=user, gezaehlt_am=datetime.now()))
        n += 1
    if neu:
        nr, code, ist = neu
        a = con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).scalar()
        if not a:
            raise BuchungsFehler(f"Artikel {nr} gibt es nicht.")
        from ..services.lager import Lager
        p = Lager(con, user).platz(code)
        vorhanden = con.execute(select(inventur_pos.c.id).where(and_(inventur_pos.c.inventur_id == iid, inventur_pos.c.artikel_id == a,
                                                                     inventur_pos.c.lagerplatz_id == p["id"]))).scalar()
        if vorhanden:
            con.execute(update(inventur_pos).where(inventur_pos.c.id == vorhanden).values(ist=ist, gezaehlt_von=user, gezaehlt_am=datetime.now()))
        else:
            con.execute(insert(inventur_pos).values(inventur_id=iid, artikel_id=a, lagerplatz_id=p["id"], soll=None, ist=ist,
                                                    gezaehlt_von=user, gezaehlt_am=datetime.now()))
        n += 1
    return n


@router.post("/inventur/{iid}/zaehlen")
async def inventur_zaehlen(request: Request, iid: int):
    require(request, "lager")
    form = await request.form()
    werte = {}
    for k, v in form.items():
        if k.startswith("ist_") and str(v).strip() != "":
            val = parse_num(v)
            if val is not None and val >= 0:
                werte[int(k[4:])] = val
    neu = None
    if (form.get("neu_artikel") or "").strip() and (form.get("neu_lagerort") or "").strip() and parse_num(form.get("neu_ist")) is not None:
        neu = (form["neu_artikel"].strip(), form["neu_lagerort"].strip(), parse_num(form["neu_ist"]))
    try:
        with db.schreiben() as con:
            n = zaehlung_speichern(con, iid, request.session["user"]["username"], werte, neu)
        flash(request, f"{n} Zählung(en) gespeichert.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(f"/inventur/{iid}", status_code=303)


@router.post("/inventur/{iid}/abschliessen")
def inventur_abschliessen(request: Request, iid: int):
    require(request, "admin")
    n = 0
    try:
        with db.schreiben() as con:
            inv = con.execute(select(inventuren).where(inventuren.c.id == iid)).mappings().first()
            if not inv or inv["status"] != "offen":
                raise BuchungsFehler("Inventur ist bereits abgeschlossen.")
            L = lager(con, request)
            for p in inventur_positionen(con, iid):
                if p["ist"] is None:
                    continue
                if abs(float(p["ist"]) - float(p["aktuell"] or 0)) > 1e-9 or p["aktuell"] is None:
                    L.inventur(p["nummer"], p["code"], p["ist"], zweck=inv["name"])
                    n += 1
            con.execute(update(inventuren).where(inventuren.c.id == iid).values(status="abgeschlossen", abgeschlossen_am=datetime.now()))
            audit(con, request.session["user"]["username"], "Inventur abgeschlossen", str(iid), {"korrekturen": n})
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/inventur/{iid}", status_code=303)
    flash(request, f"Inventur abgeschlossen – {n} Bestandskorrektur(en) gebucht.")
    return RedirectResponse(f"/inventur/{iid}", status_code=303)


@router.get("/inventur/{iid}/zaehlliste.xlsx")
def zaehlliste(request: Request, iid: int):
    require(request)
    with db.engine().connect() as con:
        pos = inventur_positionen(con, iid)
    z = [[p["code"], p["nummer"], p["bezeichnung"], p["soll"], p["ist"], (p["ist"] - (p["aktuell"] or 0)) if p["ist"] is not None else None] for p in pos]
    return Response(tabelle_xlsx("Zählliste", ["Lagerplatz", "Artikel", "Bezeichnung", "Soll", "Gezählt", "Differenz"], z, [12, 12, 45, 8, 9, 10]),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Zaehlliste_{iid}.xlsx"'})


# ------------------------------------------------------------------ Lieferanten
@router.get("/lieferanten")
def lieferanten_liste(request: Request, bearbeiten: int = 0):
    require(request)
    with db.engine().connect() as con:
        rows = con.execute(select(lieferanten, func.count(artikel.c.id).label("artikel"))
                           .select_from(lieferanten.outerjoin(artikel, artikel.c.lieferant_id == lieferanten.c.id))
                           .group_by(lieferanten.c.id).order_by(func.lower(lieferanten.c.name))).mappings().all()
    return render(request, "lieferanten.html", rows=rows, edit=next((r for r in rows if r["id"] == bearbeiten), None))


@router.post("/lieferanten/speichern")
async def lieferant_speichern(request: Request):
    require(request, "lager")
    f = dict(await request.form())
    werte = {k: (f.get(k) or "").strip() or None for k in ("name", "ansprechpartner", "email", "telefon", "kundennummer", "webseite", "notiz")}
    if not werte["name"]:
        flash(request, "Bitte einen Namen angeben.", "fehler")
        return RedirectResponse("/lieferanten", status_code=303)
    with db.schreiben() as con:
        doppelt = con.execute(select(lieferanten.c.id).where(func.lower(lieferanten.c.name) == werte["name"].lower())).scalar()
        if doppelt and str(doppelt) != str(f.get("id") or ""):
            flash(request, f"Lieferant {werte['name']} gibt es schon.", "fehler")
            return RedirectResponse("/lieferanten", status_code=303)
        if f.get("id"):
            con.execute(update(lieferanten).where(lieferanten.c.id == int(f["id"])).values(**werte))
        else:
            con.execute(insert(lieferanten).values(**werte))
        audit(con, request.session["user"]["username"], "Lieferant gespeichert", werte["name"])
    flash(request, f"Lieferant {werte['name']} gespeichert.")
    return RedirectResponse("/lieferanten", status_code=303)


@router.post("/lieferanten/{lid}/loeschen")
def lieferant_loeschen(request: Request, lid: int):
    require(request, "admin")
    with db.schreiben() as con:
        con.execute(update(artikel).where(artikel.c.lieferant_id == lid).values(lieferant_id=None))
        con.execute(delete(lieferanten).where(lieferanten.c.id == lid))
        audit(con, request.session["user"]["username"], "Lieferant gelöscht", str(lid))
    flash(request, "Lieferant gelöscht.")
    return RedirectResponse("/lieferanten", status_code=303)
