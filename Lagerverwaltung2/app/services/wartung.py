"""Wartungsplanung nach dem Instandhaltungsplan (Maßnahmen S/W/F/B und Pflichtprüfungen Z).

Grundsätze aus dem Instandhaltungsplan:
* Es gibt drei eigene Maßnahmen – Sichtprüfung (S), Wartung (W), Funktionsprüfung (F) – plus ständige Beobachtung (B,
  ohne Termin) und gesetzliche Pflichtprüfungen (Z…), die extern durchgeführt werden.
* Intervalle hängen an der Bauteilklasse, nicht am einzelnen Bauteil.
* Eine Kampagne bündelt gleichartige Bauteile zu einem Arbeitspaket; dokumentiert wird trotzdem je Bauteil
  (WP-01). Nur reine Sichtprüfungen an Bauteilen ohne Sicherheitsfunktion gehen über das Sammelprotokoll (WP-02).
* Der Plan sagt WANN, die Wartungs-/Prüfanweisung des Bauteils sagt WIE.
"""
from __future__ import annotations

import io
import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import (artikel, bestand, bewegungen, ih_auftraege, ih_auftrag_positionen, ih_dokumente, ih_kampagne_bauteile, ih_kampagnen,
                  ih_klassen_intervalle, ih_massnahmen, ih_plaetze, ih_statuslog, ih_stueckliste, lagerplaetze)
from .lager import audit


class WartungsFehler(ValueError):
    pass


STATUS = {"angelegt": "Angelegt", "freigegeben": "Freigegeben", "in_arbeit": "In Arbeit", "erledigt": "Technisch erledigt",
          "abgeschlossen": "Abgeschlossen", "storniert": "Storniert"}
OFFEN = ("angelegt", "freigegeben", "in_arbeit", "erledigt")
ERGEBNIS = {"ohne_befund": "ohne Befund", "mit_befund": "mit Befund", "nicht_durchfuehrbar": "nicht durchführbar"}
ERGEBNIS_Z = {"ohne_befund": "bestanden / ohne Mängel", "mit_befund": "mit Mängeln", "nicht_durchfuehrbar": "nicht durchgeführt"}
ZUSTAND = {"unauffaellig": "unauffällig, betriebsbereit", "auffaellig": "Auffälligkeiten", "gestoert": "bereits gestört / außer Funktion"}
ABSCHLUSS = {"brueckung": "Brückungsschalter entfernt, Umgänge geschlossen", "kennzeichnung": "Kennzeichnung vorhanden und lesbar",
             "grenzwerte": "Grenzwerte auf Sollwert zurückgestellt", "betrieb": "Betrieb informiert, Anlage freigegeben"}
# Standard-Vorlauf (Wochen): so früh erscheint ein Termin als „bald fällig“. Innere Prüfungen und Festigkeitsprüfungen
# brauchen Monate Vorbereitung (Entleeren, Reinigen, ZÜS beauftragen) – im Plan je Kampagne änderbar.
VORLAUF = {"Zi": 26, "Zf": 26}
VORLAUF_PFLICHT = 12
VORLAUF_EIGEN = 2


# ------------------------------------------------------------------ Datumsrechnung
def plus_monate(d: date, monate: int) -> date:
    m = d.month - 1 + monate
    j, m = d.year + m // 12, m % 12 + 1
    return date(j, m, min(d.day, monthrange(j, m)[1]))


def montag(d: date) -> date:
    return d - timedelta(days=d.weekday())


def kw(d: date) -> str:
    j, w, _ = d.isocalendar()
    return f"KW {w:02d}/{j}"


RHYTHMUS = {"fest": "fest ab dem ersten Termin (wie im Instandhaltungsplan)",
            "ab_erledigung": "ab der letzten Durchführung (später erledigt = nächster Termin später)"}


def startpunkt(k: dict) -> date | None:
    """Ab wann die Intervalle gerechnet werden: fester Rhythmus ab erstem Termin oder ab letzter Durchführung."""
    erster = k.get("erster_termin")
    if k.get("rhythmus") == "ab_erledigung" and k.get("basis") and k.get("intervall_monate"):
        ab = montag(plus_monate(k["basis"], int(k["intervall_monate"])))  # Wochenplanung: Montag der Woche
        return max(ab, erster) if erster else ab
    return erster


def termine(k: dict, bis: date) -> list[date]:
    """Termine einer Kampagne bis einschließlich ``bis`` – ab ``startpunkt`` im Abstand des Intervalls."""
    start = startpunkt(k)
    if not k.get("intervall_monate") or not start:
        return []
    out, n = [], 0
    while True:
        t = plus_monate(start, n * int(k["intervall_monate"]))
        if t > bis:
            return out
        out.append(t)
        n += 1
        if n > 2000:
            return out


def vorlauf(k: dict) -> int:
    if k.get("vorlauf_wochen") is not None:
        return int(k["vorlauf_wochen"])
    return VORLAUF.get(k["massnahme"], VORLAUF_PFLICHT if k["massnahme"].startswith("Z") else VORLAUF_EIGEN)


def lage(con: Connection, heute: date | None = None) -> list[dict]:
    """Jede aktive Kampagne mit nächstem offenen Termin, Status und Anzahl Bauteile."""
    heute = heute or date.today()
    auftr, offene = {}, {}
    for r in con.execute(select(ih_auftraege.c.kampagne_id, ih_auftraege.c.termin, ih_auftraege.c.id, ih_auftraege.c.status)):
        auftr[(r.kampagne_id, r.termin)] = {"id": r.id, "status": r.status}
        if r.status in OFFEN:
            offene.setdefault(r.kampagne_id, []).append((r.termin, {"id": r.id, "status": r.status}))
    anzahl = bauteile_je_klasse(con)
    einzeln = dict(con.execute(select(ih_kampagne_bauteile.c.kampagne_id, func.count()).select_from(
        ih_kampagne_bauteile.join(ih_plaetze, ih_plaetze.c.id == ih_kampagne_bauteile.c.platz_id)).where(ih_plaetze.c.aktiv)
        .group_by(ih_kampagne_bauteile.c.kampagne_id)).all())
    basen = basis_je_kampagne(con)
    out = []
    for k in con.execute(select(ih_kampagnen).order_by(ih_kampagnen.c.schluessel)).mappings():
        k = dict(k)
        k["einzeln"] = k["id"] in einzeln
        k["bauteile"] = einzeln[k["id"]] if k["einzeln"] else anzahl.get((k["bauteilklasse"] or "").casefold(), 0)
        k["vorlauf"] = vorlauf(k)
        k["basis"] = basen.get(k["id"])
        offen = []
        for t in termine(k, heute + timedelta(days=366 + 7 * k["vorlauf"])):
            a = auftr.get((k["id"], t))
            if not a or a["status"] in OFFEN:
                offen.append((t, a))
        # offene Aufträge außerhalb des Rasters (z. B. nach Änderung des Intervalls) zählen trotzdem als nächster Termin
        bekannt = {t for t, _ in offen}
        offen = sorted(offen + [(t, a) for t, a in offene.get(k["id"], []) if t not in bekannt], key=lambda x: x[0])
        k["ueberfaellige"] = sum(1 for t, _ in offen if t + timedelta(weeks=k["dauer_wochen"] or 1) <= heute)
        if offen:
            k["naechster"], k["auftrag"] = offen[0]
            ende = k["naechster"] + timedelta(weeks=k["dauer_wochen"] or 1)
            if ende <= heute:
                k["lage"] = "ueberfaellig"
            elif k["naechster"] <= heute:
                k["lage"] = "laeuft"
            elif k["naechster"] - heute <= timedelta(weeks=k["vorlauf"]):
                k["lage"] = "bald"
            else:
                k["lage"] = "geplant"
        else:
            k["naechster"], k["auftrag"], k["lage"] = None, None, "geplant"
        if not k["aktiv"]:
            k["lage"] = "inaktiv"
        out.append(k)
    return out


LAGE_TEXT = {"ueberfaellig": "überfällig", "laeuft": "läuft jetzt", "bald": "bald fällig", "geplant": "geplant", "inaktiv": "inaktiv"}


def bauteile_je_klasse(con: Connection) -> dict[str, int]:
    return {(k or "").casefold(): n for k, n in con.execute(
        select(ih_plaetze.c.bauteilklasse, func.count()).where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv)
        .group_by(ih_plaetze.c.bauteilklasse))}


def bauteile(con: Connection, klasse: str | None) -> list[dict]:
    if not klasse:
        return []
    return [dict(r) for r in con.execute(select(ih_plaetze).where(
        ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv, func.lower(ih_plaetze.c.bauteilklasse) == klasse.casefold())
        .order_by(ih_plaetze.c.code)).mappings()]


def bauteile_kampagne(con: Connection, k: dict) -> list[dict]:
    """Einzeln zugeordnete Bauteile (eigene Kampagne) – sonst alle aktiven Bauteile der Bauteilklasse."""
    einzeln = [dict(r) for r in con.execute(select(ih_plaetze).select_from(
        ih_kampagne_bauteile.join(ih_plaetze, ih_plaetze.c.id == ih_kampagne_bauteile.c.platz_id))
        .where(ih_kampagne_bauteile.c.kampagne_id == k["id"], ih_plaetze.c.aktiv).order_by(ih_plaetze.c.code)).mappings()]
    if einzeln or con.execute(select(func.count()).select_from(ih_kampagne_bauteile).where(ih_kampagne_bauteile.c.kampagne_id == k["id"])).scalar():
        return einzeln
    return bauteile(con, k.get("bauteilklasse"))


def basis_je_kampagne(con: Connection) -> dict[int, date]:
    """Letzte Durchführung je Kampagne: Datum „technisch erledigt“ des neuesten abgeschlossenen Auftrags."""
    out = {}
    for kid, erl, abg in con.execute(select(ih_auftraege.c.kampagne_id, ih_auftraege.c.erledigt_am, ih_auftraege.c.abgeschlossen_am)
                                     .where(ih_auftraege.c.status == "abgeschlossen")):
        d = (erl or abg)
        if d and (kid not in out or d.date() > out[kid]):
            out[kid] = d.date()
    return out


def wochenlast(kampagnen: list[dict], wochen: list[date]) -> dict[date, float]:
    """Techniker-Tage je Woche: Aufwand einer Kampagne gleichmäßig auf ihre Dauer verteilt."""
    last = {w: 0.0 for w in wochen}
    bis = wochen[-1] if wochen else date.today()
    for k in kampagnen:
        if not k["aktiv"] or not k.get("aufwand_tage"):
            continue
        dauer = max(1, k.get("dauer_wochen") or 1)
        for t in termine(k, bis):
            start = montag(t)
            for i in range(dauer):
                w = start + timedelta(weeks=i)
                if w in last:
                    last[w] += k["aufwand_tage"] / dauer
    return last


# ------------------------------------------------------------------ Instandhaltungsplan einlesen
def _norm(s) -> str:
    s = str(s or "").lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]", "", s)


BLAETTER = {"massnahmen": "massnahmen", "intervalle": "intervallejeklasse", "kampagnen": "kampagnen", "pflicht": "pflichtprufungen"}


def _blatt(wb, name: str):
    for ws in wb.worksheets:
        if _norm(ws.title) == name:
            return ws
    return None


def _zeilen(ws) -> list[dict]:
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    kopf_i = next((i for i, r in enumerate(rows) if sum(1 for c in r if c not in (None, "")) >= 2), None)
    if kopf_i is None:
        return []
    kopf = [_norm(c) for c in rows[kopf_i]]
    out = []
    for r in rows[kopf_i + 1:]:
        if not any(c not in (None, "") for c in r):
            continue
        out.append({k: (v.strip() if isinstance(v, str) else v) for k, v in zip(kopf, r) if k})
    return out


def _monate(v, einheit="") -> int | None:
    if v in (None, "") or (isinstance(v, str) and v.strip().lower() in ("laufend", "-", "–")):
        return None
    try:
        n = float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError(f"Intervall „{v}“")
    e = _norm(einheit)
    if e.startswith("jahr"):
        n *= 12
    return int(round(n))


def _datum(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return date.fromisoformat(s[:10])


def _zahl(v) -> float | None:
    if v in (None, ""):
        return None
    return float(str(v).replace(",", "."))


def plan_lesen(daten: bytes) -> dict:
    """Instandhaltungsplan (Excel) -> Maßnahmen, Intervalle je Klasse, Kampagnen (inkl. Pflichtprüfungen)."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(daten), read_only=True, data_only=True)
    except Exception as e:
        raise WartungsFehler("Die Datei lässt sich nicht als Excel-Datei lesen.") from e
    try:
        blaetter = {k: _blatt(wb, v) for k, v in BLAETTER.items()}
        fehlt = [n for n, k in (("Maßnahmen", "massnahmen"), ("Intervalle je Klasse", "intervalle"), ("Kampagnen", "kampagnen"))
                 if blaetter[k] is None]
        if fehlt:
            raise WartungsFehler(f"Im Instandhaltungsplan fehlen die Blätter: {', '.join(fehlt)}.")
        roh = {k: _zeilen(ws) if ws is not None else [] for k, ws in blaetter.items()}
    finally:
        wb.close()
    meldungen: list[str] = []
    massnahmen = []
    for i, r in enumerate(roh["massnahmen"]):
        code = str(r.get("code") or "").strip()
        if not code or not r.get("massnahme"):
            continue
        massnahmen.append({"code": code, "symbol": r.get("symbol"), "name": r.get("massnahme"), "beschreibung": r.get("wasistzutun"),
                           "wer": r.get("wermachtes"), "nachweis": r.get("nachweis"), "pflicht": code.startswith("Z"), "reihenfolge": i})
    intervalle = []
    for r in roh["intervalle"]:
        art, klasse = str(r.get("art") or "").strip(), str(r.get("bauteilklasse") or "").strip()
        if not art or not klasse:
            continue
        try:
            monate = _monate(r.get("intervall"), r.get("einheit") or "")
        except ValueError as e:
            meldungen.append(f"Intervalle je Klasse, {r.get('id') or art + '-' + klasse}: {e} ist keine Zahl – übersprungen.")
            continue
        intervalle.append({"schluessel": str(r.get("id") or f"{art}-{klasse}"), "bauteilklasse": klasse, "massnahme": art,
                           "intervall_monate": monate, "grundlage": r.get("grundlage"), "achtung": r.get("achtung")})
    pflicht = {str(r.get("id") or "").strip(): r for r in roh["pflicht"] if r.get("id")}
    kampagnen = []
    for r in roh["kampagnen"]:
        sid, art = str(r.get("gruppenid") or "").strip(), str(r.get("art") or "").strip()
        if not sid or not art:
            continue
        try:
            monate = _monate(r.get("intervallmonate"))
            erster = _datum(r.get("erstertermin"))
        except ValueError as e:
            meldungen.append(f"Kampagne {sid}: {e} – übersprungen.")
            continue
        if not monate or not erster:
            meldungen.append(f"Kampagne {sid}: Intervall oder erster Termin fehlt – übersprungen.")
            continue
        p = pflicht.get(sid, {})
        aktiv = str(r.get("aktiv") or "Ja").strip().lower() not in ("nein", "n", "falsch", "false", "0")
        kampagnen.append({
            "schluessel": sid, "massnahme": art, "bauteilklasse": r.get("bauteilklasse"), "intervall_monate": monate,
            "erster_termin": erster, "aufwand_tage": _zahl(r.get("aufwandtage")), "dauer_wochen": int(_zahl(r.get("dauerwochen")) or 1),
            "bauteile_pro_tag": _zahl(r.get("bauteiletag")), "grundlage": r.get("grundlage"), "aktiv": aktiv,
            "verantwortlich": r.get("verantwortlich"), "gegenstand": p.get("gegenstand"), "rechtsgrundlage": p.get("rechtsgrundlage"),
            "durchfuehrung": p.get("durchfuhrung"), "nachweis": p.get("nachweis"), "hinweis": p.get("hinweis")})
    # Pflichtprüfungen ohne eigene Maßnahmenzeile (z. B. ZE, ZD): Maßnahme aus dem Blatt „Pflichtprüfungen“ ergänzen
    codes = {m["code"] for m in massnahmen}
    for k in kampagnen:
        if k["massnahme"] not in codes:
            p = pflicht.get(k["schluessel"], {})
            massnahmen.append({"code": k["massnahme"], "symbol": "◆", "name": p.get("prufung") or k["massnahme"],
                               "beschreibung": p.get("gegenstand"), "wer": p.get("durchfuhrung"), "nachweis": p.get("nachweis"),
                               "pflicht": k["massnahme"].startswith("Z"), "reihenfolge": 100 + len(massnahmen)})
            codes.add(k["massnahme"])
    for sid in pflicht:
        if sid not in {k["schluessel"] for k in kampagnen}:
            meldungen.append(f"Pflichtprüfung {sid}: keine Kampagne mit dieser ID – nur als Information übernommen, ohne Termin.")
    if not kampagnen:
        raise WartungsFehler("Im Blatt „Kampagnen“ wurden keine gültigen Kampagnen gefunden.")
    return {"massnahmen": massnahmen, "intervalle": intervalle, "kampagnen": kampagnen, "meldungen": meldungen}


def _json(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def plan_als_json(plan: dict) -> str:
    return json.dumps({k: ([{a: _json(b) for a, b in z.items()} for z in v] if isinstance(v, list) and v and isinstance(v[0], dict) else v)
                       for k, v in plan.items()}, ensure_ascii=False)


def plan_aus_json(text: str) -> dict:
    plan = json.loads(text)
    for k in plan["kampagnen"]:
        k["erster_termin"] = date.fromisoformat(k["erster_termin"])
    return plan


TABELLEN = (("massnahmen", ih_massnahmen, "code"), ("intervalle", ih_klassen_intervalle, "schluessel"),
            ("kampagnen", ih_kampagnen, "schluessel"))


def plan_vergleich(con: Connection, plan: dict) -> dict:
    """Je Blatt: neu / geändert (mit Feldern) / unverändert – ohne zu schreiben. Nichts wird gelöscht."""
    out = {}
    for name, tab, key in TABELLEN:
        vorhanden = {r[key]: dict(r) for r in con.execute(select(tab)).mappings()}
        neu, geaendert, gleich = [], [], 0
        for z in plan[name]:
            alt = vorhanden.get(z[key])
            if not alt:
                neu.append(z[key])
                continue
            aend = {f: [alt.get(f), v] for f, v in z.items() if f != key and alt.get(f) != v and not (alt.get(f) in (None, "") and v in (None, ""))}
            if aend:
                geaendert.append({"schluessel": z[key], "felder": {f: [_json(a), _json(b)] for f, (a, b) in aend.items()}})
            else:
                gleich += 1
        out[name] = {"neu": neu, "geaendert": geaendert, "unveraendert": gleich,
                     "nicht_im_plan": sorted(set(vorhanden) - {z[key] for z in plan[name]})}
    return out


def plan_uebernehmen(con: Connection, plan: dict, benutzer: str) -> dict:
    zahlen = {}
    for name, tab, key in TABELLEN:
        vorhanden = {r[0] for r in con.execute(select(tab.c[key]))}
        n = g = 0
        for z in plan[name]:
            werte = dict(z)
            if name == "kampagnen":
                werte["geaendert_am"] = datetime.now()
            if z[key] in vorhanden:
                con.execute(update(tab).where(tab.c[key] == z[key]).values(**{k: v for k, v in werte.items() if k != key}))
                g += 1
            else:
                con.execute(insert(tab).values(**werte))
                n += 1
        zahlen[name] = {"neu": n, "aktualisiert": g}
    audit(con, benutzer, "Instandhaltungsplan übernommen", "Wartungsplanung", zahlen)
    return zahlen


# ------------------------------------------------------------------ Aufträge
def massnahmen(con: Connection) -> dict[str, dict]:
    return {r["code"]: dict(r) for r in con.execute(select(ih_massnahmen).order_by(ih_massnahmen.c.reihenfolge)).mappings()}


def formular(massnahme: str, sicherheitsgerichtet: bool | None) -> str:
    """WP-02 (Sammelprotokoll) nur für reine Sichtprüfungen an Bauteilen ohne Sicherheitsfunktion; Pflichtprüfung: Z."""
    if massnahme.startswith("Z"):
        return "Z"
    return "WP-02" if massnahme == "S" and not sicherheitsgerichtet else "WP-01"


def auftrag_anlegen(con: Connection, kampagne_id: int, termin: date, benutzer: str) -> int:
    k = con.execute(select(ih_kampagnen).where(ih_kampagnen.c.id == kampagne_id)).mappings().first()
    if not k:
        raise WartungsFehler("Kampagne nicht gefunden.")
    k = {**k, "basis": basis_je_kampagne(con).get(kampagne_id)}
    if termin not in termine(k, termin):
        raise WartungsFehler(f"{termin:%d.%m.%Y} ist kein Termin dieser Kampagne.")
    if con.execute(select(ih_auftraege.c.id).where(ih_auftraege.c.kampagne_id == kampagne_id, ih_auftraege.c.termin == termin)).scalar():
        raise WartungsFehler(f"Für {kw(termin)} gibt es schon einen Auftrag.")
    m = massnahmen(con).get(k["massnahme"], {"name": k["massnahme"]})
    titel = f"{m['name']} {k['gegenstand'] or k['bauteilklasse'] or ''}".strip() + f" – {kw(termin)}"
    jetzt = datetime.now()
    aid = con.execute(insert(ih_auftraege).values(kampagne_id=kampagne_id, termin=termin, massnahme=k["massnahme"], titel=titel[:300],
                                                  status="angelegt", verantwortlich=k["verantwortlich"], erstellt_von=benutzer,
                                                  erstellt_am=jetzt)).inserted_primary_key[0]
    teile = bauteile_kampagne(con, k)
    if teile:
        con.execute(insert(ih_auftrag_positionen), [{"auftrag_id": aid, "platz_id": t["id"],
                                                     "formular": formular(k["massnahme"], t["sicherheitsgerichtet"])} for t in teile])
    _log(con, aid, benutzer, None, "angelegt", f"{len(teile)} Bauteile" if teile else "ohne Bauteilliste")
    audit(con, benutzer, "Wartungsauftrag angelegt", f"A-{aid:05d}", {"kampagne": k["schluessel"], "termin": termin, "bauteile": len(teile)})
    return aid


def faellige_anlegen(con: Connection, benutzer: str, heute: date | None = None) -> list[int]:
    """Aufträge für alle aktiven Kampagnen anlegen, deren nächster Termin im Vorlauf liegt oder schon fällig ist."""
    heute = heute or date.today()
    neu = []
    for k in lage(con, heute):
        if k["aktiv"] and k["naechster"] and not k["auftrag"] and k["naechster"] - heute <= timedelta(weeks=k["vorlauf"]):
            neu.append(auftrag_anlegen(con, k["id"], k["naechster"], benutzer))
    return neu


def _log(con, aid, benutzer, von, nach, text=""):
    con.execute(insert(ih_statuslog).values(auftrag_id=aid, zeit=datetime.now(), benutzer=benutzer, von=von, nach=nach, text=text or None))


def auftrag(con: Connection, aid: int) -> dict | None:
    r = con.execute(select(ih_auftraege, ih_kampagnen.c.schluessel.label("kampagne"), ih_kampagnen.c.bauteilklasse,
                           ih_kampagnen.c.gegenstand, ih_kampagnen.c.grundlage, ih_kampagnen.c.rechtsgrundlage,
                           ih_kampagnen.c.durchfuehrung, ih_kampagnen.c.hinweis, ih_kampagnen.c.dauer_wochen,
                           ih_kampagnen.c.taetigkeit, ih_kampagnen.c.eigen, ih_kampagnen.c.hinweis.label("kampagne_hinweis"))
                    .select_from(ih_auftraege.outerjoin(ih_kampagnen, ih_kampagnen.c.id == ih_auftraege.c.kampagne_id))
                    .where(ih_auftraege.c.id == aid)).mappings().first()
    return dict(r) if r else None


def positionen(con: Connection, aid: int) -> list[dict]:
    rows = con.execute(select(ih_auftrag_positionen, ih_plaetze.c.code, ih_plaetze.c.bezeichnung, ih_plaetze.c.sicherheitsgerichtet,
                              ih_plaetze.c.doku_url)
                       .select_from(ih_auftrag_positionen.join(ih_plaetze, ih_plaetze.c.id == ih_auftrag_positionen.c.platz_id))
                       .where(ih_auftrag_positionen.c.auftrag_id == aid).order_by(ih_plaetze.c.code)).mappings().all()
    out = []
    for r in rows:
        r = dict(r)
        r["schritte"] = json.loads(r["schritte"] or "[]")
        r["abschluss"] = json.loads(r["abschluss"] or "{}")
        out.append(r)
    return out


def achtung(con: Connection, massnahme: str, klasse: str | None) -> str | None:
    if not klasse:
        return None
    return con.execute(select(ih_klassen_intervalle.c.achtung).where(ih_klassen_intervalle.c.massnahme == massnahme,
                                                                     func.lower(ih_klassen_intervalle.c.bauteilklasse) == klasse.casefold())).scalar()


def position_pruefen(pos: dict, werte: dict) -> list[str]:
    """Pflichtangaben je Formular (WP-01 nach SR 4: Zustand bei Beginn, Ergebnis, Abschluss bei Sicherheitseinrichtungen)."""
    fehler = []
    erg = werte.get("ergebnis")
    if erg not in ERGEBNIS:
        fehler.append("Bitte das Ergebnis wählen.")
    if pos["formular"] == "WP-01" and werte.get("zustand_beginn") not in ZUSTAND:
        fehler.append("Bitte den Zustand bei Beginn angeben (SR 4 verlangt den vorgefundenen Zustand).")
    if erg == "mit_befund" and not (werte.get("befund_nr") or werte.get("befund_text")):
        fehler.append("Bei „mit Befund“ bitte Befundmeldung-Nr. oder eine Beschreibung angeben.")
    if erg == "nicht_durchfuehrbar" and not werte.get("befund_text"):
        fehler.append("Bei „nicht durchführbar“ bitte die Begründung angeben.")
    if pos["formular"] == "WP-01" and pos.get("sicherheitsgerichtet") and erg in ("ohne_befund", "mit_befund"):
        fehlt = [ABSCHLUSS[k] for k in ABSCHLUSS if not werte.get("abschluss", {}).get(k)]
        if fehlt:
            fehler.append("PLT-Sicherheitseinrichtung: Abschlusskontrolle vollständig bestätigen (" + "; ".join(fehlt) + ").")
    return fehler


def position_speichern(con: Connection, a: dict, pos: dict, werte: dict, benutzer: str) -> None:
    if a["status"] not in ("freigegeben", "in_arbeit"):
        raise WartungsFehler("Protokolle können nur in freigegebenen Aufträgen erfasst werden." if a["status"] == "angelegt"
                             else "Der Auftrag ist nicht mehr in Bearbeitung.")
    fehler = position_pruefen(pos, werte)
    if fehler:
        raise WartungsFehler(" ".join(fehler))
    con.execute(update(ih_auftrag_positionen).where(ih_auftrag_positionen.c.id == pos["id"]).values(
        zustand_beginn=werte.get("zustand_beginn"), zustand_text=werte.get("zustand_text") or None,
        schritte=json.dumps(werte.get("schritte") or [], ensure_ascii=False) if werte.get("schritte") else None,
        ergebnis=werte["ergebnis"], befund_nr=werte.get("befund_nr") or None, befund_text=werte.get("befund_text") or None,
        abschluss=json.dumps(werte.get("abschluss") or {}) if werte.get("abschluss") else None, sil=werte.get("sil") or None,
        durchgefuehrt_von=benutzer, durchgefuehrt_am=datetime.now()))
    if a["status"] == "freigegeben":
        con.execute(update(ih_auftraege).where(ih_auftraege.c.id == a["id"]).values(status="in_arbeit"))
        _log(con, a["id"], benutzer, "freigegeben", "in_arbeit", "erstes Protokoll erfasst")
        a["status"] = "in_arbeit"


AKTIONEN = {  # Aktion: (erlaubt aus, neuer Status, Recht)
    "freigeben": (("angelegt",), "freigegeben", "ih.auftrag.freigeben"),
    "erledigt": (("freigegeben", "in_arbeit"), "erledigt", "ih.auftrag.ausfuehren"),
    "zurueckweisen": (("erledigt",), "in_arbeit", "ih.auftrag.abschliessen"),
    "abschliessen": (("erledigt",), "abgeschlossen", "ih.auftrag.abschliessen"),
    "stornieren": (("angelegt", "freigegeben"), "storniert", "ih.wartung.planen"),
}


def status_aendern(con: Connection, aid: int, aktion: str, benutzer: str, text: str = "") -> str:
    a = auftrag(con, aid)
    if not a:
        raise WartungsFehler("Auftrag nicht gefunden.")
    if aktion not in AKTIONEN:
        raise WartungsFehler("Unbekannte Aktion.")
    von, nach, _ = AKTIONEN[aktion]
    if a["status"] not in von:
        raise WartungsFehler(f"Im Status „{STATUS[a['status']]}“ nicht möglich.")
    pos = positionen(con, aid)
    werte = {"status": nach}
    if aktion == "erledigt":
        offen = [p["code"] for p in pos if not p["ergebnis"]]
        if offen:
            raise WartungsFehler(f"Noch {len(offen)} Bauteile ohne Protokoll: {', '.join(offen[:8])}{' …' if len(offen) > 8 else ''}.")
        if a["massnahme"].startswith("Z") and not con.execute(select(func.count()).select_from(ih_dokumente).where(
                ih_dokumente.c.auftrag_id == aid)).scalar():
            raise WartungsFehler("Pflichtprüfung: Bitte zuerst den Nachweis (z. B. Prüfbescheinigung) hochladen.")
        werte["erledigt_am"] = datetime.now()
    elif aktion == "abschliessen":
        selbst = [p["code"] for p in pos if p["sicherheitsgerichtet"] and p["durchgefuehrt_von"] == benutzer]
        if selbst:
            raise WartungsFehler("Vier-Augen-Prinzip: Sie haben PLT-Sicherheitseinrichtungen in diesem Auftrag selbst geprüft "
                                 f"({', '.join(selbst[:5])}). Abschließen muss eine andere Person.")
        werte.update(abgeschlossen_von=benutzer, abgeschlossen_am=datetime.now())
    elif aktion == "freigeben":
        werte.update(freigegeben_von=benutzer, freigegeben_am=datetime.now())
    elif aktion in ("stornieren", "zurueckweisen"):
        if not text.strip():
            raise WartungsFehler("Bitte einen Grund angeben.")
        if aktion == "stornieren":
            werte["storno_grund"] = text.strip()[:300]
    con.execute(update(ih_auftraege).where(ih_auftraege.c.id == aid).values(**werte))
    _log(con, aid, benutzer, a["status"], nach, text.strip())
    audit(con, benutzer, f"Wartungsauftrag {STATUS[nach].lower()}", f"A-{aid:05d}", {"von": a["status"], "grund": text.strip() or None})
    return nach


def historie(con: Connection, platz_id: int) -> list[dict]:
    """Durchgeführte Maßnahmen an einem Bauteil (neueste zuerst)."""
    return [dict(r) for r in con.execute(
        select(ih_auftrag_positionen.c.ergebnis, ih_auftrag_positionen.c.durchgefuehrt_am, ih_auftrag_positionen.c.durchgefuehrt_von,
               ih_auftrag_positionen.c.befund_nr, ih_auftrag_positionen.c.befund_text, ih_auftrag_positionen.c.formular,
               ih_auftraege.c.id.label("auftrag_id"), ih_auftraege.c.massnahme, ih_auftraege.c.status, ih_auftraege.c.titel)
        .select_from(ih_auftrag_positionen.join(ih_auftraege, ih_auftraege.c.id == ih_auftrag_positionen.c.auftrag_id))
        .where(ih_auftrag_positionen.c.platz_id == platz_id, ih_auftrag_positionen.c.ergebnis.isnot(None))
        .order_by(ih_auftrag_positionen.c.durchgefuehrt_am.desc()).limit(100)).mappings()]


def plan_fuer_bauteil(con: Connection, a: dict) -> list[dict]:
    """Maßnahmen, die für das Bauteil gelten (über die Bauteilklasse oder eigene Kampagnen), mit letzter
    Durchführung und nächstem Termin."""
    letzte = {r.massnahme: r.am for r in con.execute(
        select(ih_auftraege.c.massnahme, func.max(ih_auftrag_positionen.c.durchgefuehrt_am).label("am"))
        .select_from(ih_auftrag_positionen.join(ih_auftraege, ih_auftraege.c.id == ih_auftrag_positionen.c.auftrag_id))
        .where(ih_auftrag_positionen.c.platz_id == a["id"], ih_auftrag_positionen.c.ergebnis.isnot(None))
        .group_by(ih_auftraege.c.massnahme))}
    klasse = (a.get("bauteilklasse") or "").casefold()
    eigene_ids = {r[0] for r in con.execute(select(ih_kampagne_bauteile.c.kampagne_id).where(ih_kampagne_bauteile.c.platz_id == a["id"]))}
    alle = lage(con)
    naechster = {}
    for k in alle:
        if klasse and not k["einzeln"] and (k["bauteilklasse"] or "").casefold() == klasse and k["aktiv"]:
            naechster[k["massnahme"]] = k
    m = massnahmen(con)
    out = []
    if klasse:
        for r in con.execute(select(ih_klassen_intervalle).where(func.lower(ih_klassen_intervalle.c.bauteilklasse) == klasse)).mappings():
            r = dict(r)
            r["mass"] = m.get(r["massnahme"], {"name": r["massnahme"], "symbol": ""})
            r["letzte"] = letzte.get(r["massnahme"])
            r["kampagne"] = naechster.get(r["massnahme"])
            out.append(r)
    for k in alle:  # eigene Kampagnen, die genau dieses Bauteil enthalten
        if k["id"] in eigene_ids:
            out.append({"massnahme": k["massnahme"], "mass": m.get(k["massnahme"], {"name": k["massnahme"], "symbol": ""}),
                        "intervall_monate": k["intervall_monate"], "grundlage": k["taetigkeit"] or k["grundlage"], "achtung": k["hinweis"],
                        "letzte": letzte.get(k["massnahme"]), "kampagne": k, "eigen": True})
    return sorted(out, key=lambda r: (r["mass"].get("reihenfolge") or 0, r.get("eigen", False)))


def offene_auftraege_zahl(con: Connection) -> int:
    return con.execute(select(func.count()).select_from(ih_auftraege).where(ih_auftraege.c.status.in_(OFFEN))).scalar()



# ------------------------------------------------------------------ Eigene Kampagnen
STANDARD_MASSNAHMEN = [
    {"code": "S", "symbol": "●", "name": "Sichtprüfung", "beschreibung": "Äußerlich erkennbare Mängel oder Schäden an Gerät, Installation und "
     "Kennzeichnung feststellen. Keine Demontage, kein Eingriff in den Prozess.", "wer": "Instandhaltung", "nachweis": "Wartungsprotokoll",
     "pflicht": False, "reihenfolge": 0},
    {"code": "W", "symbol": "▲", "name": "Wartung", "beschreibung": "Maßnahmen zum Erhalt des Sollzustands nach der bauteilspezifischen "
     "Wartungsanweisung.", "wer": "Instandhaltung", "nachweis": "Wartungsprotokoll", "pflicht": False, "reihenfolge": 1},
    {"code": "F", "symbol": "■", "name": "Funktionsprüfung", "beschreibung": "Nachweis, dass die Funktion im Anforderungsfall erfüllt wird.",
     "wer": "Instandhaltung / Fachfirma", "nachweis": "Prüfprotokoll", "pflicht": False, "reihenfolge": 2},
]


def massnahmen_sicherstellen(con: Connection) -> None:
    """Ohne übernommenen Instandhaltungsplan gibt es trotzdem S, W und F für eigene Kampagnen."""
    vorhanden = {r[0] for r in con.execute(select(ih_massnahmen.c.code))}
    for m in STANDARD_MASSNAHMEN:
        if m["code"] not in vorhanden:
            con.execute(insert(ih_massnahmen).values(**m))


def schluessel_vorschlag(con: Connection, massnahme: str, text: str) -> str:
    basis = re.sub(r"\s+", " ", f"E-{massnahme}-{text}".strip())[:100]
    vorhanden = {r[0] for r in con.execute(select(ih_kampagnen.c.schluessel))}
    if basis not in vorhanden:
        return basis
    n = 2
    while f"{basis}-{n}" in vorhanden:
        n += 1
    return f"{basis}-{n}"


# ------------------------------------------------------------------ Ersatzteile (Stückliste) und Entnahme für Aufträge
def orte(con: Connection, artikel_ids: list[int]) -> dict[int, list[tuple[str, float]]]:
    out: dict[int, list] = {}
    if not artikel_ids:
        return out
    for aid, code, menge in con.execute(select(bestand.c.artikel_id, lagerplaetze.c.code, bestand.c.menge)
                                        .select_from(bestand.join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id))
                                        .where(bestand.c.artikel_id.in_(artikel_ids), bestand.c.menge != 0).order_by(lagerplaetze.c.code)):
        out.setdefault(aid, []).append((code, float(menge)))
    return out


def ersatzteile_platz(con: Connection, platz_id: int) -> list[dict]:
    rows = [dict(r) for r in con.execute(
        select(ih_stueckliste.c.id.label("sid"), ih_stueckliste.c.menge.label("je_bauteil"), ih_stueckliste.c.bemerkung, artikel.c.id,
               artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, artikel.c.meldebestand, artikel.c.aktiv)
        .select_from(ih_stueckliste.join(artikel, artikel.c.id == ih_stueckliste.c.artikel_id))
        .where(ih_stueckliste.c.platz_id == platz_id).order_by(artikel.c.nummer)).mappings()]
    o = orte(con, [r["id"] for r in rows])
    for r in rows:
        r["orte"] = o.get(r["id"], [])
        r["bestand"] = sum(m for _, m in r["orte"])
    return rows


def ersatzteile_auftrag(con: Connection, aid: int) -> list[dict]:
    """Ersatzteile aller Bauteile im Auftrag, zusammengefasst je Artikel, mit Lagerbestand und bereits Entnommenem."""
    rows = con.execute(select(artikel.c.id, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, ih_plaetze.c.code, ih_stueckliste.c.menge)
                       .select_from(ih_auftrag_positionen.join(ih_stueckliste, ih_stueckliste.c.platz_id == ih_auftrag_positionen.c.platz_id)
                                    .join(artikel, artikel.c.id == ih_stueckliste.c.artikel_id)
                                    .join(ih_plaetze, ih_plaetze.c.id == ih_auftrag_positionen.c.platz_id))
                       .where(ih_auftrag_positionen.c.auftrag_id == aid).order_by(artikel.c.nummer, ih_plaetze.c.code)).all()
    teile: dict[int, dict] = {}
    for r in rows:
        t = teile.setdefault(r.id, {"id": r.id, "nummer": r.nummer, "bezeichnung": r.bezeichnung, "einheit": r.einheit, "bauteile": [], "bedarf": 0.0})
        t["bauteile"].append(r.code)
        t["bedarf"] += r.menge or 0
    for t in entnahmen(con, aid):
        if t["artikel_id"] not in teile and t["artikel_id"]:
            teile[t["artikel_id"]] = {"id": t["artikel_id"], "nummer": t["artikel_nr"], "bezeichnung": t["bezeichnung"], "einheit": t["einheit"],
                                      "bauteile": [], "bedarf": 0.0}
    o = orte(con, list(teile))
    ent: dict[int, float] = {}
    for e in entnahmen(con, aid):
        ent[e["artikel_id"]] = ent.get(e["artikel_id"], 0) - e["menge"]
    for t in teile.values():
        t["orte"] = o.get(t["id"], [])
        t["bestand"] = sum(m for _, m in t["orte"])
        t["entnommen"] = ent.get(t["id"], 0)
    return list(teile.values())


def entnahmen(con: Connection, aid: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        select(bewegungen.c.id, bewegungen.c.zeit, bewegungen.c.artikel_id, bewegungen.c.artikel_nr, bewegungen.c.lagerplatz, bewegungen.c.menge,
               bewegungen.c.preis, bewegungen.c.benutzer, bewegungen.c.typ, artikel.c.bezeichnung, artikel.c.einheit)
        .select_from(bewegungen.outerjoin(artikel, artikel.c.id == bewegungen.c.artikel_id))
        .where(bewegungen.c.auftrag_id == aid, bewegungen.c.typ == "ausgang", bewegungen.c.storniert_durch.is_(None))  # im Lager stornierte zählen nicht
        .order_by(bewegungen.c.id)).mappings()]


def tag_muster(code: str) -> re.Pattern:
    """Tag-Nr. in Freitext finden: Leerzeichen zwischen den Teilen beliebig, nicht als Teil einer längeren Nummer."""
    teile = [re.escape(t) for t in code.split()]
    return re.compile(r"(?<![0-9A-Za-z])" + r"\s*".join(teile) + r"(?![0-9A-Za-z])", re.IGNORECASE)


def vorschlaege_aus_verwendung(con: Connection, nur_platz: int | None = None) -> list[dict]:
    """Artikel, deren Feld „Verwendung“ eine Tag-Nr. nennt, die noch nicht zugeordnet ist."""
    q = select(ih_plaetze.c.id, ih_plaetze.c.code, ih_plaetze.c.bezeichnung).where(ih_plaetze.c.art == "platz", ih_plaetze.c.aktiv,
                                                                                   func.length(ih_plaetze.c.schluessel) >= 5)
    if nur_platz:
        q = q.where(ih_plaetze.c.id == nur_platz)
    plaetze = [(r.id, r.code, r.bezeichnung, tag_muster(r.code)) for r in con.execute(q)]
    schon = {(r.artikel_id, r.platz_id) for r in con.execute(select(ih_stueckliste.c.artikel_id, ih_stueckliste.c.platz_id))}
    out = []
    for a in con.execute(select(artikel.c.id, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.verwendung)
                         .where(artikel.c.aktiv, artikel.c.verwendung.isnot(None), artikel.c.verwendung != "").order_by(artikel.c.nummer)):
        treffer = [{"id": pid, "code": code, "bezeichnung": bez} for pid, code, bez, m in plaetze
                   if (a.id, pid) not in schon and m.search(a.verwendung)]
        if treffer:
            out.append({"id": a.id, "nummer": a.nummer, "bezeichnung": a.bezeichnung, "verwendung": a.verwendung, "tags": treffer})
    return out


def zuordnen(con: Connection, artikel_id: int, platz_id: int, benutzer: str, menge: float | None = None, bemerkung: str | None = None) -> bool:
    if con.execute(select(ih_stueckliste.c.id).where(ih_stueckliste.c.artikel_id == artikel_id, ih_stueckliste.c.platz_id == platz_id)).scalar():
        return False
    con.execute(insert(ih_stueckliste).values(artikel_id=artikel_id, platz_id=platz_id, menge=menge, bemerkung=bemerkung, erstellt_von=benutzer,
                                              erstellt_am=datetime.now()))
    return True
