"""Instandhaltung (CMMS): Übersicht, Anlagen, Asset-Import. Jede Route prüft ihr Recht serverseitig (require_recht)."""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import and_, delete, func, insert, or_, select, update

from .. import db
from ..db import artikel, ih_import_laeufe, ih_import_zeilen, ih_plaetze
from ..services import asset_import as ai
from ..services.excel import tabelle_xlsx
from ..services.lager import audit
from ..web import flash, render, require_recht

router = APIRouter(prefix="/ih")

PRO_SEITE = 100
ERGEBNIS_TEXT = {"neu": "Neu", "geaendert": "Wird geändert", "unveraendert": "Unverändert", "fehler": "Fehler – übersprungen"}
ART_TEXT = {"bereich": "Bereich", "unit": "Unit", "platz": "Bauteil"}


def _zusatz(p: dict) -> dict:
    try:
        return json.loads(p.get("zusatz") or "{}")
    except ValueError:
        return {}


# ------------------------------------------------------------------ Übersicht
@router.get("")
def uebersicht(request: Request):
    require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        def zahl(*bed):
            return con.execute(select(func.count()).select_from(ih_plaetze).where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv, *bed)).scalar()
        kennz = {
            "bauteile": zahl(),
            "sicher": zahl(ih_plaetze.c.sicherheitsgerichtet.is_(True)),
            "ohne_klasse": zahl(or_(ih_plaetze.c.bauteilklasse.is_(None), ih_plaetze.c.bauteilklasse == "")),
            "ohne_doku": zahl(or_(ih_plaetze.c.doku_url.is_(None), ih_plaetze.c.doku_url == "")),
            "ohne_unit": zahl(ih_plaetze.c.eltern_id.is_(None)),
        }
        einheiten = _ebenen(con)
        klassen = con.execute(select(ih_plaetze.c.bauteilklasse, func.count()).where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv)
                              .group_by(ih_plaetze.c.bauteilklasse).order_by(func.count().desc())).all()
        laeufe = con.execute(select(ih_import_laeufe).order_by(ih_import_laeufe.c.id.desc()).limit(5)).mappings().all()
    return render(request, "ih/uebersicht.html", k=kennz, ebenen=einheiten, klassen=klassen, laeufe=laeufe)


def _ebenen(con) -> list[dict]:
    """Bereiche und Units mit Anzahl Bauteile (direkt darunter), sortiert nach Code."""
    zaehl = dict(con.execute(select(ih_plaetze.c.eltern_id, func.count()).where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv)
                             .group_by(ih_plaetze.c.eltern_id)).all())
    rows = [dict(r) for r in con.execute(select(ih_plaetze.c.id, ih_plaetze.c.code, ih_plaetze.c.bezeichnung, ih_plaetze.c.art, ih_plaetze.c.eltern_id)
                                         .where(ih_plaetze.c.art.in_(("bereich", "unit")))).mappings()]
    for r in rows:
        r["anzahl"] = zaehl.get(r["id"], 0)
    bereiche = sorted((r for r in rows if r["art"] == "bereich"), key=lambda r: r["code"])
    out = []
    for b in bereiche:
        out.append(b)
        out += sorted((r for r in rows if r["eltern_id"] == b["id"]), key=lambda r: r["code"])
    rest = sorted((r for r in rows if r not in out), key=lambda r: r["code"])
    return out + rest


# ------------------------------------------------------------------ Anlagen
@router.get("/anlagen")
def anlagen(request: Request, q: str = "", ebene: str = "", klasse: str = "", filter: str = "", seite: int = 1):
    require_recht(request, "ih.ansehen")
    p = ih_plaetze
    bed = [p.c.art == "platz", p.c.aktiv]
    if q.strip():
        like = f"%{q.strip()}%"
        kompakt = f"%{ai.schluessel(q)}%"
        bed.append(or_(p.c.code.ilike(like), p.c.schluessel.like(kompakt), p.c.bezeichnung.ilike(like), p.c.hersteller.ilike(like),
                       p.c.modell.ilike(like), p.c.seriennummer.ilike(like), p.c.kategorie.ilike(like), p.c.bauteilklasse.ilike(like)))
    with db.engine().connect() as con:
        ebenen = _ebenen(con)
        if ebene.isdigit():
            ids = {int(ebene)} | {e["id"] for e in ebenen if e["eltern_id"] == int(ebene)}
            bed.append(p.c.eltern_id.in_(ids))
        elif ebene == "ohne":
            bed.append(p.c.eltern_id.is_(None))
        if klasse:
            bed.append(p.c.bauteilklasse == klasse if klasse != "-" else or_(p.c.bauteilklasse.is_(None), p.c.bauteilklasse == ""))
        if filter == "sicher":
            bed.append(p.c.sicherheitsgerichtet.is_(True))
        elif filter == "ohne_doku":
            bed.append(or_(p.c.doku_url.is_(None), p.c.doku_url == ""))
        gesamt = con.execute(select(func.count()).select_from(p).where(and_(*bed))).scalar()
        seite = max(1, min(seite, (gesamt + PRO_SEITE - 1) // PRO_SEITE or 1))
        eltern = p.alias("eltern")
        rows = con.execute(select(p, eltern.c.code.label("ebene")).select_from(p.outerjoin(eltern, eltern.c.id == p.c.eltern_id))
                           .where(and_(*bed)).order_by(p.c.code).limit(PRO_SEITE).offset((seite - 1) * PRO_SEITE)).mappings().all()
        klassen = [r[0] for r in con.execute(select(p.c.bauteilklasse).where(p.c.bauteilklasse.isnot(None), p.c.bauteilklasse != "")
                                             .distinct().order_by(p.c.bauteilklasse))]
    return render(request, "ih/anlagen.html", rows=rows, gesamt=gesamt, seite=seite, seiten=(gesamt + PRO_SEITE - 1) // PRO_SEITE,
                  q=q, ebene=ebene, klasse=klasse, filter=filter, ebenen=ebenen, klassen=klassen)


def _anlage(con, aid: int) -> dict | None:
    r = con.execute(select(ih_plaetze).where(ih_plaetze.c.id == aid)).mappings().first()
    return dict(r) if r else None


def _pfad(con, a: dict) -> list[dict]:
    pfad, eltern_id, gesehen = [], a.get("eltern_id"), set()
    while eltern_id and eltern_id not in gesehen:
        gesehen.add(eltern_id)
        e = _anlage(con, eltern_id)
        if not e:
            break
        pfad.insert(0, e)
        eltern_id = e["eltern_id"]
    return pfad


@router.get("/anlagen/{aid}")
def anlage(request: Request, aid: int):
    require_recht(request, "ih.ansehen")
    with db.engine().connect() as con:
        a = _anlage(con, aid)
        if not a:
            return render(request, "fehler.html", titel="Anlage nicht gefunden", text="Diese Anlage gibt es nicht (mehr).")
        pfad = _pfad(con, a)
        kinder = con.execute(select(ih_plaetze).where(ih_plaetze.c.eltern_id == aid, ih_plaetze.c.aktiv).order_by(ih_plaetze.c.code)
                             .limit(500)).mappings().all()
        # Ersatzteile aus dem Lager: Artikel, deren Verwendung diese Tag-Nr. nennt (bis zur Stückliste in Phase 1)
        teile = []
        if a["art"] == "platz":
            teile = con.execute(select(artikel.c.nummer, artikel.c.bezeichnung, artikel.c.verwendung).where(
                artikel.c.aktiv, or_(artikel.c.verwendung.ilike(f"%{a['code']}%"),
                                     func.replace(artikel.c.verwendung, " ", "").ilike(f"%{a['code'].replace(' ', '')}%")))
                .order_by(artikel.c.nummer).limit(50)).mappings().all()
    return render(request, "ih/anlage.html", a=a, ebenen_pfad=pfad, kinder=kinder, zusatz=_zusatz(a), teile=teile, ART_TEXT=ART_TEXT)


BEARBEITBAR = ["bezeichnung", "bauteilklasse", "kategorie", "kuerzel", "hersteller", "modell", "seriennummer", "lieferant", "status",
               "bestellnummer", "leistungsnummer", "doku_url", "notiz"]


@router.get("/anlagen/{aid}/bearbeiten")
def anlage_bearbeiten_form(request: Request, aid: int):
    require_recht(request, "ih.anlagen.pflegen")
    with db.engine().connect() as con:
        a = _anlage(con, aid)
        if not a:
            return RedirectResponse("/ih/anlagen", status_code=303)
        ebenen = _ebenen(con)
    return render(request, "ih/anlage_form.html", a=a, ebenen=ebenen, ART_TEXT=ART_TEXT)


@router.post("/anlagen/{aid}/bearbeiten")
async def anlage_bearbeiten(request: Request, aid: int):
    me = require_recht(request, "ih.anlagen.pflegen")
    f = await request.form()
    werte, fehler = {}, []
    for k in BEARBEITBAR:
        v = (f.get(k) or "").strip()
        werte[k] = v or None
    if werte["doku_url"] and not werte["doku_url"].lower().startswith(("http://", "https://")):
        fehler.append("Der Dokumentations-Link muss mit http:// oder https:// beginnen.")
    try:
        werte["kritikalitaet"] = ai.kritikalitaet(f.get("kritikalitaet") or "")
    except ValueError:
        fehler.append("Kritikalität: A, B oder C.")
    werte["sicherheitsgerichtet"] = {"ja": True, "nein": False}.get(f.get("sicherheitsgerichtet") or "")
    for k in ("inbetriebnahme", "anschaffung"):
        try:
            werte[k] = ai.datum(f.get(k) or "")
        except ValueError:
            fehler.append(f"{k.capitalize()}: kein gültiges Datum.")
    for k in ("kosten", "nebenkosten"):
        try:
            werte[k] = ai.zahl(f.get(k) or "")
        except ValueError:
            fehler.append(f"{k.capitalize()}: keine gültige Zahl.")
    eltern = f.get("eltern_id") or ""
    werte["eltern_id"] = int(eltern) if eltern.isdigit() else None
    with db.schreiben() as con:
        a = _anlage(con, aid)
        if not a:
            return RedirectResponse("/ih/anlagen", status_code=303)
        if werte["eltern_id"] == aid or (werte["eltern_id"] and any(p["id"] == aid for p in _pfad(con, {"eltern_id": werte["eltern_id"]}))):
            fehler.append("Eine Anlage kann nicht unter sich selbst hängen.")
        if fehler:
            ebenen = _ebenen(con)
            return render(request, "ih/anlage_form.html", a={**a, **werte}, ebenen=ebenen, fehler=" ".join(fehler), ART_TEXT=ART_TEXT)
        geaendert = {k: [str(a[k]) if a[k] is not None else None, str(v) if v is not None else None] for k, v in werte.items() if a[k] != v}
        if geaendert:
            con.execute(update(ih_plaetze).where(ih_plaetze.c.id == aid).values(geaendert_am=datetime.now(), **werte))
            audit(con, me["username"], "Anlage geändert", a["code"], geaendert)
    flash(request, "Gespeichert." if geaendert else "Keine Änderungen.")
    return RedirectResponse(f"/ih/anlagen/{aid}", status_code=303)


# ------------------------------------------------------------------ Asset-Import
@router.get("/import")
def import_liste(request: Request):
    require_recht(request, "ih.import")
    with db.engine().connect() as con:
        laeufe = con.execute(select(ih_import_laeufe).order_by(ih_import_laeufe.c.id.desc()).limit(30)).mappings().all()
    return render(request, "ih/import.html", laeufe=laeufe)


@router.post("/import")
async def import_hochladen(request: Request, datei: UploadFile | None = None, blatt: str = Form("")):
    me = require_recht(request, "ih.import")
    if datei is None or not datei.filename:
        flash(request, "Bitte eine Datei auswählen.", "fehler")
        return RedirectResponse("/ih/import", status_code=303)
    inhalt = await datei.read(ai.MAX_DATEI + 1)
    try:
        info = ai.lesen_mit_info(datei.filename, inhalt, blatt.strip())
    except ai.ImportFehler as e:
        flash(request, f"{datei.filename}: {e}", "fehler")
        return RedirectResponse("/ih/import", status_code=303)
    zuordnung = ai.vorschlag(info["spalten"], info["zeilen"])
    optionen = {**ai.Optionen().als_dict(), "blatt": info["blatt"], "blaetter": info["blaetter"]}
    with db.schreiben() as con:
        lid = con.execute(insert(ih_import_laeufe).values(
            dateiname=datei.filename[:300], benutzer=me["username"], status="neu", zeit=datetime.now(),
            spalten=json.dumps(info["spalten"], ensure_ascii=False), zuordnung=json.dumps(zuordnung),
            optionen=json.dumps(optionen, ensure_ascii=False), zeilen=len(info["zeilen"]))).inserted_primary_key[0]
        con.execute(insert(ih_import_zeilen), [{"lauf_id": lid, "nr": i, "werte": json.dumps(z, ensure_ascii=False)}
                                               for i, z in enumerate(info["zeilen"], start=1)])
        audit(con, me["username"], "Asset-Import hochgeladen", datei.filename, {"zeilen": len(info["zeilen"]), "blatt": info["blatt"]})
    return RedirectResponse(f"/ih/import/{lid}", status_code=303)


def _lauf(con, lid: int) -> dict | None:
    r = con.execute(select(ih_import_laeufe).where(ih_import_laeufe.c.id == lid)).mappings().first()
    if not r:
        return None
    lauf = dict(r)
    for k in ("spalten", "zuordnung", "optionen", "ergebnis"):
        lauf[k] = json.loads(lauf[k]) if lauf[k] else None
    return lauf


def _zeilen(con, lid: int) -> list[tuple[int, list[str]]]:
    return [(nr, json.loads(w)) for nr, w in con.execute(
        select(ih_import_zeilen.c.nr, ih_import_zeilen.c.werte).where(ih_import_zeilen.c.lauf_id == lid).order_by(ih_import_zeilen.c.nr))]


@router.get("/import/{lid}")
def import_lauf(request: Request, lid: int, zeige: str = ""):
    require_recht(request, "ih.import")
    with db.engine().connect() as con:
        lauf = _lauf(con, lid)
        if not lauf:
            return RedirectResponse("/ih/import", status_code=303)
        roh = _zeilen(con, lid)
        beispiele = []
        for i in range(len(lauf["spalten"])):
            werte = [w[i] for _, w in roh if i < len(w) and w[i].strip()]
            beispiele.append((werte[:3], len(werte)))
        auswahl = []
        if lauf["ergebnis"]:
            q = select(ih_import_zeilen).where(ih_import_zeilen.c.lauf_id == lid)
            if zeige in ERGEBNIS_TEXT:
                q = q.where(ih_import_zeilen.c.ergebnis == zeige)
            elif zeige == "hinweise":
                q = q.where(ih_import_zeilen.c.meldungen.isnot(None), ih_import_zeilen.c.ergebnis != "fehler")
            else:
                q = q.where(or_(ih_import_zeilen.c.ergebnis == "fehler", ih_import_zeilen.c.meldungen.isnot(None)))
            ci = lauf["zuordnung"].index("code") if "code" in lauf["zuordnung"] else 0
            for r in con.execute(q.order_by(ih_import_zeilen.c.nr).limit(300)).mappings():
                w = json.loads(r["werte"])
                auswahl.append({"nr": r["nr"], "code": w[ci] if ci < len(w) else "", "ergebnis": r["ergebnis"],
                                "meldungen": json.loads(r["meldungen"] or "[]"), "aenderungen": json.loads(r["aenderungen"] or "{}")})
    return render(request, "ih/import_lauf.html", lauf=lauf, beispiele=beispiele, FELDER=ai.FELDER, auswahl=auswahl, zeige=zeige,
                  ERGEBNIS_TEXT=ERGEBNIS_TEXT)


def _formular(lauf: dict, f) -> tuple[list[str], ai.Optionen]:
    zuordnung = [(f.get(f"spalte_{i}") or "") for i in range(len(lauf["spalten"]))]
    optionen = ai.Optionen(bereiche_bilden=f.get("bereiche_bilden") == "on", unit_aus_tag=f.get("unit_aus_tag") == "on",
                           leere_ueberschreiben=f.get("leere_ueberschreiben") == "on")
    return zuordnung, optionen


@router.post("/import/{lid}/pruefen")
async def import_pruefen(request: Request, lid: int):
    """Zuordnung speichern, prüfen und Testlauf: Der Import läuft vollständig in einer Transaktion, die zurückgerollt wird."""
    require_recht(request, "ih.import")
    f = await request.form()
    with db.engine().connect() as con:
        lauf = _lauf(con, lid)
    if not lauf:
        return RedirectResponse("/ih/import", status_code=303)
    if lauf["status"] == "uebernommen":
        flash(request, "Dieser Import ist bereits übernommen. Für eine erneute Übernahme die Datei neu hochladen.", "fehler")
        return RedirectResponse(f"/ih/import/{lid}", status_code=303)
    zuordnung, optionen = _formular(lauf, f)
    opt_json = json.dumps({**lauf["optionen"], **optionen.als_dict()}, ensure_ascii=False)
    try:
        ai.zuordnung_pruefen(lauf["spalten"], zuordnung)
    except ai.ImportFehler as e:
        with db.schreiben() as con:
            con.execute(update(ih_import_laeufe).where(ih_import_laeufe.c.id == lid).values(
                zuordnung=json.dumps(zuordnung), optionen=opt_json, ergebnis=None, pruef_kennung=None, status="neu"))
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/ih/import/{lid}", status_code=303)
    con = db.engine().execution_options(schreiben=True).connect()
    try:
        tr = con.begin()
        try:
            plan = ai.planen(con, lauf["spalten"], zuordnung, optionen, _zeilen(con, lid))
            ai.ausfuehren(con, plan, lid)
            testlauf_ok, testlauf_fehler = True, ""
        except Exception as e:  # z. B. Datenbankregel verletzt – genau das soll der Testlauf finden
            testlauf_ok, testlauf_fehler = False, str(e)[:300]
        finally:
            tr.rollback()  # Testlauf: nichts bleibt in der Datenbank
    finally:
        con.close()
    with db.schreiben() as con:
        if testlauf_ok:
            ai.zeilen_ergebnis(con, plan, lid)
        ergebnis = {**(plan.zusammenfassung if testlauf_ok else {}), "testlauf_ok": testlauf_ok, "testlauf_fehler": testlauf_fehler,
                    "geprueft_am": datetime.now().isoformat(timespec="seconds"),
                    "neue_ebenen": [g["code"] for g in plan.gruppen] if testlauf_ok else []}
        con.execute(update(ih_import_laeufe).where(ih_import_laeufe.c.id == lid).values(
            zuordnung=json.dumps(zuordnung), optionen=opt_json, ergebnis=json.dumps(ergebnis, ensure_ascii=False),
            status="geprueft" if testlauf_ok else "neu", pruef_kennung=ai.kennung(zuordnung, optionen, con, lid) if testlauf_ok else None))
    flash(request, "Prüfung und Testlauf abgeschlossen – es wurde nichts verändert." if testlauf_ok
          else f"Testlauf fehlgeschlagen: {testlauf_fehler}", "ok" if testlauf_ok else "fehler")
    return RedirectResponse(f"/ih/import/{lid}#ergebnis", status_code=303)


@router.post("/import/{lid}/uebernehmen")
def import_uebernehmen(request: Request, lid: int, bestaetigt: str = Form("")):
    me = require_recht(request, "ih.import")
    with db.engine().connect() as con:
        lauf = _lauf(con, lid)
    if not lauf or lauf["status"] != "geprueft" or not lauf["pruef_kennung"]:
        flash(request, "Bitte zuerst „Prüfen und Testlauf“ ausführen.", "fehler")
        return RedirectResponse(f"/ih/import/{lid}", status_code=303)
    if bestaetigt != "ja":
        flash(request, "Bitte die Übernahme bestätigen.", "fehler")
        return RedirectResponse(f"/ih/import/{lid}#ergebnis", status_code=303)
    optionen = ai.Optionen.aus(lauf["optionen"])
    cfg = request.app.state.cfg
    try:
        from ..services.sicherung import einzel_sicherung
        gesichert = einzel_sicherung(cfg, cfg.path(cfg.backup.ordner), name="vor_import", aufbewahren_tage=365).name
    except Exception as e:
        flash(request, f"Sicherung vor dem Import fehlgeschlagen ({e}). Import nicht ausgeführt.", "fehler")
        return RedirectResponse(f"/ih/import/{lid}", status_code=303)
    with db.schreiben() as con:
        if ai.kennung(lauf["zuordnung"], optionen, con, lid) != lauf["pruef_kennung"]:
            erg = None
        else:
            plan = ai.planen(con, lauf["spalten"], lauf["zuordnung"], optionen, _zeilen(con, lid))
            erg = ai.ausfuehren(con, plan, lid)
            ergebnis = {**lauf["ergebnis"], **erg, "uebernommen_von": me["username"], "sicherung": gesichert,
                        "neue_ebenen": [g["code"] for g in plan.gruppen]}
            con.execute(update(ih_import_laeufe).where(ih_import_laeufe.c.id == lid).values(
                status="uebernommen", uebernommen_am=datetime.now(), ergebnis=json.dumps(ergebnis, ensure_ascii=False)))
            audit(con, me["username"], "Asset-Import übernommen", lauf["dateiname"],
                  {"lauf": lid, "neu": erg["neu"], "geaendert": erg["geaendert"], "fehler": erg["fehler"], "sicherung": gesichert})
    if erg is None:
        flash(request, "Die Anlagen wurden seit der Prüfung verändert. Bitte erneut prüfen.", "fehler")
        return RedirectResponse(f"/ih/import/{lid}", status_code=303)
    flash(request, f"Import übernommen: {erg['neu']} neu, {erg['geaendert']} geändert, {erg['fehler']} Zeilen übersprungen. "
                   f"Der vorherige Stand ist als „{gesichert}“ gesichert.")
    return RedirectResponse(f"/ih/import/{lid}", status_code=303)


@router.post("/import/{lid}/verwerfen")
def import_verwerfen(request: Request, lid: int):
    me = require_recht(request, "ih.import")
    with db.schreiben() as con:
        lauf = _lauf(con, lid)
        if lauf and lauf["status"] != "uebernommen":
            con.execute(delete(ih_import_laeufe).where(ih_import_laeufe.c.id == lid))
            audit(con, me["username"], "Asset-Import verworfen", lauf["dateiname"], {"lauf": lid})
            flash(request, "Import verworfen.")
        elif lauf:
            flash(request, "Ein übernommener Import bleibt zur Nachverfolgung erhalten.", "fehler")
    return RedirectResponse("/ih/import", status_code=303)


@router.get("/import/{lid}/bericht.xlsx")
def import_bericht(request: Request, lid: int):
    require_recht(request, "ih.import")
    with db.engine().connect() as con:
        lauf = _lauf(con, lid)
        if not lauf:
            return RedirectResponse("/ih/import", status_code=303)
        ci = lauf["zuordnung"].index("code") if "code" in lauf["zuordnung"] else 0
        zeilen = []
        for r in con.execute(select(ih_import_zeilen).where(ih_import_zeilen.c.lauf_id == lid).order_by(ih_import_zeilen.c.nr)).mappings():
            w = json.loads(r["werte"])
            meld = json.loads(r["meldungen"] or "[]")
            aend = json.loads(r["aenderungen"] or "{}")
            zeilen.append([r["nr"], w[ci] if ci < len(w) else "", ERGEBNIS_TEXT.get(r["ergebnis"] or "", "nicht geprüft"),
                           "; ".join(t for a, t in meld if a == "fehler"), "; ".join(t for a, t in meld if a == "hinweis"),
                           "; ".join(f"{k}: {v[0]} → {v[1]}" for k, v in aend.items())])
    daten = tabelle_xlsx("Importbericht", ["Datenzeile", "Tag-Nr.", "Ergebnis", "Fehler", "Hinweise", "Änderungen"], zeilen,
                         [10, 22, 20, 50, 60, 60])
    name = f"Importbericht_{lid}_{date.today():%Y%m%d}.xlsx"
    return Response(daten, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
