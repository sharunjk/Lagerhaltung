from __future__ import annotations

import base64
import json
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, insert, select, update

from .. import db
from ..config import save_section
from ..db import artikel, audit as audit_t, lieferanten, users
from ..services import betrieb, casper_import, labels, queries
from ..services.excel import import_lesen, import_vorlage, tabelle_xlsx
from ..services.lager import BuchungsFehler, audit, parse_num
from ..services.zertifikat import lokale_adressen
from ..web import ROLLEN, flash, pw_kennung, render, require
from .artikel import etiketten_drucken, lager

router = APIRouter()


def _d(s: str, default: date) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return default


# ------------------------------------------------------------------ Auswertungen
@router.get("/auswertungen")
def auswertungen(request: Request, von: str = "", bis: str = "", monate: int = 12):
    require(request)
    bis_d = _d(bis, date.today())
    von_d = _d(von, bis_d - timedelta(days=365))
    with db.engine().connect() as con:
        verbrauch = queries.verbrauch(con, von_d, bis_d)
        kst = queries.verbrauch_kostenstelle(con, von_d, bis_d)
        lh = queries.ladenhueter(con, monate)
        arts = queries.artikel_liste(con)
    lagerwert = sum(a["bestand"] * a["preis"] for a in arts if a["preis"] and a["bestand"] > 0)
    kat: dict[str, list] = {}
    for a in arts:
        k = kat.setdefault(a["kategorie"] or "ohne Gruppe", [0, 0.0, 0.0])
        k[0] += 1
        k[1] += a["bestand"]
        k[2] += a["bestand"] * (a["preis"] or 0)
    return render(request, "auswertungen.html", verbrauch=verbrauch[:50], kst=kst, ladenhueter=lh[:100], ladenhueter_n=len(lh),
                  von=von_d.isoformat(), bis=bis_d.isoformat(), monate=monate, lagerwert=lagerwert,
                  ohne_preis=sum(1 for a in arts if not a["preis"] and a["bestand"] > 0),
                  verbrauch_summe=sum(float(v["ausgang"] or 0) for v in verbrauch),
                  kategorien=sorted(kat.items(), key=lambda x: -x[1][0])[:15])


@router.get("/auswertungen/{art}.xlsx")
def auswertung_export(request: Request, art: str, von: str = "", bis: str = "", monate: int = 12):
    require(request)
    bis_d = _d(bis, date.today())
    von_d = _d(von, bis_d - timedelta(days=365))
    with db.engine().connect() as con:
        if art == "verbrauch":
            kopf = ["Artikel", "Bezeichnung", "Entnommen", "Eingang", "Buchungen", "Preis", "Wert Entnahmen"]
            z = [[r["artikel_nr"], r["bezeichnung"], r["ausgang"], r["eingang"], r["buchungen"], r["preis"],
                  (r["ausgang"] or 0) * r["preis"] if r["preis"] else None] for r in queries.verbrauch(con, von_d, bis_d)]
        elif art == "ladenhueter":
            kopf = ["Artikel", "Bezeichnung", "Bestand", "Letzte Bewegung", "Lagerplätze"]
            z = [[r["nummer"], r["bezeichnung"], r["bestand"], r["letzte_bewegung"], ", ".join(o for o, _ in r["orte"])] for r in queries.ladenhueter(con, monate)]
        elif art == "lagerwert":
            kopf = ["Artikel", "Bezeichnung", "Gruppe", "Bestand", "Einheit", "Preis", "Wert"]
            z = [[r["nummer"], r["bezeichnung"], r["kategorie"], r["bestand"], r["einheit"], r["preis"], r["bestand"] * r["preis"] if r["preis"] else None]
                 for r in queries.artikel_liste(con) if r["bestand"] > 0]
        elif art == "kostenstellen":
            kopf = ["Kostenstelle", "Entnommene Menge", "Buchungen", "Wert"]
            z = [[r["kostenstelle"] or "ohne Angabe", r["menge"], r["buchungen"], r["wert"]] for r in queries.verbrauch_kostenstelle(con, von_d, bis_d)]
        else:
            return Response(status_code=404)
    return Response(tabelle_xlsx(art.capitalize(), kopf, z), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{art}_{date.today():%Y-%m-%d}.xlsx"'})


# ------------------------------------------------------------------ Einstellungen
@router.get("/einstellungen")
def einstellungen(request: Request, tab: str = "allgemein"):
    require(request, "admin")
    cfg = request.app.state.cfg
    with db.engine().connect() as con:
        nutzer = con.execute(select(users).order_by(func.lower(users.c.username))).mappings().all()
        letztes_backup = betrieb.get_setting(con, "letztes_backup")
        hat_daten = casper_import.hat_daten(con)
        bericht = betrieb.get_setting(con, "uebernahme_bericht")
    bo = cfg.path(cfg.backup.ordner)
    backups = sorted(bo.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[:30] if bo.exists() else []
    svg = labels.etikett_svg("10001", "10001", "Testetikett Kugelhahn DN15", cfg.drucker.standard_format, cfg.drucker.barcode, 2)
    import socket
    return render(request, "einstellungen.html", tab=tab, users=nutzer, backups=backups, letztes_backup=letztes_backup,
                  drucker_liste=labels.windows_drucker() if tab == "drucker" else [], svg=svg, hat_daten=hat_daten,
                  adressen=[a for a in lokale_adressen() if a != "127.0.0.1"], hostname=socket.gethostname(),
                  uebernahme=json.loads(bericht) if bericht else None)


def _cfg_update(request, section: str, werte: dict):
    obj = getattr(request.app.state.cfg, section)
    for k, v in werte.items():
        setattr(obj, k, v)
    save_section(section, werte)


@router.post("/einstellungen/allgemein")
async def allgemein(request: Request):
    require(request, "admin")
    f = await request.form()
    try:
        _cfg_update(request, "lager", {
            "negative_bestaende_erlauben": f.get("negative_bestaende_erlauben") == "on",
            "lagerplaetze_automatisch_anlegen": f.get("lagerplaetze_automatisch_anlegen") == "on",
            "live_abfrage_sekunden": max(3, int(f.get("live_abfrage_sekunden") or 10)),
            "standard_einheit": (f.get("standard_einheit") or "Stk").strip() or "Stk",
        })
        _cfg_update(request, "server", {"firmenname": (f.get("firmenname") or "").strip() or "Lager",
                                        "port": int(f.get("port") or 8080), "https_port": int(f.get("https_port") or 0)})
    except ValueError:
        flash(request, "Ungültige Zahl.", "fehler")
        return RedirectResponse("/einstellungen?tab=allgemein", status_code=303)
    flash(request, "Gespeichert. Geänderte Ports gelten nach einem Neustart der Lagerverwaltung.")
    return RedirectResponse("/einstellungen?tab=allgemein", status_code=303)


@router.post("/einstellungen/drucker")
async def drucker(request: Request):
    require(request, "admin")
    f = await request.form()
    try:
        werte = {
            "modus": f.get("modus") if f.get("modus") in ("windows", "netzwerk", "datei") else "windows",
            "name": (f.get("name") or "").strip(), "host": (f.get("host") or "").strip(), "port": int(f.get("port") or 9100),
            "standard_format": f.get("standard_format") if f.get("standard_format") in labels.LAYOUTS else "45x23",
            "barcode": "QR" if f.get("barcode") == "QR" else "128",
            "versatz_x_mm": float(str(f.get("versatz_x_mm") or 0).replace(",", ".")),
            "versatz_y_mm": float(str(f.get("versatz_y_mm") or 0).replace(",", ".")),
            "dichte": max(0, min(15, int(f.get("dichte") or 8))), "geschwindigkeit": max(2, min(5, int(f.get("geschwindigkeit") or 4))),  # HT100: 2–5 (Handbuch)
            "luecke_mm": float(str(f.get("luecke_mm") or 2).replace(",", ".")),
        }
    except ValueError:
        flash(request, "Ungültige Zahl in den Druckereinstellungen.", "fehler")
        return RedirectResponse("/einstellungen?tab=drucker", status_code=303)
    _cfg_update(request, "drucker", werte)
    if f.get("aktion") == "test":
        try:
            flash(request, "Testdruck: " + etiketten_drucken(request, [("10001", "10001", "Testetikett Kugelhahn DN15", 1)]))
        except labels.DruckFehler as e:
            flash(request, f"Testdruck fehlgeschlagen: {e}", "fehler")
    else:
        flash(request, "Druckereinstellungen gespeichert.")
    return RedirectResponse("/einstellungen?tab=drucker", status_code=303)


@router.post("/einstellungen/mail")
async def mail(request: Request):
    require(request, "admin")
    f = await request.form()
    werte = {"aktiv": f.get("aktiv") == "on", "server": (f.get("server") or "").strip(), "port": int(f.get("port")) if str(f.get("port") or "").isdigit() else 587,
             "ssl": f.get("ssl") == "on", "starttls": f.get("starttls") == "on", "benutzer": (f.get("benutzer") or "").strip(),
             "absender": (f.get("absender") or "").strip(), "empfaenger": (f.get("empfaenger") or "").strip(),
             "uhrzeit": (f.get("uhrzeit") or "07:30").strip()}
    if f.get("passwort"):
        werte["passwort"] = f.get("passwort")
    _cfg_update(request, "mail", werte)
    if f.get("aktion") == "test":
        try:
            n = betrieb.meldebestand_mail(db.engine(), request.app.state.cfg, nur_wenn_vorhanden=False)
            flash(request, f"Test-Mail gesendet ({n} Artikel unter Meldebestand).")
        except Exception as e:
            flash(request, f"Mailversand fehlgeschlagen: {e}", "fehler")
    else:
        flash(request, "E-Mail-Einstellungen gespeichert.")
    return RedirectResponse("/einstellungen?tab=mail", status_code=303)


@router.post("/einstellungen/backup")
async def backup(request: Request):
    require(request, "admin")
    f = await request.form()
    cfg = request.app.state.cfg
    if f.get("aktion") == "jetzt":
        try:
            flash(request, f"Sicherung erstellt: {betrieb.backup_erstellen(cfg).name}")
        except Exception as e:
            flash(request, f"Sicherung fehlgeschlagen: {e}", "fehler")
    else:
        _cfg_update(request, "backup", {"aktiv": f.get("aktiv") == "on", "ordner": (f.get("ordner") or "backups").strip(),
                                        "uhrzeit": (f.get("uhrzeit") or "22:00").strip(), "aufbewahren_tage": max(1, int(f.get("aufbewahren_tage") or 30))})
        flash(request, "Sicherungseinstellungen gespeichert.")
    return RedirectResponse("/einstellungen?tab=backup", status_code=303)


@router.get("/einstellungen/backup/{name}")
def backup_download(request: Request, name: str):
    require(request, "admin")
    cfg = request.app.state.cfg
    p = cfg.path(cfg.backup.ordner) / name
    if "/" in name or "\\" in name or not name.endswith(".zip") or not p.exists():
        return Response(status_code=404)
    return FileResponse(p, filename=name)


@router.post("/einstellungen/uebernahme")
async def uebernahme(request: Request, datei: UploadFile = File(...), ersetzen: str = Form("")):
    """Datenübernahme aus dem HeidiSQL-Export der Casper-Datenbank."""
    me = require(request, "admin")
    roh = await datei.read()
    try:
        text = roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = roh.decode("cp1252")
    cfg = request.app.state.cfg
    try:
        with db.engine().connect() as con:
            vorhanden = casper_import.hat_daten(con)
        if vorhanden and ersetzen != "on":
            raise ValueError("Es sind bereits Artikel vorhanden. Zum Überschreiben „Vorhandene Daten ersetzen“ anhaken.")
        if vorhanden:
            betrieb.backup_erstellen(cfg, name="vor_uebernahme")
        with db.schreiben() as con:
            if vorhanden:
                casper_import.alles_loeschen(con)
            rep = casper_import.uebernehmen(con, text, me["username"])
    except Exception as e:
        flash(request, f"Übernahme fehlgeschlagen, nichts geändert: {e}", "fehler")
        return RedirectResponse("/einstellungen?tab=uebernahme", status_code=303)
    with db.schreiben() as con:
        betrieb.set_setting(con, "uebernahme_bericht", json.dumps(rep.__dict__, ensure_ascii=False))
    flash(request, f"Übernommen: {rep.artikel} Artikel, {rep.lagerplaetze} Lagerplätze, {rep.bewegungen} Buchungen.")
    return RedirectResponse("/einstellungen?tab=uebernahme", status_code=303)


# ------------------------------------------------------------------ Benutzer
@router.post("/benutzer/speichern")
def benutzer_speichern(request: Request, id: str = Form(""), username: str = Form(...), anzeigename: str = Form(""),
                       rolle: str = Form("lager"), passwort: str = Form(""), aktiv: str = Form("")):
    me = require(request, "admin")
    rolle = rolle if rolle in ROLLEN else "lager"
    username = username.strip()
    with db.schreiben() as con:
        werte = dict(username=username, anzeigename=anzeigename.strip() or username, rolle=rolle, aktiv=aktiv == "on")
        if passwort:
            if len(passwort) < 6:
                flash(request, "Passwort muss mindestens 6 Zeichen haben.", "fehler")
                return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
            werte["pw_hash"] = betrieb.hash_pw(passwort)
        if id and not id.isdigit():
            flash(request, "Ungültiger Benutzer.", "fehler")
            return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
        if not username:
            flash(request, "Bitte einen Benutzernamen angeben.", "fehler")
            return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
        doppelt = con.execute(select(users.c.id).where(func.lower(users.c.username) == username.lower())).scalar()
        if doppelt and str(doppelt) != id:
            flash(request, "Benutzername existiert bereits.", "fehler")
            return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
        if id:
            if int(id) == me["id"] and (rolle != "admin" or not werte["aktiv"]):
                flash(request, "Sie können sich nicht selbst die Admin-Rechte entziehen.", "fehler")
                return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
            alt = con.execute(select(users.c.pw_hash).where(users.c.id == int(id))).scalar()
            if werte["aktiv"] and not alt and not passwort:
                flash(request, "Zum Aktivieren bitte ein Passwort vergeben.", "fehler")
                return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
            con.execute(update(users).where(users.c.id == int(id)).values(**werte))
            if int(id) == me["id"] and "pw_hash" in werte:
                request.session["user"] = {**me, "pw": pw_kennung(werte["pw_hash"])}
        else:
            if not passwort:
                flash(request, "Für neue Benutzer ist ein Passwort nötig.", "fehler")
                return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)
            con.execute(insert(users).values(**werte))
        audit(con, me["username"], "Benutzer gespeichert", username, {"rolle": rolle, "aktiv": werte["aktiv"]})
    flash(request, f"Benutzer {username} gespeichert.")
    return RedirectResponse("/einstellungen?tab=benutzer", status_code=303)


@router.post("/benutzer/{uid}/token")
def api_token(request: Request, uid: int):
    me = require(request, "admin")
    t = "lv_" + secrets.token_urlsafe(32)
    with db.schreiben() as con:
        con.execute(update(users).where(users.c.id == uid).values(api_token=t))
        audit(con, me["username"], "API-Schlüssel erzeugt", str(uid))
    request.session["neuer_token"] = t
    flash(request, "Neuer API-Schlüssel erzeugt. Er wird nur einmal angezeigt.")
    return RedirectResponse("/einstellungen?tab=api", status_code=303)


@router.get("/passwort")
def passwort_form(request: Request):
    require(request)
    return render(request, "passwort.html")


@router.post("/passwort")
def passwort(request: Request, alt: str = Form(...), neu: str = Form(...), neu2: str = Form(...)):
    me = require(request)
    with db.schreiben() as con:
        u = con.execute(select(users).where(users.c.id == me["id"])).mappings().first()
        if not betrieb.check_pw(alt, u["pw_hash"] or ""):
            return render(request, "passwort.html", fehler="Aktuelles Passwort ist falsch.")
        if len(neu) < 6 or neu != neu2:
            return render(request, "passwort.html", fehler="Neue Passwörter stimmen nicht überein oder sind kürzer als 6 Zeichen.")
        neu_hash = betrieb.hash_pw(neu)
        con.execute(update(users).where(users.c.id == me["id"]).values(pw_hash=neu_hash))
        audit(con, me["username"], "Passwort geändert", me["username"])
    request.session["user"] = {**me, "pw": pw_kennung(neu_hash)}
    flash(request, "Passwort geändert. Andere Anmeldungen mit dem alten Passwort sind beendet.")
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ Excel-Import
@router.get("/import")
def import_seite(request: Request):
    require(request, "admin")
    return render(request, "import.html")


@router.get("/import/vorlage.xlsx")
def vorlage(request: Request):
    require(request, "admin")
    return Response(import_vorlage(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Artikelimport_Vorlage.xlsx"'})


@router.post("/import/pruefen")
async def import_pruefen(request: Request, datei: UploadFile = File(...)):
    require(request, "admin")
    try:
        zeilen = import_lesen(await datei.read())
    except Exception as e:
        flash(request, f"Datei konnte nicht gelesen werden: {e}", "fehler")
        return RedirectResponse("/import", status_code=303)
    with db.engine().connect() as con:
        vorhanden = {r[0] for r in con.execute(select(artikel.c.nummer))}
        naechste = int(queries.naechste_nummer(con))
    for z in zeilen:
        z["_fehler"] = []
        if not z.get("nummer"):
            z["nummer"] = str(naechste)
            naechste += 1
            z["_auto"] = True
        z["_aktion"] = "aktualisieren" if z["nummer"] in vorhanden else "neu"
        if z["_aktion"] == "neu" and not z.get("bezeichnung"):
            z["_fehler"].append("Bezeichnung fehlt")
        for k in ("meldebestand", "mindestbestand", "bestellmenge", "preis", "anfangsbestand"):
            if z.get(k) and parse_num(z[k]) is None:
                z["_fehler"].append(f"{k} ist keine Zahl")
        if z.get("anfangsbestand") and not z.get("lagerplatz") and z["_aktion"] == "neu":
            z["_fehler"].append("Anfangsbestand ohne Lagerplatz")
    payload = base64.b64encode(json.dumps(zeilen, ensure_ascii=False).encode()).decode()
    return render(request, "import.html", zeilen=zeilen, payload=payload, fehlerhaft=sum(1 for z in zeilen if z["_fehler"]))


@router.post("/import/ausfuehren")
def import_ausfuehren(request: Request, payload: str = Form(...)):
    require(request, "admin")
    zeilen = json.loads(base64.b64decode(payload))
    neu = akt = 0
    try:
        with db.schreiben() as con:
            L = lager(con, request)
            lief = {r[1].lower(): r[0] for r in con.execute(select(lieferanten.c.id, lieferanten.c.name))}
            for z in zeilen:
                if z.get("_fehler"):
                    continue
                d = {}
                for k in ("bezeichnung", "typ", "kategorie", "hersteller", "hersteller_nr", "lieferant_artnr", "einheit", "verwendung", "notiz"):
                    if z.get(k):
                        d[k] = z[k]
                for k in ("meldebestand", "mindestbestand", "bestellmenge", "preis"):
                    if z.get(k):
                        d[k] = parse_num(z[k])
                if z.get("kritisch"):
                    d["kritisch"] = z["kritisch"].strip().lower() in ("ja", "x", "1", "true", "wahr")
                if z.get("lieferant"):
                    key = z["lieferant"].strip().lower()
                    if key not in lief:
                        lief[key] = con.execute(insert(lieferanten).values(name=z["lieferant"].strip())).inserted_primary_key[0]
                    d["lieferant_id"] = lief[key]
                if z["_aktion"] == "neu":
                    L.artikel_anlegen({"nummer": z["nummer"], **d}, z.get("lagerplatz", ""), z.get("anfangsbestand") or 0)
                    neu += 1
                else:
                    aid = con.execute(select(artikel.c.id).where(artikel.c.nummer == z["nummer"])).scalar()
                    L.artikel_aendern(aid, d)
                    akt += 1
            audit(con, request.session["user"]["username"], "Excel-Import", "", {"neu": neu, "aktualisiert": akt})
    except BuchungsFehler as e:
        flash(request, f"Import abgebrochen, nichts gespeichert: {e}", "fehler")
        return RedirectResponse("/import", status_code=303)
    flash(request, f"Import abgeschlossen: {neu} neu, {akt} aktualisiert.")
    return RedirectResponse("/artikel", status_code=303)


# ------------------------------------------------------------------ Protokoll
@router.get("/protokoll")
def protokoll(request: Request, q: str = "", seite: int = 1):
    require(request, "admin")
    pro = 100
    with db.engine().connect() as con:
        stmt = select(audit_t)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(audit_t.c.benutzer.ilike(like) | audit_t.c.aktion.ilike(like) | audit_t.c.objekt.ilike(like) | audit_t.c.details.ilike(like))
        total = con.execute(select(func.count()).select_from(stmt.subquery())).scalar()
        rows = con.execute(stmt.order_by(audit_t.c.id.desc()).limit(pro).offset((max(1, seite) - 1) * pro)).mappings().all()
    return render(request, "protokoll.html", rows=rows, q=q, seite=seite, seiten=max(1, (total - 1) // pro + 1), total=total)
