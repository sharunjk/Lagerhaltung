"""Instandhaltung – Schichtbuch (ab 2.8.0): Dashboard je Team, Meldungen, Übergaben, Schichtbeginn und -ende, Einrichten.

Jede Route prüft ihr Recht serverseitig (require_recht). Geschäftslogik in app/services/schichtbuch.py.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, insert, select, update

from .. import db
from ..db import benutzer_rollen, ih_auftraege, ih_plaetze, sb_mitglieder, sb_teams, sb_zeiten, users
from ..services import schichtbuch as sb
from ..services.excel import tabelle_xlsx
from ..services.lager import audit
from ..web import flash, render, require_recht

router = APIRouter(prefix="/ih/schichtbuch")
OFFEN_AUFTRAG = ("freigegeben", "in_arbeit")


def _tags(con) -> list[tuple[str, str]]:
    return [(r.code, r.bezeichnung or "") for r in con.execute(select(ih_plaetze.c.code, ih_plaetze.c.bezeichnung)
                                                               .where(ih_plaetze.c.aktiv, ih_plaetze.c.art == "platz").order_by(ih_plaetze.c.code))]


def _grunddaten() -> None:
    """Teams und Schichtzeiten beim ersten Aufruf anlegen – sonst nur lesen (keine Schreibsperre bei jedem Seitenaufruf)."""
    with db.engine().connect() as con:
        if sb.grunddaten_vorhanden(con):
            return
    with db.schreiben() as con:
        sb.sicherstellen(con)


def _datum(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


# ------------------------------------------------------------------ Dashboard
@router.get("")
def dashboard(request: Request, team: str = ""):
    me = require_recht(request, "ih.schichtbuch.ansehen")
    _grunddaten()
    jetzt = datetime.now()
    with db.engine().connect() as con:
        teams = sb.teams(con)
        mein_team = sb.team_von(con, me["id"])
        sicht = next((t for t in teams if team.isdigit() and t["id"] == int(team)), None) or mein_team
        d, z = sb.laufender_slot(con, jetzt)
        akt = sb.schicht(con, datum=d, zeit_id=z["id"])
        beginn, schluss = sb.fenster(d, z)
        nd, nz = sb.naechster_slot(con, d, z)
        n_beginn = sb.fenster(nd, nz)[0]
        naechste = sb.schicht(con, datum=nd, zeit_id=nz["id"])
        vorzeitig = (not naechste or not naechste["begonnen_am"]) and (bool(akt and akt["beendet_am"]) or jetzt >= n_beginn - sb.VORZEITIG)
        oeffnen_grund = sb.wieder_oeffnen_grund(con, akt["id"]) if akt and akt["beendet_am"] else None
        uebergaben = sb.offene_uebergaben(con)
        ueb_ids = {m["id"] for m in uebergaben}
        offene = [m for m in sb.offene(con) if m["id"] not in ueb_ids]
        diese = sb.der_schicht(con, akt["id"]) if akt else []
        letzte = sb.letzte_schichten(con, beginn, 4)
        team_letzte = sb.letzte_schichten(con, beginn, 1, team_id=sicht["id"]) if sicht else []
        seit_ab = (team_letzte[0]["beendet_am"] or team_letzte[0]["schluss"]) if team_letzte else None
        seit = sb.seit(con, seit_ab) if seit_ab else []
        haengend = sb.nicht_beendet(con, ausser=akt["id"] if akt else None)
        auftraege = con.execute(select(func.count()).select_from(ih_auftraege).where(ih_auftraege.c.status.in_(OFFEN_AUFTRAG))).scalar()
    return render(request, "ih/schichtbuch.html", teams=teams, mein_team=mein_team, sicht=sicht, akt=akt, slot_text=sb.bezeichnung(d, z),
                  slot_zeit=z, beginn=beginn, schluss=schluss, uebergaben=uebergaben, offene=offene, diese=diese, letzte=letzte,
                  team_letzte=team_letzte[0] if team_letzte else None, seit=seit, seit_ab=seit_ab, haengend=haengend,
                  auftraege=auftraege, STATUS=sb.STATUS, PRIO=sb.PRIO, jetzt=jetzt, naechste_text=sb.bezeichnung(nd, nz), n_beginn=n_beginn,
                  vorzeitig=vorzeitig, oeffnen_grund=oeffnen_grund)


@router.post("/beginnen")
async def beginnen(request: Request):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    with db.schreiben() as con:
        sb.sicherstellen(con)
        d, z = sb.laufender_slot(con)
        if f.get("naechste") == "1":  # nächste Schicht vorzeitig beginnen (Übergabe vor der vollen Stunde)
            akt = sb.schicht(con, datum=d, zeit_id=z["id"])
            d, z = sb.naechster_slot(con, d, z)
            if not (akt and akt["beendet_am"]) and datetime.now() < sb.fenster(d, z)[0] - sb.VORZEITIG:
                flash(request, f"Die Schicht {sb.bezeichnung(d, z)} kann frühestens 2 Stunden vor ihrem Beginn starten.", "fehler")
                return RedirectResponse("/ih/schichtbuch", status_code=303)
        tid = int(f["team_id"]) if (f.get("team_id") or "").isdigit() and con.execute(
            select(sb_teams.c.id).where(sb_teams.c.id == int(f["team_id"]))).scalar() else None
        sid = sb.beginnen(con, d, z["id"], tid, f.get("schichtfuehrer") or me["name"], me["username"])
        audit(con, me["username"], "Schicht begonnen", sb.bezeichnung(d, z), {"schicht_id": sid, "team_id": tid})
    flash(request, f"Schicht {sb.bezeichnung(d, z)} begonnen. Bitte zuerst die offenen Übergaben lesen und übernehmen.")
    return RedirectResponse("/ih/schichtbuch#uebergaben", status_code=303)


@router.get("/papier")
def papier(request: Request):
    """Papierformular fürs Schichtbuch bei Systemausfall (vorab ausdrucken; Nachtrag über „Nachtragen“)."""
    require_recht(request, "ih.schichtbuch.ansehen")
    _grunddaten()
    with db.engine().connect() as con:
        return render(request, "papier/schichtbuch.html", teams=sb.teams(con), zeiten=sb.zeiten(con), typen=sb.ereignistypen(con))


@router.post("/wieder-oeffnen")
async def wieder_oeffnen(request: Request):
    """Versehentlich beendete Schicht wieder öffnen (solange die nächste Schicht noch nicht begonnen und nichts übernommen hat)."""
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    sid = int(f["schicht_id"]) if (f.get("schicht_id") or "").isdigit() else 0
    try:
        with db.schreiben() as con:
            s = sb.wieder_oeffnen(con, sid, me["username"])
            audit(con, me["username"], "Schicht wieder geöffnet", s["text"], {"schicht_id": sid})
    except sb.SchichtFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse("/ih/schichtbuch", status_code=303)
    flash(request, f"Schicht {s['text']} ist wieder offen. Ihre Übergaben sieht die nächste Schicht erst nach dem erneuten Beenden.")
    return RedirectResponse("/ih/schichtbuch", status_code=303)


# ------------------------------------------------------------------ Meldungen
def _form_ctx(con, f: dict | None = None, **extra) -> dict:
    return dict(typen=sb.ereignistypen(con), tags=_tags(con), PRIO=sb.PRIO, STATUS=sb.STATUS, f=f or {}, teams=sb.teams(con),
                jetzt_iso=datetime.now().strftime("%Y-%m-%dT%H:%M"), **extra)


@router.get("/neu")
def neu_form(request: Request, platz: str = "", nachtrag: int = 0):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    _grunddaten()
    with db.engine().connect() as con:
        t = sb.team_von(con, me["id"])
        vor = {"nachtrag": "on" if nachtrag else "", "nachtrag_team": t["id"] if t else ""}
        if platz.isdigit():
            code = con.execute(select(ih_plaetze.c.code).where(ih_plaetze.c.id == int(platz))).scalar()
            if code:
                vor["asset"] = code
        d, z = sb.laufender_slot(con)
        return render(request, "ih/sb_meldung_form.html", neu=True, slot_text=sb.bezeichnung(d, z), **_form_ctx(con, vor))


@router.post("/neu")
async def neu(request: Request):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    with db.schreiben() as con:
        sb.sicherstellen(con)
        w, fehler = sb.werte_aus_formular(con, f)
        zeitpunkt = None
        if f.get("nachtrag") == "on":
            try:
                zeitpunkt = sb.nachtrag_zeitpunkt(f.get("zeitpunkt") or "")
            except sb.SchichtFehler as e:
                fehler.append(str(e))
        if fehler:
            d, z = sb.laufender_slot(con)
            return render(request, "ih/sb_meldung_form.html", neu=True, slot_text=sb.bezeichnung(d, z), fehler=" ".join(fehler),
                          **_form_ctx(con, dict(f)))
        if zeitpunkt:
            tid = int(f["nachtrag_team"]) if (f.get("nachtrag_team") or "").isdigit() and con.execute(
                select(sb_teams.c.id).where(sb_teams.c.id == int(f["nachtrag_team"]))).scalar() else None
            sid = sb.nachtrag_schicht(con, zeitpunkt, tid, f.get("nachtrag_schichtfuehrer") or "")
        else:
            sid = sb.aktuelle_schicht_id(con, me)
        mid = sb.anlegen(con, w, f.get("status") or "offen", me["username"], sid, zeitpunkt)
        audit(con, me["username"], "Schichtbuch: Meldung nachgetragen" if zeitpunkt else "Schichtbuch: Meldung angelegt", f"M-{mid:05d}",
              {"titel": w["titel"], "asset": w["asset"], "zeitpunkt": zeitpunkt.isoformat(" ") if zeitpunkt else None})
    flash(request, f"Meldung M-{mid:05d} " + (f"nachgetragen ({zeitpunkt:%d.%m.%Y %H:%M})." if zeitpunkt else "gespeichert."))
    return RedirectResponse("/ih/schichtbuch" if f.get("weiter") == "dashboard" else f"/ih/schichtbuch/meldung/{mid}", status_code=303)


@router.get("/meldung/{mid}")
def meldung(request: Request, mid: int):
    require_recht(request, "ih.schichtbuch.ansehen")
    with db.engine().connect() as con:
        m = sb.meldung(con, mid)
        if not m:
            return render(request, "fehler.html", titel="Meldung nicht gefunden", text=f"Die Meldung M-{mid:05d} gibt es nicht.")
        v = sb.verlauf(con, mid)
        ueb_von = sb.schicht(con, m["uebergeben_schicht_id"]) if m["uebergeben_schicht_id"] else None
    return render(request, "ih/sb_meldung.html", m=m, verlauf=v, ueb_von=ueb_von, STATUS=sb.STATUS, PRIO=sb.PRIO)


@router.get("/meldung/{mid}/bearbeiten")
def bearbeiten_form(request: Request, mid: int):
    require_recht(request, "ih.schichtbuch.schreiben")
    with db.engine().connect() as con:
        m = sb.meldung(con, mid)
        if not m:
            return RedirectResponse("/ih/schichtbuch", status_code=303)
        f = {k: m[k] for k in sb.FELDER}
        f["sicherheitsrelevant"] = "on" if m["sicherheitsrelevant"] else ""
        f["stillstand"] = "on" if m["stillstand"] else ""
        return render(request, "ih/sb_meldung_form.html", neu=False, m=m, **_form_ctx(con, f))


@router.post("/meldung/{mid}/bearbeiten")
async def bearbeiten(request: Request, mid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    with db.schreiben() as con:
        m = sb.meldung(con, mid)
        if not m:
            return RedirectResponse("/ih/schichtbuch", status_code=303)
        w, fehler = sb.werte_aus_formular(con, f)
        if fehler:
            return render(request, "ih/sb_meldung_form.html", neu=False, m=m, fehler=" ".join(fehler), **_form_ctx(con, dict(f)))
        geaendert = sb.aendern(con, mid, w, me["username"], sb.aktuelle_schicht_id(con, me))
        if geaendert:
            audit(con, me["username"], "Schichtbuch: Meldung geändert", f"M-{mid:05d}", {"felder": geaendert})
    flash(request, "Meldung gespeichert." if geaendert else "Keine Änderungen.")
    return RedirectResponse(f"/ih/schichtbuch/meldung/{mid}", status_code=303)


@router.post("/meldung/{mid}/ergaenzen")
async def ergaenzen(request: Request, mid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    try:
        with db.schreiben() as con:
            sb.ergaenzen(con, mid, me["username"], sb.aktuelle_schicht_id(con, me), f.get("text") or "", f.get("status"))
    except sb.SchichtFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse(f"/ih/schichtbuch/meldung/{mid}#ergaenzen", status_code=303)
    flash(request, "Ergänzung gespeichert." + (f" Status: {sb.STATUS[f['status']]}." if f.get("status") in sb.STATUS else ""))
    return RedirectResponse(f"/ih/schichtbuch/meldung/{mid}" if f.get("weiter") != "dashboard" else "/ih/schichtbuch", status_code=303)


@router.post("/meldung/{mid}/uebernehmen")
async def uebernehmen(request: Request, mid: int):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    with db.schreiben() as con:
        ok = sb.uebernehmen(con, mid, me["username"], sb.aktuelle_schicht_id(con, me), f.get("kommentar") or "")
    flash(request, f"Übergabe M-{mid:05d} übernommen." if ok else "Diese Übergabe ist schon übernommen.", "ok" if ok else "fehler")
    return RedirectResponse(f"/ih/schichtbuch/meldung/{mid}" if f.get("weiter") == "meldung" else "/ih/schichtbuch#uebergaben", status_code=303)


@router.post("/uebernehmen-alle")
def uebernehmen_alle(request: Request):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    with db.schreiben() as con:
        sid = sb.aktuelle_schicht_id(con, me)
        n = sum(sb.uebernehmen(con, m["id"], me["username"], sid) for m in sb.offene_uebergaben(con))
    flash(request, f"{n} Übergaben übernommen.")
    return RedirectResponse("/ih/schichtbuch", status_code=303)


# ------------------------------------------------------------------ Schichtende
@router.get("/beenden")
def beenden_form(request: Request, schicht: str = ""):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    with db.schreiben() as con:
        sb.sicherstellen(con)
        sid = int(schicht) if schicht.isdigit() else sb.aktuelle_schicht_id(con, me)
    with db.engine().connect() as con:
        s = sb.schicht(con, sid)
        if not s:
            return RedirectResponse("/ih/schichtbuch", status_code=303)
        offene = sb.offene(con)
        for m in offene:
            m["vorschlag"] = (m["schicht_id"] == sid or m["uebernommen_schicht_id"] == sid or m["uebergeben_schicht_id"] == sid
                              or m["prioritaet"] == "hoch" or m["sicherheitsrelevant"] or m["stillstand"])
            m["text_vor"] = m["uebergabe_text"] if m["uebergeben_schicht_id"] == sid else ""
        erledigt = [m for m in sb.der_schicht(con, sid) if m["status"] == "erledigt"]
    return render(request, "ih/sb_beenden.html", s=s, offene=offene, erledigt=erledigt, STATUS=sb.STATUS, PRIO=sb.PRIO)


@router.post("/beenden")
async def beenden(request: Request):
    me = require_recht(request, "ih.schichtbuch.schreiben")
    f = await request.form()
    sid = int(f["schicht_id"]) if (f.get("schicht_id") or "").isdigit() else 0
    auswahl = {int(x): f.get(f"text_{x}") or "" for x in f.getlist("ueb") if x.isdigit()}
    try:
        with db.schreiben() as con:
            s = sb.schicht(con, sid)
            n = sb.beenden(con, sid, me["username"], auswahl, f.get("notiz") or "")
            audit(con, me["username"], "Schicht beendet", s["text"] if s else str(sid), {"uebergaben": n})
    except sb.SchichtFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse("/ih/schichtbuch", status_code=303)
    flash(request, f"Schicht {s['text']} beendet, {n} Punkt(e) an die nächste Schicht übergeben.")
    return RedirectResponse("/ih/schichtbuch", status_code=303)


# ------------------------------------------------------------------ Liste und Export
SPALTEN = ["Titel", "Datum", "Schicht", "Schichtführer", "Team", "Ereignistyp", "Beschreibung", "Maßnahme", "Status", "Priorität", "Asset",
           "Functional Location", "Work Order", "Übergabe an nächste Schicht", "Erledigt von nächster Schicht", "Kommentar nächste Schicht",
           "Sicherheitsrelevant", "Stillstand Anlage", "Stillstandsdauer (h)"]


def _filter(request: Request) -> dict:
    p = request.query_params
    return {"q": p.get("q", ""), "status": p.get("status", ""), "team": p.get("team", ""), "typ": p.get("typ", ""),
            "von": _datum(p.get("von", "")), "bis": _datum(p.get("bis", "")), "nur": p.get("nur", "")}


@router.get("/meldungen")
def liste(request: Request):
    require_recht(request, "ih.schichtbuch.ansehen")
    fl = _filter(request)
    with db.engine().connect() as con:
        rows = sb.suche(con, **fl)
        teams, typen = sb.teams(con, alle=True), sb.ereignistypen(con)
    return render(request, "ih/sb_liste.html", liste=rows, fl=fl, teams=teams, typen=typen, STATUS=sb.STATUS, PRIO=sb.PRIO,
                  query=request.url.query)


@router.get("/export.xlsx")
def export(request: Request):
    require_recht(request, "ih.schichtbuch.ansehen")
    fl = _filter(request)
    ja = {True: "Ja", False: "Nein"}
    with db.engine().connect() as con:
        rows = sb.suche(con, **fl, grenze=None)
        komm = sb.kommentare(con, [m["id"] for m in rows])
    zeilen = [[m["titel"], m["erstellt_am"], m["schicht_zeit"], m["schichtfuehrer"], m["team"], m["ereignistyp"], m["beschreibung"],
               m["massnahme"], sb.STATUS.get(m["status"]), sb.PRIO.get(m["prioritaet"]), m["asset"], m["functional_location"],
               (f"A-{m['auftrag_id']:05d}" if m["auftrag_id"] else m["work_order"]), ja[bool(m["uebergabe"])],
               ja[bool(m["erledigt_schicht_id"] and m["erledigt_schicht_id"] != m["schicht_id"])], komm.get(m["id"]),
               ja[bool(m["sicherheitsrelevant"])], ja[bool(m["stillstand"])], m["stillstand_h"]] for m in rows]
    daten = tabelle_xlsx("Schichtbuch", SPALTEN, zeilen, [34, 16, 8, 18, 8, 22, 50, 40, 14, 9, 16, 24, 12, 12, 12, 40, 12, 12, 12])
    return Response(daten, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Schichtbuch_{date.today():%Y%m%d}.xlsx"'})


# ------------------------------------------------------------------ Einrichten
@router.get("/einrichten")
def einrichten(request: Request):
    require_recht(request, "ih.schichtbuch.einrichten")
    _grunddaten()
    with db.engine().connect() as con:
        teams, zeiten = sb.teams(con, alle=True), sb.zeiten(con, alle=True)
        zuordnung = dict(con.execute(select(sb_mitglieder.c.user_id, sb_mitglieder.c.team_id)).all())
        ih_rolle = dict(con.execute(select(benutzer_rollen.c.user_id, benutzer_rollen.c.rolle).where(benutzer_rollen.c.modul == "ih")).all())
        benutzer = [dict(r) for r in con.execute(select(users.c.id, users.c.username, users.c.anzeigename, users.c.rolle)
                                                 .where(users.c.aktiv).order_by(users.c.anzeigename, users.c.username)).mappings()
                    if r["id"] in ih_rolle or r["rolle"] == "admin"]
        anzahl = {t: n for t, n in con.execute(select(sb_mitglieder.c.team_id, func.count()).group_by(sb_mitglieder.c.team_id))}
        typen = sb.ereignistypen(con)
    from ..rechte import IH_ROLLEN
    return render(request, "ih/sb_einrichten.html", teams=teams, zeiten=zeiten, zuordnung=zuordnung, benutzer=benutzer, ih_rolle=ih_rolle,
                  anzahl=anzahl, typen=typen, IH_ROLLEN=IH_ROLLEN)


@router.post("/einrichten/teams")
async def einrichten_teams(request: Request):
    me = require_recht(request, "ih.schichtbuch.einrichten")
    f = await request.form()
    with db.schreiben() as con:
        alt = sb.teams(con, alle=True)
        neu = []
        for i, t in enumerate(alt):
            neu.append({"id": t["id"], "name": " ".join((f.get(f"name_{t['id']}") or t["name"]).split())[:60],
                        "farbe": f.get(f"farbe_{t['id']}") or t["farbe"], "aktiv": f.get(f"aktiv_{t['id']}") == "on", "reihenfolge": i})
        if (f.get("neu_name") or "").strip():
            neu.append({"id": None, "name": " ".join(f["neu_name"].split())[:60], "farbe": f.get("neu_farbe") or "#5B6773", "aktiv": True,
                        "reihenfolge": len(alt)})
        namen = [t["name"].casefold() for t in neu]
        fehler = ("Jedes Team braucht einen Namen." if any(not n for n in namen) else
                  "Teamnamen müssen verschieden sein." if len(set(namen)) != len(namen) else
                  "Farbe bitte als #RRGGBB." if any(not sb.FARBE.match(t["farbe"]) for t in neu) else
                  "Mindestens ein Team muss aktiv bleiben." if not any(t["aktiv"] for t in neu) else None)
        if fehler:
            flash(request, fehler, "fehler")
            return RedirectResponse("/ih/schichtbuch/einrichten#teams", status_code=303)
        for t in neu:
            werte = {k: t[k] for k in ("name", "farbe", "aktiv", "reihenfolge")}
            if t["id"]:
                con.execute(update(sb_teams).where(sb_teams.c.id == t["id"]).values(**werte))
            else:
                con.execute(insert(sb_teams).values(**werte))
        audit(con, me["username"], "Schichtbuch: Teams geändert", "Schichtbuch", {"teams": [f"{t['name']}{'' if t['aktiv'] else ' (inaktiv)'}" for t in neu]})
    flash(request, "Teams gespeichert.")
    return RedirectResponse("/ih/schichtbuch/einrichten#teams", status_code=303)


def _ueberschneidung(zeiten: list[dict]) -> str | None:
    aktiv = [z for z in zeiten if z["aktiv"]]
    d = date(2026, 1, 5)
    fenster = [(z["name"], *sb.fenster(d + timedelta(days=k), z)) for z in aktiv for k in (0, 1)]
    for i, (n1, b1, e1) in enumerate(fenster):
        for n2, b2, e2 in fenster[i + 1:]:
            if n1 != n2 and b1 < e2 and b2 < e1:
                return f"Die Schichten „{n1}“ und „{n2}“ überschneiden sich."
    return None


@router.post("/einrichten/zeiten")
async def einrichten_zeiten(request: Request):
    me = require_recht(request, "ih.schichtbuch.einrichten")
    f = await request.form()
    try:
        with db.schreiben() as con:
            alt = sb.zeiten(con, alle=True)
            neu = []
            for i, z in enumerate(alt):
                neu.append({"id": z["id"], "name": " ".join((f.get(f"name_{z['id']}") or z["name"]).split())[:40],
                            "beginn": sb.uhrzeit(f.get(f"beginn_{z['id']}") or z["beginn"]), "ende": sb.uhrzeit(f.get(f"ende_{z['id']}") or z["ende"]),
                            "aktiv": f.get(f"aktiv_{z['id']}") == "on", "reihenfolge": i})
            if (f.get("neu_name") or "").strip():
                neu.append({"id": None, "name": " ".join(f["neu_name"].split())[:40], "beginn": sb.uhrzeit(f.get("neu_beginn") or ""),
                            "ende": sb.uhrzeit(f.get("neu_ende") or ""), "aktiv": True, "reihenfolge": len(alt)})
            namen = [z["name"].casefold() for z in neu]
            if any(not n for n in namen) or len(set(namen)) != len(namen):
                raise sb.SchichtFehler("Jede Schicht braucht einen eigenen Namen.")
            if not any(z["aktiv"] for z in neu):
                raise sb.SchichtFehler("Mindestens eine Schicht muss aktiv bleiben.")
            if fehler := _ueberschneidung(neu):
                raise sb.SchichtFehler(fehler)
            for z in neu:
                werte = {k: z[k] for k in ("name", "beginn", "ende", "aktiv", "reihenfolge")}
                if z["id"]:
                    con.execute(update(sb_zeiten).where(sb_zeiten.c.id == z["id"]).values(**werte))
                else:
                    con.execute(insert(sb_zeiten).values(**werte))
            audit(con, me["username"], "Schichtbuch: Schichtzeiten geändert", "Schichtbuch",
                  {"zeiten": [f"{z['name']} {z['beginn']}–{z['ende']}" for z in neu if z["aktiv"]]})
    except sb.SchichtFehler as e:
        flash(request, str(e), "fehler")
        return RedirectResponse("/ih/schichtbuch/einrichten#zeiten", status_code=303)
    flash(request, "Schichtzeiten gespeichert.")
    return RedirectResponse("/ih/schichtbuch/einrichten#zeiten", status_code=303)


@router.post("/einrichten/typen")
async def einrichten_typen(request: Request):
    me = require_recht(request, "ih.schichtbuch.einrichten")
    f = await request.form()
    liste = [z for z in (f.get("typen") or "").splitlines() if z.strip()]
    if not liste:
        flash(request, "Mindestens ein Ereignistyp.", "fehler")
        return RedirectResponse("/ih/schichtbuch/einrichten#typen", status_code=303)
    with db.schreiben() as con:
        sb.typen_speichern(con, liste)
        audit(con, me["username"], "Schichtbuch: Ereignistypen geändert", "Schichtbuch", {"anzahl": len(liste)})
    flash(request, "Ereignistypen gespeichert.")
    return RedirectResponse("/ih/schichtbuch/einrichten#typen", status_code=303)


@router.post("/einrichten/mitglieder")
async def einrichten_mitglieder(request: Request):
    me = require_recht(request, "ih.schichtbuch.einrichten")
    f = await request.form()
    with db.schreiben() as con:
        team_ids = {t["id"] for t in sb.teams(con, alle=True)}
        alt = dict(con.execute(select(sb_mitglieder.c.user_id, sb_mitglieder.c.team_id)).all())
        geaendert = 0
        for key, wert in f.items():
            if not key.startswith("team_") or not key[5:].isdigit():
                continue
            uid = int(key[5:])
            tid = int(wert) if str(wert).isdigit() and int(wert) in team_ids else None
            if alt.get(uid) == tid:
                continue
            if not con.execute(select(users.c.id).where(users.c.id == uid)).scalar():
                continue
            con.execute(delete(sb_mitglieder).where(sb_mitglieder.c.user_id == uid))
            if tid:
                con.execute(insert(sb_mitglieder).values(user_id=uid, team_id=tid))
            geaendert += 1
        if geaendert:
            audit(con, me["username"], "Schichtbuch: Teamzuordnung geändert", "Schichtbuch", {"benutzer": geaendert})
    flash(request, f"Zuordnung gespeichert ({geaendert} geändert)." if geaendert else "Keine Änderungen.")
    return RedirectResponse("/ih/schichtbuch/einrichten#mitglieder", status_code=303)

