"""Instandhaltung – Wartungsplanung: Plan-Übersicht, Kalender, Wochenliste, Kampagnen, Aufträge, Protokolle, Nachweise.

Jede Route prüft ihr Recht serverseitig (require_recht). Geschäftslogik in app/services/wartung.py.
"""
from __future__ import annotations

import json
import mimetypes
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, insert, select, update

from .. import db
from ..db import (ih_auftraege, ih_auftrag_positionen, ih_dokumente, ih_import_laeufe, ih_import_zeilen, ih_kampagne_bauteile,
                  ih_kampagnen, ih_plaetze, ih_statuslog)
from ..rechte import hat_recht
from ..services import wartung as w
from ..services.lager import audit
from ..web import flash, render, require_recht

router = APIRouter(prefix="/ih")

MAX_DOKUMENT = 25 * 1024 * 1024
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


# ------------------------------------------------------------------ Plan-Übersicht
@router.get("/wartung")
def wartung(request: Request, art: str = ""):
    require_recht(request, "ih.ansehen")
    heute = date.today()
    with db.engine().connect() as con:
        kampagnen = w.lage(con, heute)
        mass = w.massnahmen(con)
        offen = w.offene_auftraege_zahl(con)
    if art == "eigen":
        kampagnen = [k for k in kampagnen if not k["massnahme"].startswith("Z")]
    elif art == "pflicht":
        kampagnen = [k for k in kampagnen if k["massnahme"].startswith("Z")]
    reihe = {"ueberfaellig": 0, "laeuft": 1, "bald": 2, "geplant": 3, "inaktiv": 4}
    kampagnen.sort(key=lambda k: (reihe[k["lage"]], k["naechster"] or date.max, k["schluessel"]))
    zahl = {lg: sum(1 for k in kampagnen if k["lage"] == lg) for lg in reihe}
    return render(request, "ih/wartung.html", kampagnen=kampagnen, mass=mass, zahl=zahl, offen=offen, art=art, heute=heute,
                  LAGE_TEXT=w.LAGE_TEXT, kw=w.kw, timedelta=timedelta)


@router.post("/wartung/auftraege-anlegen")
def auftraege_anlegen(request: Request):
    me = require_recht(request, "ih.wartung.planen")
    with db.schreiben() as con:
        neu = w.faellige_anlegen(con, me["username"])
    flash(request, f"{len(neu)} Aufträge angelegt (alle Kampagnen, deren Termin fällig ist oder im Vorlauf liegt)." if neu
          else "Keine neuen Aufträge nötig – für alle fälligen Termine gibt es schon einen Auftrag.")
    return RedirectResponse("/ih/auftraege" if neu else "/ih/wartung", status_code=303)


# ------------------------------------------------------------------ Kalender und Wochenliste
def _wochen(ab: str, anzahl: int) -> list[date]:
    try:
        start = w.montag(date.fromisoformat(ab)) if ab else w.montag(date.today())
    except ValueError:
        start = w.montag(date.today())
    return [start + timedelta(weeks=i) for i in range(anzahl)]


def _belegung(con, wochen: list[date]):
    """Je Kampagne: Woche -> ('start'|'lauf', Termin, Auftragsstatus)."""
    kampagnen = [k for k in w.lage(con) if k["aktiv"]]
    auftr = {(r.kampagne_id, r.termin): r.status for r in con.execute(select(ih_auftraege.c.kampagne_id, ih_auftraege.c.termin,
                                                                             ih_auftraege.c.status))}
    bis = wochen[-1] + timedelta(days=6)
    heute = date.today()
    belegt = {}
    for k in kampagnen:
        zellen = {}
        dauer = max(1, k["dauer_wochen"] or 1)
        for t in w.termine(k, bis):
            start = w.montag(t)
            st = auftr.get((k["id"], t))
            ueber = t + timedelta(weeks=dauer) <= heute and st not in ("abgeschlossen", "storniert")
            for i in range(dauer):
                woche = start + timedelta(weeks=i)
                if wochen[0] <= woche <= wochen[-1]:
                    zellen[woche] = ("start" if i == 0 else "lauf", t, st, ueber)
        belegt[k["id"]] = zellen
    return kampagnen, belegt


@router.get("/wartung/kalender")
def kalender(request: Request, ab: str = "", wochen: int = 26):
    require_recht(request, "ih.ansehen")
    wochen = wochen if wochen in (13, 26, 52, 104, 156) else 26
    liste = _wochen(ab, wochen)
    with db.engine().connect() as con:
        kampagnen, belegt = _belegung(con, liste)
        mass = w.massnahmen(con)
    reihe = {m: i for i, m in enumerate(mass)}
    kampagnen.sort(key=lambda k: (k["massnahme"].startswith("Z"), reihe.get(k["massnahme"], 99), k["bauteilklasse"] or ""))
    last = w.wochenlast(kampagnen, liste)
    return render(request, "ih/kalender.html", wochen=liste, kampagnen=kampagnen, belegt=belegt, mass=mass, last=last,
                  anzahl=wochen, vor=(liste[0] + timedelta(weeks=wochen)).isoformat(), zurueck=(liste[0] - timedelta(weeks=wochen)).isoformat(),
                  diese=w.montag(date.today()), STATUS=w.STATUS,
                  farben_codes=[m for m in ("S", "W", "F", "Za", "Zi", "Zf", "Zv", "B") if any(k["massnahme"] == m for k in kampagnen)],
                  weitere_pflicht=any(k["massnahme"].startswith("Z") and k["massnahme"] not in ("Za", "Zi", "Zf", "Zv") for k in kampagnen))


@router.get("/wartung/wochen")
def wochenliste(request: Request, ab: str = "", wochen: int = 13):
    require_recht(request, "ih.ansehen")
    wochen = wochen if wochen in (4, 13, 26, 52) else 13
    liste = _wochen(ab, wochen)
    with db.engine().connect() as con:
        kampagnen, belegt = _belegung(con, liste)
        mass = w.massnahmen(con)
    nach_woche = {wo: [] for wo in liste}
    for k in kampagnen:
        for wo, (art, termin, status, ueber) in belegt[k["id"]].items():
            nach_woche[wo].append({"k": k, "art": art, "termin": termin, "status": status, "ueber": ueber})
    for v in nach_woche.values():
        v.sort(key=lambda e: (e["art"] != "start", e["k"]["schluessel"]))
    return render(request, "ih/wochenliste.html", nach_woche=nach_woche, mass=mass, anzahl=wochen, kw=w.kw, timedelta=timedelta,
                  STATUS=w.STATUS, vor=(liste[0] + timedelta(weeks=wochen)).isoformat(), zurueck=(liste[0] - timedelta(weeks=wochen)).isoformat())


# ------------------------------------------------------------------ Kampagnen
def _kampagne(con, kid: int) -> dict | None:
    r = con.execute(select(ih_kampagnen).where(ih_kampagnen.c.id == kid)).mappings().first()
    return dict(r) if r else None


def _kampagne_werte(f, neu: bool = False) -> tuple[dict, list[str]]:
    """Formularfelder einer Kampagne (Bearbeiten und eigene Kampagne anlegen)."""
    fehler = []
    werte = {"verantwortlich": (f.get("verantwortlich") or "").strip() or None, "aktiv": f.get("aktiv") == "on" or (neu and "aktiv" not in f),
             "rhythmus": f.get("rhythmus") if f.get("rhythmus") in w.RHYTHMUS else "fest",
             "taetigkeit": (f.get("taetigkeit") or "").strip() or None, "hinweis": (f.get("hinweis") or "").strip() or None}
    for feld, lab in (("intervall_monate", "Intervall"), ("dauer_wochen", "Dauer"), ("vorlauf_wochen", "Vorlauf")):
        v = (f.get(feld) or "").strip()
        if v == "" and feld in ("vorlauf_wochen", "dauer_wochen"):
            werte[feld] = None if feld == "vorlauf_wochen" else 1
            continue
        if not v.isdigit() or (feld != "vorlauf_wochen" and int(v) < 1) or int(v) > 600:
            fehler.append(f"{lab}: ganze Zahl angeben.")
        else:
            werte[feld] = int(v)
    try:
        werte["erster_termin"] = date.fromisoformat(f.get("erster_termin") or "")
    except ValueError:
        fehler.append("Erster Termin bzw. Beginn: gültiges Datum angeben.")
    try:
        werte["aufwand_tage"] = float(str(f.get("aufwand_tage") or "0").replace(",", ".")) or None
    except ValueError:
        fehler.append("Aufwand: Zahl angeben.")
    return werte, fehler


@router.get("/wartung/kampagne/neu")
def kampagne_neu_form(request: Request, platz: str = ""):
    require_recht(request, "ih.wartung.planen")
    with db.schreiben() as con:
        w.massnahmen_sicherstellen(con)
    with db.engine().connect() as con:
        mass = w.massnahmen(con)
        klassen = [r[0] for r in con.execute(select(ih_plaetze.c.bauteilklasse).where(ih_plaetze.c.bauteilklasse.isnot(None),
                                                                                    ih_plaetze.c.bauteilklasse != "").distinct().order_by(ih_plaetze.c.bauteilklasse))]
        tags = _tags(con)
        vorbelegt = con.execute(select(ih_plaetze.c.code).where(ih_plaetze.c.id == int(platz))).scalar() if platz.isdigit() else None
    return render(request, "ih/kampagne_neu.html", mass=mass, klassen=klassen, tags=tags, vorbelegt=[vorbelegt] if vorbelegt else [],
                  RHYTHMUS=w.RHYTHMUS, f={}, heute=w.montag(date.today()))


def _tags(con) -> list[tuple[str, str]]:
    return [(r.code, r.bezeichnung or "") for r in con.execute(select(ih_plaetze.c.code, ih_plaetze.c.bezeichnung)
                                                               .where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv).order_by(ih_plaetze.c.code))]


def _platz_ids(con, codes: list[str]) -> tuple[list[int], list[str]]:
    from ..services.asset_import import schluessel
    ids, unbekannt = [], []
    for c in codes:
        c = " ".join((c or "").split(" – ")[0].split())
        if not c:
            continue
        pid = con.execute(select(ih_plaetze.c.id).where(ih_plaetze.c.schluessel == schluessel(c), ih_plaetze.c.art == "platz")).scalar()
        if pid:
            if pid not in ids:
                ids.append(pid)
        else:
            unbekannt.append(c)
    return ids, unbekannt


@router.post("/wartung/kampagne/neu")
async def kampagne_neu(request: Request):
    me = require_recht(request, "ih.wartung.planen")
    f = await request.form()
    werte, fehler = _kampagne_werte(f, neu=True)
    massnahme = f.get("massnahme") or ""
    ziel = f.get("ziel") or "bauteile"
    klasse = (f.get("bauteilklasse") or "").strip() if ziel == "klasse" else None
    gegenstand = (f.get("gegenstand") or "").strip() or None
    with db.schreiben() as con:
        mass = w.massnahmen(con)
        if massnahme not in mass:
            fehler.append("Bitte eine Maßnahme wählen.")
        ids, unbekannt = _platz_ids(con, f.getlist("tag")) if ziel == "bauteile" else ([], [])
        if unbekannt:
            fehler.append(f"Diese Tag-Nr. gibt es nicht unter Anlagen: {', '.join(unbekannt)}.")
        if ziel == "bauteile" and not ids:
            fehler.append("Bitte mindestens ein Bauteil auswählen.")
        if ziel == "klasse" and not klasse:
            fehler.append("Bitte eine Bauteilklasse wählen.")
        if ziel == "anlage" and not gegenstand:
            fehler.append("Bitte angeben, was geprüft bzw. gewartet wird (Gegenstand).")
        if not werte.get("taetigkeit"):
            fehler.append("Bitte beschreiben, was zu tun ist.")
        if fehler:
            klassen = [r[0] for r in con.execute(select(ih_plaetze.c.bauteilklasse).where(ih_plaetze.c.bauteilklasse.isnot(None),
                                                                                        ih_plaetze.c.bauteilklasse != "").distinct().order_by(ih_plaetze.c.bauteilklasse))]
            return render(request, "ih/kampagne_neu.html", mass=mass, klassen=klassen, tags=_tags(con), vorbelegt=list(f.getlist("tag")),
                          RHYTHMUS=w.RHYTHMUS, f=dict(f), fehler=" ".join(fehler), heute=w.montag(date.today()))
        text = gegenstand or klasse or con.execute(select(ih_plaetze.c.code).where(ih_plaetze.c.id == ids[0])).scalar()
        sid = w.schluessel_vorschlag(con, massnahme, text)
        kid = con.execute(insert(ih_kampagnen).values(
            schluessel=sid, massnahme=massnahme, bauteilklasse=klasse if ziel == "klasse" else ("Anlage" if ziel == "anlage" else None),
            gegenstand=gegenstand or (None if ziel != "bauteile" else (text if len(ids) == 1 else f"{text} + {len(ids) - 1} weitere")),
            grundlage=(f.get("grundlage") or "").strip() or None, eigen=True, geaendert_am=datetime.now(),
            durchfuehrung=(f.get("durchfuehrung") or "").strip() or None, **werte)).inserted_primary_key[0]
        for pid in ids:
            con.execute(insert(ih_kampagne_bauteile).values(kampagne_id=kid, platz_id=pid))
        audit(con, me["username"], "Eigene Kampagne angelegt", sid, {"bauteile": len(ids), "klasse": klasse, "intervall": werte.get("intervall_monate")})
    flash(request, f"Kampagne {sid} angelegt.")
    return RedirectResponse(f"/ih/wartung/kampagne/{kid}", status_code=303)


@router.get("/wartung/kampagne/{kid}")
def kampagne(request: Request, kid: int):
    require_recht(request, "ih.ansehen")
    heute = date.today()
    with db.engine().connect() as con:
        k = next((x for x in w.lage(con, heute) if x["id"] == kid), None)
        if not k:
            return render(request, "fehler.html", titel="Kampagne nicht gefunden", text="Diese Kampagne gibt es nicht.")
        m = w.massnahmen(con).get(k["massnahme"], {"name": k["massnahme"], "symbol": ""})
        auftr = {r["termin"]: dict(r) for r in con.execute(select(ih_auftraege).where(ih_auftraege.c.kampagne_id == kid)).mappings()}
        kommende = [t for t in w.termine(k, heute + timedelta(days=366 * 3)) if t + timedelta(weeks=k["dauer_wochen"] or 1) > heute][:6]
        teile = w.bauteile_kampagne(con, k)
        letzte = dict(con.execute(select(ih_auftrag_positionen.c.platz_id, func.max(ih_auftrag_positionen.c.durchgefuehrt_am))
                                  .select_from(ih_auftrag_positionen.join(ih_auftraege, ih_auftraege.c.id == ih_auftrag_positionen.c.auftrag_id))
                                  .where(ih_auftraege.c.kampagne_id == kid, ih_auftrag_positionen.c.ergebnis.isnot(None))
                                  .group_by(ih_auftrag_positionen.c.platz_id)).all())
        achtung = w.achtung(con, k["massnahme"], k["bauteilklasse"]) if not k["einzeln"] else None
        tags = _tags(con) if k["einzeln"] else []
    return render(request, "ih/kampagne.html", k=k, m=m, auftr=auftr, kommende=kommende, teile=teile, letzte=letzte, achtung=achtung,
                  heute=heute, kw=w.kw, STATUS=w.STATUS, LAGE_TEXT=w.LAGE_TEXT, timedelta=timedelta, RHYTHMUS=w.RHYTHMUS, tags=tags,
                  historie=sorted(auftr.values(), key=lambda a: a["termin"], reverse=True))


@router.post("/wartung/kampagne/{kid}/bearbeiten")
async def kampagne_bearbeiten(request: Request, kid: int):
    me = require_recht(request, "ih.wartung.planen")
    f = await request.form()
    werte, fehler = _kampagne_werte(f)
    if fehler:
        flash(request, " ".join(fehler), "fehler")
        return RedirectResponse(f"/ih/wartung/kampagne/{kid}", status_code=303)
    with db.schreiben() as con:
        k = _kampagne(con, kid)
        if not k:
            return RedirectResponse("/ih/wartung", status_code=303)
        geaendert = {x: [str(k[x]), str(v)] for x, v in werte.items() if k[x] != v and not (k[x] is None and x == "rhythmus" and v == "fest")}
        if geaendert:
            con.execute(update(ih_kampagnen).where(ih_kampagnen.c.id == kid).values(geaendert_am=datetime.now(), **werte))
            audit(con, me["username"], "Kampagne geändert", k["schluessel"], geaendert)
    flash(request, ("Kampagne gespeichert." + ("" if k.get("eigen") else " Hinweis: Ein erneuter Import des Instandhaltungsplans überschreibt "
                    "die Werte aus dem Plan; Rhythmus und Tätigkeit bleiben.")) if geaendert else "Keine Änderungen.")
    return RedirectResponse(f"/ih/wartung/kampagne/{kid}", status_code=303)


@router.post("/wartung/kampagne/{kid}/bauteile")
async def kampagne_bauteile(request: Request, kid: int):
    """Einzelne Bauteile einer eigenen Kampagne hinzufügen oder entfernen."""
    me = require_recht(request, "ih.wartung.planen")
    f = await request.form()
    with db.schreiben() as con:
        k = _kampagne(con, kid)
        if not k:
            return RedirectResponse("/ih/wartung", status_code=303)
        if f.get("entfernen", "").isdigit():
            n = con.execute(select(func.count()).select_from(ih_kampagne_bauteile).where(ih_kampagne_bauteile.c.kampagne_id == kid)).scalar()
            if n <= 1:
                flash(request, "Das letzte Bauteil bleibt – die Kampagne stattdessen deaktivieren.", "fehler")
            else:
                con.execute(ih_kampagne_bauteile.delete().where(ih_kampagne_bauteile.c.kampagne_id == kid,
                                                                ih_kampagne_bauteile.c.platz_id == int(f["entfernen"])))
                audit(con, me["username"], "Kampagne: Bauteil entfernt", k["schluessel"], {"platz_id": int(f["entfernen"])})
        else:
            ids, unbekannt = _platz_ids(con, f.getlist("tag"))
            vorhanden = {r[0] for r in con.execute(select(ih_kampagne_bauteile.c.platz_id).where(ih_kampagne_bauteile.c.kampagne_id == kid))}
            neu = [i for i in ids if i not in vorhanden]
            for pid in neu:
                con.execute(insert(ih_kampagne_bauteile).values(kampagne_id=kid, platz_id=pid))
            if neu:
                audit(con, me["username"], "Kampagne: Bauteile hinzugefügt", k["schluessel"], {"anzahl": len(neu)})
            if unbekannt:
                flash(request, f"Nicht gefunden: {', '.join(unbekannt)}.", "fehler")
            elif neu:
                flash(request, f"{len(neu)} Bauteil(e) hinzugefügt. Neue Aufträge enthalten sie, bestehende bleiben unverändert.")
    return RedirectResponse(f"/ih/wartung/kampagne/{kid}#bauteile", status_code=303)


@router.post("/wartung/kampagne/{kid}/auftrag")
def kampagne_auftrag(request: Request, kid: int, termin: str = Form("")):
    me = require_recht(request, "ih.wartung.planen")
    try:
        with db.schreiben() as con:
            aid = w.auftrag_anlegen(con, kid, date.fromisoformat(termin), me["username"])
    except (ValueError, w.WartungsFehler) as e:
        flash(request, str(e) if isinstance(e, w.WartungsFehler) else "Ungültiger Termin.", "fehler")
        return RedirectResponse(f"/ih/wartung/kampagne/{kid}", status_code=303)
    flash(request, f"Auftrag A-{aid:05d} angelegt. Nächster Schritt: freigeben.")
    return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)


# ------------------------------------------------------------------ Instandhaltungsplan übernehmen
@router.get("/wartung/import")
def plan_import_form(request: Request):
    require_recht(request, "ih.wartung.planen")
    with db.engine().connect() as con:
        laeufe = con.execute(select(ih_import_laeufe).where(ih_import_laeufe.c.art == "plan").order_by(ih_import_laeufe.c.id.desc())
                             .limit(10)).mappings().all()
    return render(request, "ih/plan_import.html", laeufe=laeufe)


@router.post("/wartung/import")
async def plan_import(request: Request, datei: UploadFile | None = None):
    me = require_recht(request, "ih.wartung.planen")
    if datei is None or not datei.filename:
        flash(request, "Bitte den Instandhaltungsplan (Excel) auswählen.", "fehler")
        return RedirectResponse("/ih/wartung/import", status_code=303)
    inhalt = await datei.read(10 * 1024 * 1024 + 1)
    try:
        if len(inhalt) > 10 * 1024 * 1024:
            raise w.WartungsFehler("Die Datei ist größer als 10 MB.")
        plan = w.plan_lesen(inhalt)
    except w.WartungsFehler as e:
        flash(request, f"{datei.filename}: {e}", "fehler")
        return RedirectResponse("/ih/wartung/import", status_code=303)
    with db.schreiben() as con:
        lid = con.execute(insert(ih_import_laeufe).values(dateiname=datei.filename[:300], benutzer=me["username"], zeit=datetime.now(),
                                                          status="geprueft", art="plan", zeilen=len(plan["kampagnen"]))).inserted_primary_key[0]
        con.execute(insert(ih_import_zeilen).values(lauf_id=lid, nr=1, werte=w.plan_als_json(plan)))
    return RedirectResponse(f"/ih/wartung/import/{lid}", status_code=303)


def _plan_lauf(con, lid: int):
    lauf = con.execute(select(ih_import_laeufe).where(ih_import_laeufe.c.id == lid, ih_import_laeufe.c.art == "plan")).mappings().first()
    if not lauf:
        return None, None
    text = con.execute(select(ih_import_zeilen.c.werte).where(ih_import_zeilen.c.lauf_id == lid)).scalar()
    return dict(lauf), w.plan_aus_json(text)


@router.get("/wartung/import/{lid}")
def plan_import_lauf(request: Request, lid: int):
    require_recht(request, "ih.wartung.planen")
    with db.engine().connect() as con:
        lauf, plan = _plan_lauf(con, lid)
        if not lauf:
            return RedirectResponse("/ih/wartung/import", status_code=303)
        vergleich = w.plan_vergleich(con, plan)
        anzahl = w.bauteile_je_klasse(con)
    ergebnis = json.loads(lauf["ergebnis"]) if lauf["ergebnis"] else None
    return render(request, "ih/plan_import_lauf.html", lauf=lauf, plan=plan, v=vergleich, anzahl=anzahl, ergebnis=ergebnis)


@router.post("/wartung/import/{lid}/uebernehmen")
def plan_import_uebernehmen(request: Request, lid: int, bestaetigt: str = Form("")):
    me = require_recht(request, "ih.wartung.planen")
    if bestaetigt != "ja":
        flash(request, "Bitte die Übernahme bestätigen.", "fehler")
        return RedirectResponse(f"/ih/wartung/import/{lid}", status_code=303)
    cfg = request.app.state.cfg
    with db.engine().connect() as con:
        lauf, plan = _plan_lauf(con, lid)
    if not lauf or lauf["status"] == "uebernommen":
        flash(request, "Dieser Plan ist schon übernommen. Für eine neue Fassung die Datei erneut hochladen.", "fehler")
        return RedirectResponse(f"/ih/wartung/import/{lid}", status_code=303)
    try:
        from ..services.sicherung import einzel_sicherung
        gesichert = einzel_sicherung(cfg, cfg.path(cfg.backup.ordner), name="vor_import", aufbewahren_tage=365).name
    except Exception as e:
        flash(request, f"Sicherung vor der Übernahme fehlgeschlagen ({e}). Nichts übernommen.", "fehler")
        return RedirectResponse(f"/ih/wartung/import/{lid}", status_code=303)
    with db.schreiben() as con:
        zahlen = w.plan_uebernehmen(con, plan, me["username"])
        con.execute(update(ih_import_laeufe).where(ih_import_laeufe.c.id == lid).values(
            status="uebernommen", uebernommen_am=datetime.now(), ergebnis=json.dumps({**zahlen, "sicherung": gesichert, "von": me["username"]})))
    flash(request, f"Instandhaltungsplan übernommen: {len(plan['kampagnen'])} Kampagnen, {len(plan['intervalle'])} Intervalle, "
                   f"{len(plan['massnahmen'])} Maßnahmen. Vorheriger Stand gesichert als „{gesichert}“.")
    return RedirectResponse("/ih/wartung", status_code=303)


# ------------------------------------------------------------------ Aufträge
@router.get("/auftraege")
def auftraege(request: Request, status: str = "offen", massnahme: str = ""):
    me = require_recht(request, "ih.ansehen")
    q = select(ih_auftraege, ih_kampagnen.c.schluessel.label("kampagne")).select_from(
        ih_auftraege.outerjoin(ih_kampagnen, ih_kampagnen.c.id == ih_auftraege.c.kampagne_id))
    if status == "offen":
        q = q.where(ih_auftraege.c.status.in_(w.OFFEN))
    elif status in w.STATUS:
        q = q.where(ih_auftraege.c.status == status)
    if massnahme:
        q = q.where(ih_auftraege.c.massnahme == massnahme)
    with db.engine().connect() as con:
        rows = [dict(r) for r in con.execute(q.order_by(ih_auftraege.c.termin, ih_auftraege.c.id).limit(500)).mappings()]
        fortschritt = {r.auftrag_id: (r.fertig, r.gesamt) for r in con.execute(
            select(ih_auftrag_positionen.c.auftrag_id, func.count(ih_auftrag_positionen.c.ergebnis).label("fertig"), func.count().label("gesamt"))
            .group_by(ih_auftrag_positionen.c.auftrag_id))}
        zahl = dict(con.execute(select(ih_auftraege.c.status, func.count()).group_by(ih_auftraege.c.status)).all())
        mass = w.massnahmen(con)
    return render(request, "ih/auftraege.html", rows=rows, fortschritt=fortschritt, zahl=zahl, status=status, massnahme=massnahme,
                  mass=mass, STATUS=w.STATUS, kw=w.kw, heute=date.today(), timedelta=timedelta, me=me)


def _auftrag_ctx(con, aid: int) -> dict | None:
    a = w.auftrag(con, aid)
    if not a:
        return None
    pos = w.positionen(con, aid)
    docs = [dict(r) for r in con.execute(select(ih_dokumente).where(ih_dokumente.c.auftrag_id == aid).order_by(ih_dokumente.c.id)).mappings()]
    log = [dict(r) for r in con.execute(select(ih_statuslog).where(ih_statuslog.c.auftrag_id == aid).order_by(ih_statuslog.c.id)).mappings()]
    m = w.massnahmen(con).get(a["massnahme"], {"name": a["massnahme"], "symbol": "", "beschreibung": None, "wer": None, "nachweis": None})
    teile = w.ersatzteile_auftrag(con, aid)
    entn = w.entnahmen(con, aid)
    kosten = sum(-(e["menge"] or 0) * (e["preis"] or 0) for e in entn)
    achtung = " ".join(x for x in (w.achtung(con, a["massnahme"], a["bauteilklasse"]), a.get("kampagne_hinweis") if a.get("eigen") else None) if x) or None
    return {"a": a, "pos": pos, "docs": docs, "log": log, "m": m, "achtung": achtung, "teile": teile, "entn": entn, "kosten": kosten}


@router.get("/auftraege/{aid}")
def auftrag_seite(request: Request, aid: int):
    me = require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        ctx = _auftrag_ctx(con, aid)
    if not ctx:
        return render(request, "fehler.html", titel="Auftrag nicht gefunden", text="Diesen Auftrag gibt es nicht.")
    cfg = request.app.state.cfg
    aktionen = [a for a, (von, _, recht) in w.AKTIONEN.items() if ctx["a"]["status"] in von and hat_recht(me, recht, cfg)]
    return render(request, "ih/auftrag.html", **ctx, aktionen=aktionen, me=me, STATUS=w.STATUS, ERGEBNIS=w.ERGEBNIS,
                  ERGEBNIS_Z=w.ERGEBNIS_Z, ZUSTAND=w.ZUSTAND, kw=w.kw,
                  bearbeitbar=ctx["a"]["status"] in ("freigegeben", "in_arbeit") and hat_recht(me, "ih.auftrag.ausfuehren", cfg))


@router.post("/auftraege/{aid}/status")
def auftrag_status(request: Request, aid: int, aktion: str = Form(""), text: str = Form("")):
    me = require_recht(request, "ih.ansehen")
    if aktion not in w.AKTIONEN:
        flash(request, "Unbekannte Aktion.", "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
    require_recht(request, w.AKTIONEN[aktion][2])
    try:
        with db.schreiben() as con:
            neu = w.status_aendern(con, aid, aktion, me["username"], text)
    except w.WartungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
    flash(request, f"Auftrag A-{aid:05d}: {w.STATUS[neu]}.")
    return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)


def _ergebnis_aus(f, prefix: str = "") -> dict:
    g = lambda k: (f.get(prefix + k) or "").strip()  # noqa: E731
    return {"ergebnis": g("ergebnis"), "befund_nr": g("befund_nr"), "befund_text": g("befund_text")}


@router.post("/auftraege/{aid}/sammel")
async def auftrag_sammel(request: Request, aid: int):
    """Sammelprotokoll (WP-02) bzw. Ergebnisliste einer Pflichtprüfung: mehrere Bauteile in einem Schritt."""
    me = require_recht(request, "ih.auftrag.ausfuehren")
    f = await request.form()
    gespeichert, fehler = 0, []
    try:
        with db.schreiben() as con:
            a = w.auftrag(con, aid)
            if not a:
                return RedirectResponse("/ih/auftraege", status_code=303)
            for p in w.positionen(con, aid):
                if p["formular"] == "WP-01":
                    continue
                werte = _ergebnis_aus(f, f"p{p['id']}_")
                if not werte["ergebnis"]:
                    continue
                if (werte["ergebnis"], werte["befund_nr"] or None, werte["befund_text"] or None) == (p["ergebnis"], p["befund_nr"], p["befund_text"]):
                    continue
                probleme = w.position_pruefen(p, werte)
                if probleme:
                    fehler.append(f"{p['code']}: {' '.join(probleme)}")
                    continue
                w.position_speichern(con, a, p, werte, me["username"])
                gespeichert += 1
    except w.WartungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
    if gespeichert:
        flash(request, f"{gespeichert} Bauteile gespeichert.")
    if fehler:
        flash(request, "Nicht gespeichert – " + " | ".join(fehler[:5]) + (" …" if len(fehler) > 5 else ""), "fehler")
    if not gespeichert and not fehler:
        flash(request, "Keine Änderungen.")
    return RedirectResponse(f"/ih/auftraege/{aid}#bauteile", status_code=303)


@router.get("/auftraege/{aid}/position/{pid}")
def position_form(request: Request, aid: int, pid: int):
    me = require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        ctx = _auftrag_ctx(con, aid)
    p = next((x for x in (ctx or {}).get("pos", []) if x["id"] == pid), None) if ctx else None
    if not p:
        return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
    reihe = [x["id"] for x in ctx["pos"]]
    i = reihe.index(pid)
    return render(request, "ih/protokoll.html", **ctx, p=p, ZUSTAND=w.ZUSTAND, ERGEBNIS=w.ERGEBNIS, ABSCHLUSS=w.ABSCHLUSS, STATUS=w.STATUS,
                  naechste=reihe[i + 1] if i + 1 < len(reihe) else None, vorige=reihe[i - 1] if i else None, nr=i + 1,
                  bearbeitbar=ctx["a"]["status"] in ("freigegeben", "in_arbeit") and hat_recht(me, "ih.auftrag.ausfuehren", request.app.state.cfg))


@router.post("/auftraege/{aid}/position/{pid}")
async def position_speichern(request: Request, aid: int, pid: int):
    me = require_recht(request, "ih.auftrag.ausfuehren")
    f = await request.form()
    schritte = []
    for s_, soll, ist, io, bem in zip(f.getlist("schritt"), f.getlist("soll"), f.getlist("ist"), f.getlist("io"), f.getlist("bemerkung")):
        if any(x.strip() for x in (s_, soll, ist, bem)):
            schritte.append({"schritt": s_.strip(), "soll": soll.strip(), "ist": ist.strip(), "io": io, "bemerkung": bem.strip()})
    werte = {**_ergebnis_aus(f), "zustand_beginn": f.get("zustand_beginn") or "", "zustand_text": (f.get("zustand_text") or "").strip(),
             "sil": (f.get("sil") or "").strip(), "schritte": schritte[:50], "abschluss": {k: f.get(f"ab_{k}") == "on" for k in w.ABSCHLUSS}}
    try:
        with db.schreiben() as con:
            a = w.auftrag(con, aid)
            p = next((x for x in w.positionen(con, aid) if x["id"] == pid), None) if a else None
            if not p:
                return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
            w.position_speichern(con, a, p, werte, me["username"])
            reihe = [x["id"] for x in w.positionen(con, aid)]
    except w.WartungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}/position/{pid}", status_code=303)
    flash(request, f"Protokoll {p['code']} gespeichert.")
    i = reihe.index(pid)
    if f.get("weiter") == "naechste" and i + 1 < len(reihe):
        return RedirectResponse(f"/ih/auftraege/{aid}/position/{reihe[i + 1]}", status_code=303)
    return RedirectResponse(f"/ih/auftraege/{aid}#bauteile", status_code=303)


@router.post("/auftraege/{aid}/entnahme")
def auftrag_entnahme(request: Request, aid: int, artikel_nr: str = Form(""), platz: str = Form(""), menge: str = Form("")):
    """Ersatzteil für den Auftrag entnehmen: bucht den Lagerbestand ab und verknüpft die Buchung mit dem Auftrag
    (Materialverbrauch je Anlage, Kosten zum Preis des Buchungszeitpunkts)."""
    me = require_recht(request, "ih.auftrag.ausfuehren")
    from ..services.lager import BuchungsFehler, Lager
    cfg = request.app.state.cfg
    try:
        with db.schreiben() as con:
            a = w.auftrag(con, aid)
            if not a or a["status"] not in ("freigegeben", "in_arbeit"):
                raise w.WartungsFehler("Entnahmen sind nur bei freigegebenen Aufträgen in Arbeit möglich.")
            lg = Lager(con, me["username"], "ih", cfg.lager.negative_bestaende_erlauben, False)
            e = lg.ausgang(artikel_nr.strip(), platz.strip(), menge, auftrag_id=aid, empfaenger=f"Auftrag A-{aid:05d}", zweck=a["titel"][:300])
            audit(con, me["username"], "Entnahme für Auftrag", f"A-{aid:05d}", {"artikel": e.artikel_nr, "platz": e.platz, "menge": e.menge})
    except (BuchungsFehler, w.WartungsFehler) as ex:
        flash(request, str(ex), "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}#ersatzteile", status_code=303)
    flash(request, f"Entnommen: {abs(e.menge):g} × {e.artikel_nr} von {e.platz} (Bestand dort jetzt {e.bestand_nachher:g}).")
    return RedirectResponse(f"/ih/auftraege/{aid}#ersatzteile", status_code=303)


# ------------------------------------------------------------------ Nachweise / Dokumente
def _ordner(request) -> Path:
    p = request.app.state.cfg.path(request.app.state.cfg.daten.anhaenge)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/auftraege/{aid}/dokument")
async def dokument_hochladen(request: Request, aid: int):
    me = require_recht(request, "ih.auftrag.ausfuehren")
    form = await request.form()
    dateien = [d for d in form.getlist("datei") if not isinstance(d, str) and d.filename]
    if not dateien:
        flash(request, "Bitte eine Datei auswählen.", "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}#nachweise", status_code=303)
    with db.engine().connect() as con:
        a = w.auftrag(con, aid)
    if not a or a["status"] in ("abgeschlossen", "storniert"):
        flash(request, "Zu abgeschlossenen oder stornierten Aufträgen lassen sich keine Nachweise mehr hinzufügen.", "fehler")
        return RedirectResponse(f"/ih/auftraege/{aid}", status_code=303)
    gelesen = []
    for d in dateien:  # erst lesen, dann in einer kurzen Schreibtransaktion speichern
        inhalt = await d.read(MAX_DOKUMENT + 1)
        if not inhalt or len(inhalt) > MAX_DOKUMENT:
            flash(request, f"{d.filename}: leer oder größer als 25 MB – nicht gespeichert.", "fehler")
            continue
        gelesen.append((d, inhalt))
    gespeichert, geschrieben = 0, []
    try:
        with db.schreiben() as con:
            for d, inhalt in gelesen:
                endung = "".join(c for c in Path(d.filename).suffix.lower()[:10] if c.isalnum() or c == ".")
                ziel = _ordner(request) / f"ih_{uuid.uuid4().hex}{endung}"
                ziel.write_bytes(inhalt)
                geschrieben.append(ziel)
                typ = mimetypes.guess_type(d.filename)[0] or d.content_type or "application/octet-stream"
                con.execute(insert(ih_dokumente).values(auftrag_id=aid, art="nachweis", dateiname=Path(d.filename).name[:300],
                                                        speichername=ziel.name, typ=typ, groesse=len(inhalt), hochgeladen_von=me["username"],
                                                        hochgeladen_am=datetime.now()))
                audit(con, me["username"], "Nachweis hochgeladen", f"A-{aid:05d}", {"datei": d.filename})
                gespeichert += 1
    except Exception:
        for p in geschrieben:
            p.unlink(missing_ok=True)
        raise
    if gespeichert:
        flash(request, f"{gespeichert} Nachweis(e) gespeichert.")
    return RedirectResponse(f"/ih/auftraege/{aid}#nachweise", status_code=303)


@router.get("/dokumente/{did}")
def dokument(request: Request, did: int, download: int = 0):
    require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        d = con.execute(select(ih_dokumente).where(ih_dokumente.c.id == did)).mappings().first()
    if not d:
        return render(request, "fehler.html", titel="Dokument nicht gefunden", text="Dieses Dokument gibt es nicht (mehr).")
    pfad = _ordner(request) / d["speichername"]
    if not pfad.exists():
        return render(request, "fehler.html", titel="Datei fehlt", text="Die Datei zu diesem Dokument ist nicht mehr vorhanden.")
    inline = d["typ"] in INLINE and not download
    return FileResponse(pfad, media_type=d["typ"] if inline else "application/octet-stream", filename=d["dateiname"],
                        content_disposition_type="inline" if inline else "attachment", headers={"X-Content-Type-Options": "nosniff"})
