"""Instandhaltung – Montageunterstützung (ab 2.12.0): Stutzenübersicht und Montageprotokolle.

Rechte (app/rechte.py): ansehen (alle), erfassen (Operator bis Manager), korrigieren (abgeschlossene Protokolle: Ingenieur, Manager),
stutzen (Stutzenübersicht pflegen: Schichtführer, Ingenieur, Manager). Logik in app/services/montage.py.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select, update

from .. import db
from ..db import artikel, ih_plaetze, mt_protokolle, mt_stutzen
from ..rechte import hat_recht
from ..services import montage as mt
from ..services.excel import tabelle_xlsx
from ..services.lager import BuchungsFehler, audit, fmt_num
from ..web import flash, render, require_recht

router = APIRouter(prefix="/ih/montage")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _darf(request, recht: str) -> bool:
    from ..web import current_user
    return hat_recht(current_user(request), recht, request.app.state.cfg)


def _datum(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


@router.get("")
def start(request: Request):
    require_recht(request, "ih.montage.ansehen")
    return RedirectResponse("/ih/montage/stutzen", status_code=303)


# ------------------------------------------------------------------ Stutzenübersicht
@router.get("/stutzen")
def stutzen_liste(request: Request, q: str = "", gruppe: str = "", archiv: int = 0):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        rows = mt.stutzen_liste(con, q, gruppe, bool(archiv))
        gr = mt.gruppen(con)
    return render(request, "ih/mt_stutzen.html", rows=rows, q=q, gruppe=gruppe, gruppen=gr, archiv=archiv)


@router.get("/stutzen/export.xlsx")
def stutzen_export(request: Request):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        rows = mt.stutzen_liste(con)
    kopf = ["Gruppe", "Bezeichnung", "Stutzen", "Dichtung Pos.", "Dichtungsart", "Dichtungsdurchmesser", "Artikel-Nr. (Auftragsnummer)",
            "Nenndicke [mm]", "Soll Drehmoment [Nm]", "Schrauben Länge Soll [mm]", "Gewinde", "Anzahl Schrauben", "Typ / Norm",
            "Werkstoff / Klasse", "Anlage / Reaktor", "Schmiermittel", "Bemerkung"]
    z = []
    for s in rows:
        for d in s["dichtungen"] or [{}]:
            z.append([s["gruppe"], s["bezeichnung"], s["kuerzel"], d.get("pos"), d.get("dichtungsart"), d.get("durchmesser"), d.get("artikel_nr"),
                      d.get("nenndicke"), s["drehmoment"], s["schraube_laenge"], s["gewinde"], s["schrauben_anzahl"], s["schraube_typ"],
                      s["schraube_werkstoff"], s["anlage"], s["schmiermittel"], s["bemerkung"]])
    return Response(tabelle_xlsx("Stutzen Übersicht", kopf, z), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="Stutzen_Uebersicht_{date.today():%Y-%m-%d}.xlsx"'})


def _stutzen_ctx(con, s: dict | None = None, **extra) -> dict:
    return dict(s=s or {"dichtungen": []}, gruppen=mt.gruppen(con),
                tags=[(r.code, r.bezeichnung or "") for r in con.execute(select(ih_plaetze.c.code, ih_plaetze.c.bezeichnung)
                                                                           .where(ih_plaetze.c.aktiv, ih_plaetze.c.art == "platz").order_by(ih_plaetze.c.code))],
                lager_artikel=[(r.nummer, r.bezeichnung) for r in con.execute(select(artikel.c.nummer, artikel.c.bezeichnung)
                                                                              .where(artikel.c.aktiv).order_by(artikel.c.nummer))], **extra)


def _stutzen_form(con, f) -> tuple[dict, list[dict]]:
    daten = {k: f.get(k) for k in mt.STUTZEN_FELDER}
    dicht = []
    for i in range(3):
        d = {k: f.get(f"d{i}_{k}") for k in ("einbauort", "dichtungsart", "durchmesser", "artikel_nr", "nenndicke", "menge")}
        lager_nr = (f.get(f"d{i}_lager") or "").split(" – ")[0].strip()
        d["artikel_id"] = None
        if lager_nr:
            aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == lager_nr)).scalar()
            if not aid:
                raise BuchungsFehler(f"Dichtung {i + 1}: Lagerartikel {lager_nr} gibt es nicht.")
            d["artikel_id"] = aid
        dicht.append(d)
    return daten, dicht


def _platz_id(con, text: str | None) -> int | None:
    code = (text or "").split(" – ")[0].strip()
    if not code:
        return None
    from ..services.asset_import import schluessel
    pid = con.execute(select(ih_plaetze.c.id).where(ih_plaetze.c.schluessel == schluessel(code), ih_plaetze.c.art == "platz")).scalar()
    if not pid:
        raise BuchungsFehler(f"Tag-Nr. {code} gibt es nicht unter Instandhaltung → Anlagen.")
    return pid


@router.get("/stutzen/neu")
def stutzen_neu_form(request: Request, kopie: int = 0):
    require_recht(request, "ih.montage.stutzen")
    with db.engine().connect() as con:
        s = mt.stutzen_get(con, kopie) if kopie else None
        if s:
            s = {**s, "id": None, "kuerzel": ""}
        return render(request, "ih/mt_stutzen_form.html", **_stutzen_ctx(con, s))


@router.post("/stutzen/neu")
async def stutzen_neu(request: Request):
    me = require_recht(request, "ih.montage.stutzen")
    f = await request.form()
    try:
        with db.schreiben() as con:
            daten, dicht = _stutzen_form(con, f)
            sid = mt.stutzen_speichern(con, None, daten, dicht, me["username"])
            con.execute(update(mt_stutzen).where(mt_stutzen.c.id == sid).values(platz_id=_platz_id(con, f.get("tag"))))
            audit(con, me["username"], "Stutzen angelegt", daten.get("kuerzel") or "", {"id": sid})
    except BuchungsFehler as e:
        with db.engine().connect() as con:
            return render(request, "ih/mt_stutzen_form.html", fehler=str(e), **_stutzen_ctx(con, _form_zurueck(f)))
    flash(request, f"Stutzen {daten['kuerzel']} angelegt.")
    return RedirectResponse(f"/ih/montage/stutzen/{sid}", status_code=303)


def _form_zurueck(f) -> dict:
    s = {k: f.get(k) for k in mt.STUTZEN_FELDER}
    s["tag"] = f.get("tag")
    s["dichtungen"] = [{k: f.get(f"d{i}_{k}") for k in ("einbauort", "dichtungsart", "durchmesser", "artikel_nr", "nenndicke", "menge")}
                       | {"lager_text": f.get(f"d{i}_lager")} for i in range(3)]
    return s


@router.get("/stutzen/{sid}")
def stutzen_detail(request: Request, sid: int):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        s = mt.stutzen_get(con, sid)
        if not s:
            return render(request, "fehler.html", titel="Stutzen nicht gefunden", text="Diesen Stutzen gibt es nicht.")
        tag = con.execute(select(ih_plaetze.c.id, ih_plaetze.c.code, ih_plaetze.c.bezeichnung).where(ih_plaetze.c.id == s["platz_id"])).mappings().first() if s["platz_id"] else None
        prot = mt.liste(con, stutzen_id=sid, limit=50)
    return render(request, "ih/mt_stutzen_detail.html", s=s, tag=tag, prot=prot, svg=mt.skizze_svg(s["schrauben_anzahl"] or 0, breite="220"),
                  STATUS=mt.STATUS)


@router.get("/stutzen/{sid}/bearbeiten")
def stutzen_bearbeiten_form(request: Request, sid: int):
    require_recht(request, "ih.montage.stutzen")
    with db.engine().connect() as con:
        s = mt.stutzen_get(con, sid)
        if not s:
            return RedirectResponse("/ih/montage/stutzen", status_code=303)
        if s["platz_id"]:
            s["tag"] = con.execute(select(ih_plaetze.c.code).where(ih_plaetze.c.id == s["platz_id"])).scalar()
        for d in s["dichtungen"]:
            d["lager_text"] = d.get("lager_nr") or ""
            d["nenndicke"] = fmt_num(d["nenndicke"]) if d["nenndicke"] is not None else ""
            d["menge"] = fmt_num(d["menge"]) if d["menge"] is not None else ""
        return render(request, "ih/mt_stutzen_form.html", **_stutzen_ctx(con, s))


@router.post("/stutzen/{sid}/bearbeiten")
async def stutzen_bearbeiten(request: Request, sid: int):
    me = require_recht(request, "ih.montage.stutzen")
    f = await request.form()
    try:
        with db.schreiben() as con:
            if not con.execute(select(mt_stutzen.c.id).where(mt_stutzen.c.id == sid)).scalar():
                raise BuchungsFehler("Stutzen nicht gefunden.")
            daten, dicht = _stutzen_form(con, f)
            mt.stutzen_speichern(con, sid, daten, dicht, me["username"])
            con.execute(update(mt_stutzen).where(mt_stutzen.c.id == sid).values(platz_id=_platz_id(con, f.get("tag"))))
            audit(con, me["username"], "Stutzen geändert", daten.get("kuerzel") or "", {"id": sid})
    except BuchungsFehler as e:
        with db.engine().connect() as con:
            return render(request, "ih/mt_stutzen_form.html", fehler=str(e), **_stutzen_ctx(con, {**_form_zurueck(f), "id": sid}))
    flash(request, f"Stutzen {daten['kuerzel']} gespeichert.")
    return RedirectResponse(f"/ih/montage/stutzen/{sid}", status_code=303)


@router.post("/stutzen/{sid}/archivieren")
async def stutzen_archivieren(request: Request, sid: int):
    me = require_recht(request, "ih.montage.stutzen")
    f = await request.form()
    aktiv = f.get("aktiv") == "1"
    with db.schreiben() as con:
        k = con.execute(select(mt_stutzen.c.kuerzel).where(mt_stutzen.c.id == sid)).scalar()
        con.execute(update(mt_stutzen).where(mt_stutzen.c.id == sid).values(aktiv=aktiv))
        audit(con, me["username"], "Stutzen reaktiviert" if aktiv else "Stutzen archiviert", k or str(sid))
    flash(request, f"Stutzen {k} {'wieder aktiv' if aktiv else 'archiviert (Protokolle bleiben erhalten)'}.")
    return RedirectResponse(f"/ih/montage/stutzen/{sid}", status_code=303)


@router.get("/stutzen-import")
def import_form(request: Request):
    require_recht(request, "ih.montage.stutzen")
    return render(request, "ih/mt_import.html", ergebnis=None)


@router.post("/stutzen-import")
async def import_ausfuehren(request: Request):
    me = require_recht(request, "ih.montage.stutzen")
    f = await request.form()
    datei = f.get("datei")
    if not isinstance(datei, UploadFile) and not hasattr(datei, "read"):
        flash(request, "Bitte eine Excel-Datei auswählen.", "fehler")
        return RedirectResponse("/ih/montage/stutzen-import", status_code=303)
    inhalt = await datei.read()
    try:
        if len(inhalt) > 20 * 1024 * 1024:
            raise BuchungsFehler("Die Datei ist größer als 20 MB.")
        gelesen = mt.import_lesen(inhalt, f.get("gruppe_anfang") or "")
        if f.get("probe") == "1":
            return render(request, "ih/mt_import.html", ergebnis=None, vorschau=gelesen, gruppe_anfang=f.get("gruppe_anfang") or "",
                          dateiname=getattr(datei, "filename", ""))
        with db.schreiben() as con:
            erg = mt.import_uebernehmen(con, gelesen, me["username"])
            audit(con, me["username"], "Stutzenübersicht importiert", getattr(datei, "filename", "") or "", erg)
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse("/ih/montage/stutzen-import", status_code=303)
    flash(request, f"Import: {erg['neu']} Stutzen neu, {erg['geaendert']} ergänzt/aktualisiert, {erg['dichtungen']} Dichtungen gelesen."
          + (f" {len(gelesen['hinweise'])} Hinweis(e) – siehe unten." if gelesen["hinweise"] else ""))
    return render(request, "ih/mt_import.html", ergebnis=erg, hinweise=gelesen["hinweise"])


# ------------------------------------------------------------------ Montageprotokolle
@router.get("/protokolle")
def protokolle(request: Request, q: str = "", status: str = "", stutzen: int = 0, von: str = "", bis: str = ""):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        rows = mt.liste(con, q, status, stutzen or None, _datum(von), _datum(bis))
        st = mt.stutzen_get(con, stutzen) if stutzen else None
    return render(request, "ih/mt_protokolle.html", rows=rows, q=q, status=status, stutzen=st, von=von, bis=bis, STATUS=mt.STATUS,
                  LECKTEST=mt.LECKTEST)


@router.get("/protokolle/export.xlsx")
def protokolle_export(request: Request, q: str = "", status: str = "", stutzen: int = 0, von: str = "", bis: str = ""):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        rows = mt.liste(con, q, status, stutzen or None, _datum(von), _datum(bis), limit=100_000)
    kopf = ["Nummer", "Status", "Datum", "Stutzen", "Anlage / Reaktor", "Monteur", "Prüfer", "Arbeitsauftrag", "Schrauben", "Lecktest",
            "Montage abgeschlossen", "Angelegt von"]
    z = [[r["nummer"], mt.STATUS.get(r["status"]), r["datum"], r["stutzen_bez"] or r["stutzen"], r["anlage"], r["monteur"], r["pruefer"],
          r["arbeitsauftrag"], r["schrauben_anzahl"], mt.LECKTEST.get(r["lecktest"], ""), {"ja": "Ja", "nein": "Nein"}.get(r["montage_abgeschlossen"], ""),
          r["erstellt_von"]] for r in rows]
    return Response(tabelle_xlsx("Montageprotokolle", kopf, z), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="Montageprotokolle_{date.today():%Y-%m-%d}.xlsx"'})


def _stutzen_json(con) -> list[dict]:
    aus = []
    for s in mt.stutzen_liste(con):
        v = mt.vorbelegung(s, 1)
        aus.append({"id": s["id"], "label": s["label"], "kuerzel": s["kuerzel"], "n": s["schrauben_anzahl"], "anlage": s["anlage"] or "",
                    "schmiermittel": s["schmiermittel"] or "", "dichtungen": v["dichtungen"], "schraube": v["schrauben"][0] if v["schrauben"] else {},
                    "ungeklaert": s["ungeklaert"]})
    return aus


def _form(request, con, p: dict, **extra):
    me = request.session.get("user") or {}
    p = dict(p)
    p["schrauben_anzeige"] = mt.ditto_anzeige(p.get("schrauben") or [])
    return render(request, "ih/mt_protokoll_form.html", p=p, stutzen_daten=_stutzen_json(con), STATUS=mt.STATUS, LECKTEST=mt.LECKTEST,
                  SCHRAUBEN_FELDER=mt.SCHRAUBEN_FELDER, DITTO_FELDER=mt.DITTO_FELDER, MAX=mt.MAX_SCHRAUBEN, ich=me.get("name") or "", **extra)


@router.get("/protokolle/neu")
def protokoll_neu_form(request: Request, stutzen: int = 0):
    require_recht(request, "ih.montage.erfassen")
    with db.engine().connect() as con:
        st = mt.stutzen_get(con, stutzen) if stutzen else None
        v = mt.vorbelegung(st)
        p = {"id": None, "status": "entwurf", "datum": date.today(), "stutzen_id": st["id"] if st else None, "stutzen": st["kuerzel"] if st else "",
             "stutzen_bez": st["label"] if st else "", "reihenfolge": [], **v}
        return _form(request, con, p)


def _stutzen_aus_form(con, f) -> dict | None:
    sid = f.get("stutzen_id")
    if str(sid or "").isdigit():
        return mt.stutzen_get(con, int(sid))
    return None


async def _speichern(request: Request, pid: int | None):
    me = require_recht(request, "ih.montage.erfassen")
    f = await request.form()
    aktion = f.get("aktion") or "speichern"
    korrigieren = _darf(request, "ih.montage.korrigieren")
    try:
        with db.engine().connect() as con:
            st = _stutzen_aus_form(con, f)
            daten = mt.aus_formular(f, st)
        abschliessen = aktion == "abschliessen"
        fehlend = mt.fehlende_angaben(daten) if abschliessen else []
        if fehlend and f.get("trotzdem") != "1":
            abschliessen = False  # erst speichern, dann nachfragen
        with db.schreiben() as con:
            alt = con.execute(select(mt_protokolle.c.status, mt_protokolle.c.nummer, mt_protokolle.c.geaendert_am, mt_protokolle.c.geaendert_von)
                              .where(mt_protokolle.c.id == pid)).first() if pid else None
            if pid and not alt:
                raise BuchungsFehler("Protokoll nicht gefunden.")
            stand = f.get("stand") or ""
            if alt and stand and alt.geaendert_am and alt.geaendert_am.isoformat() != stand:
                raise BuchungsFehler(f"{alt.nummer} wurde inzwischen von {alt.geaendert_von} geändert ({alt.geaendert_am:%d.%m. %H:%M}). "
                                     "Ihre Eingaben stehen unten – bitte prüfen und erneut speichern (überschreibt den neueren Stand).")
            war_abgeschlossen = bool(alt and alt.status == "abgeschlossen")
            pid = mt.speichern(con, pid, daten, me["username"], abschliessen=abschliessen and not war_abgeschlossen,
                               darf_korrigieren=korrigieren, grund=f.get("grund") or "")
            nummer = con.execute(select(mt_protokolle.c.nummer).where(mt_protokolle.c.id == pid)).scalar()
            audit(con, me["username"], "Montageprotokoll korrigiert" if war_abgeschlossen else
                  ("Montageprotokoll abgeschlossen" if abschliessen else "Montageprotokoll gespeichert"), nummer, {"stutzen": daten.get("stutzen")})
    except BuchungsFehler as e:
        with db.engine().connect() as con:
            st = _stutzen_aus_form(con, f)
            try:
                p = mt.aus_formular(f, st)
            except BuchungsFehler:
                p = mt.vorbelegung(st)
            vorh = mt.laden(con, pid) if pid else None
            p.update(id=pid, status=vorh["status"] if vorh else "entwurf", nummer=vorh["nummer"] if vorh else None,
                     verlauf=vorh["verlauf"] if vorh else [], geaendert_am=vorh["geaendert_am"] if vorh else None)
            p.setdefault("schrauben", [])
            return _form(request, con, p, fehler=str(e), grund=f.get("grund") or "")
    if fehlend and aktion == "abschliessen" and f.get("trotzdem") != "1":
        flash(request, f"{nummer} gespeichert, aber noch nicht abgeschlossen – es fehlt: " + "; ".join(fehlend) + ".", "fehler")
        return RedirectResponse(f"/ih/montage/protokolle/{pid}?fehlend=1", status_code=303)
    if aktion == "abschliessen" and not (alt and alt.status == "abgeschlossen"):
        flash(request, f"{nummer} abgeschlossen. Jetzt drucken und unterschreiben lassen.")
        return RedirectResponse(f"/ih/montage/protokolle/{pid}", status_code=303)
    flash(request, f"{nummer} gespeichert." + (" Werte können jederzeit nachgetragen werden." if not alt or alt.status != "abgeschlossen" else ""))
    return RedirectResponse(f"/ih/montage/protokolle/{pid}", status_code=303)


@router.post("/protokolle/neu")
async def protokoll_neu(request: Request):
    return await _speichern(request, None)


@router.get("/protokolle/blanko")
def blanko(request: Request, n: int = 20, stutzen: int = 0):
    """Leeres Blatt (z. B. für Arbeiten ohne PC): mit Stutzen vorausgefüllte Soll-Werte, sonst ganz leer."""
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        st = mt.stutzen_get(con, stutzen) if stutzen else None
    n = max(1, min(int((st or {}).get("schrauben_anzahl") or n), mt.MAX_SCHRAUBEN))
    p = {"nummer": "", "status": "", "stutzen": st["kuerzel"] if st else "", "stutzen_bez": st["label"] if st else "", "reihenfolge": [],
         **mt.vorbelegung(st, n)}
    if not st:
        p["schrauben"] = [{f: "" for f in mt.SCHRAUBEN_FELDER} for _ in range(n)]
    p["schrauben_anzahl"] = n
    return _druck(request, p, blanko=True)


def _druck(request, p: dict, blanko: bool = False):
    p = dict(p)
    p["schrauben_anzeige"] = mt.ditto_anzeige(p.get("schrauben") or [])
    for i, z in enumerate(p["schrauben_anzeige"]):
        z["kennzeichnung"] = "" if blanko else mt.kennzeichnung(p.get("stutzen"), i + 1, (p["schrauben"][i] or {}).get("ist_nm"))
    return render(request, "ih/mt_druck.html", p=p, svg=mt.skizze_svg(p.get("schrauben_anzahl") or 0, p.get("reihenfolge"), breite="100%"),
                  blanko=blanko, LECKTEST=mt.LECKTEST, STATUS=mt.STATUS)


@router.get("/protokolle/{pid}")
def protokoll(request: Request, pid: int, fehlend: int = 0, korrektur: int = 0):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        p = mt.laden(con, pid)
        if not p:
            return render(request, "fehler.html", titel="Protokoll nicht gefunden", text="Dieses Montageprotokoll gibt es nicht.")
        darf_erfassen = _darf(request, "ih.montage.erfassen")
        darf_korr = _darf(request, "ih.montage.korrigieren")
        if (p["status"] == "entwurf" and darf_erfassen) or (korrektur and darf_korr):
            return _form(request, con, p, fehlende=mt.fehlende_angaben(p) if fehlend else None, korrektur=p["status"] == "abgeschlossen")
    p["schrauben_anzeige"] = mt.ditto_anzeige(p["schrauben"])
    for i, z in enumerate(p["schrauben_anzeige"]):
        z["kennzeichnung"] = mt.kennzeichnung(p["stutzen"], i + 1, p["schrauben"][i].get("ist_nm"))
    return render(request, "ih/mt_protokoll.html", p=p, svg=mt.skizze_svg(p["schrauben_anzahl"] or 0, p["reihenfolge"]), STATUS=mt.STATUS,
                  LECKTEST=mt.LECKTEST)


@router.post("/protokolle/{pid}")
async def protokoll_speichern(request: Request, pid: int):
    return await _speichern(request, pid)


@router.get("/protokolle/{pid}/druck")
def druck(request: Request, pid: int):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        p = mt.laden(con, pid)
    if not p:
        return RedirectResponse("/ih/montage/protokolle", status_code=303)
    return _druck(request, p)


@router.get("/protokolle/{pid}/excel")
def excel(request: Request, pid: int):
    require_recht(request, "ih.montage.ansehen")
    with db.engine().connect() as con:
        p = mt.laden(con, pid)
    if not p:
        return RedirectResponse("/ih/montage/protokolle", status_code=303)
    name = f"Montageprotokoll_{p['nummer']}_{(p['stutzen'] or '').replace(' ', '')}.xlsx"
    return Response(mt.excel(p, request.app.state.cfg.server.firmenname), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/protokolle/{pid}/oeffnen")
async def oeffnen(request: Request, pid: int):
    me = require_recht(request, "ih.montage.korrigieren")
    f = await request.form()
    try:
        with db.schreiben() as con:
            mt.wieder_oeffnen(con, pid, me["username"], f.get("grund") or "")
            nr = con.execute(select(mt_protokolle.c.nummer).where(mt_protokolle.c.id == pid)).scalar()
            audit(con, me["username"], "Montageprotokoll wieder geöffnet", nr or str(pid), {"grund": f.get("grund")})
        flash(request, f"{nr} ist wieder in Arbeit und kann von allen mit Erfassungsrecht ergänzt werden.")
    except BuchungsFehler as e:
        flash(request, str(e), "fehler")
    return RedirectResponse(f"/ih/montage/protokolle/{pid}", status_code=303)


@router.post("/protokolle/{pid}/loeschen")
async def loeschen(request: Request, pid: int):
    me = require_recht(request, "ih.montage.erfassen")
    with db.schreiben() as con:
        p = con.execute(select(mt_protokolle.c.status, mt_protokolle.c.nummer, mt_protokolle.c.erstellt_von).where(mt_protokolle.c.id == pid)).first()
        if not p:
            return RedirectResponse("/ih/montage/protokolle", status_code=303)
        if p.status != "entwurf":
            flash(request, "Abgeschlossene Protokolle werden nicht gelöscht.", "fehler")
            return RedirectResponse(f"/ih/montage/protokolle/{pid}", status_code=303)
        if p.erstellt_von != me["username"] and not _darf(request, "ih.montage.korrigieren"):
            flash(request, "Löschen darf nur, wer das Protokoll angelegt hat (oder Ingenieur/Manager).", "fehler")
            return RedirectResponse(f"/ih/montage/protokolle/{pid}", status_code=303)
        con.execute(mt_protokolle.delete().where(mt_protokolle.c.id == pid))
        audit(con, me["username"], "Montageprotokoll gelöscht (Entwurf)", p.nummer)
    flash(request, f"Entwurf {p.nummer} gelöscht.")
    return RedirectResponse("/ih/montage/protokolle", status_code=303)
