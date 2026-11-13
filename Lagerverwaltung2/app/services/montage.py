"""Montageunterstützung (ab 2.12.0): Stutzenübersicht und Montageprotokolle für Reaktorstutzen / Dichtungen / Schrauben.

* Stutzenübersicht (``mt_stutzen`` + ``mt_stutzen_dichtungen``): Soll-Werte je Stutzen – Dichtungen (bis 3), Anzahl Schrauben,
  Gewinde, Schraubenlänge, Drehmoment … Import aus der Excel-Vorlage (Blatt „Stutzen Übersicht“, Nenndicke aus „Zuordnung Dichtungen“).
* Montageprotokoll (``mt_protokolle``): wird in zwei Schritten ausgefüllt (vorher Kopf und Dichtungen, nach der Montage Drehmomente
  und Reihenfolge), Zwischenspeichern jederzeit. Abgeschlossene Protokolle ändert nur, wer ``ih.montage.korrigieren`` hat –
  mit Grund, jede Änderung steht mit Alt → Neu im Verlauf (``mt_verlauf``).
* Skizze: Flansch mit n gleichmäßig verteilten Schraubenlöchern (Loch 1 oben, im Uhrzeigersinn). Die Reihenfolge des Anziehens
  wird durch Anklicken der Löcher festgelegt: ``reihenfolge[k]`` = Loch der Schraube auf Pos. k+1.
* „#“ in einer Zelle der Schraubentabelle = gleicher Wert wie eine Zeile darüber (beim Speichern aufgelöst; Anzeige und Druck
  zeigen Wiederholungen wieder als „#“).
"""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import artikel, bestand, mt_protokolle, mt_stutzen, mt_stutzen_dichtungen, mt_verlauf
from .lager import BuchungsFehler, fmt_num, parse_num

MAX_SCHRAUBEN = 100
DITTO = "#"
STUTZEN_FELDER = ["gruppe", "kuerzel", "bezeichnung", "anlage", "schrauben_anzahl", "gewinde", "schraube_typ", "schraube_laenge",
                  "schraube_werkstoff", "drehmoment", "schmiermittel", "bemerkung"]
DICHTUNG_FELDER = ["einbauort", "dichtungsart", "artikel_nr", "nenndicke", "ist_dicke", "alt_neu"]
SCHRAUBEN_FELDER = ["typ", "groesse", "laenge_soll", "laenge_ist", "werkstoff", "soll_nm", "ist_nm", "alt_neu", "bemerkung"]
DITTO_FELDER = ["typ", "groesse", "laenge_soll", "laenge_ist", "werkstoff", "soll_nm", "ist_nm"]  # dürfen „#“ sein
KOPF_FELDER = ["anlage", "datum", "monteur", "pruefer", "arbeitsauftrag", "reinigung", "schmiermittel", "bemerkung_dichtungen",
               "bemerkungen", "montage_abgeschlossen", "lecktest", "abschluss_zeit"]
FELD_NAMEN = {"anlage": "Anlage / Reaktor", "datum": "Datum", "monteur": "Monteur", "pruefer": "Prüfer", "arbeitsauftrag": "Arbeitsauftrag",
              "reinigung": "Reinigung", "schmiermittel": "Schmiermittel", "bemerkung_dichtungen": "Bemerkung Dichtungen",
              "bemerkungen": "Allgemeine Bemerkungen", "montage_abgeschlossen": "Montage abgeschlossen", "lecktest": "Lecktest",
              "abschluss_zeit": "Datum / Uhrzeit", "stutzen": "Stutzen", "schrauben_anzahl": "Anzahl Schrauben", "reihenfolge": "Reihenfolge",
              "einbauort": "Einbauort", "dichtungsart": "Dichtungsart", "artikel_nr": "Artikel-Nr.", "nenndicke": "Nenndicke",
              "ist_dicke": "Ist-Dicke", "alt_neu": "Alt/Neu", "typ": "Typ / Norm", "groesse": "Größe / Gewinde", "laenge_soll": "Länge-Soll",
              "laenge_ist": "Länge-Ist", "werkstoff": "Werkstoff / Klasse", "soll_nm": "Soll [Nm]", "ist_nm": "Ist [Nm]", "bemerkung": "Bemerkung"}
STATUS = {"entwurf": "In Arbeit", "abgeschlossen": "Abgeschlossen"}
LECKTEST = {"bestanden": "bestanden", "offen": "offen", "nb": "n. b."}


def _t(v, n: int = 300) -> str | None:
    s = " ".join(str(v).split()) if v is not None else ""
    return s[:n] or None


def _zahl_text(v) -> str | None:
    """Excel-Werte als Text: 125.0 -> „125“, 3.18 -> „3,18“, Text bleibt Text."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return fmt_num(v)
    return _t(v, 60)


def ungeklaert(*werte) -> bool:
    return any("?" in str(w or "") for w in werte)


# ------------------------------------------------------------------ Stutzen
def stutzen_label(s: dict) -> str:
    teile = [s.get("kuerzel") or ""]
    if s.get("bezeichnung"):
        teile.append(s["bezeichnung"])
    t = " – ".join(teile)
    return f"{t} ({s['gruppe']})" if s.get("gruppe") else t


def dichtungen_von(con: Connection, sid: int) -> list[dict]:
    rows = [dict(r) for r in con.execute(select(mt_stutzen_dichtungen).where(mt_stutzen_dichtungen.c.stutzen_id == sid)
                                         .order_by(mt_stutzen_dichtungen.c.pos)).mappings()]
    for d in rows:
        d["bestand"] = None
        if d["artikel_id"]:
            a = con.execute(select(artikel.c.nummer).where(artikel.c.id == d["artikel_id"])).scalar()
            d["lager_nr"] = a
            d["bestand"] = float(con.execute(select(func.coalesce(func.sum(bestand.c.menge), 0)).where(bestand.c.artikel_id == d["artikel_id"])).scalar())
    return rows


def stutzen_liste(con: Connection, q: str = "", gruppe: str = "", archiv: bool = False) -> list[dict]:
    qy = select(mt_stutzen).where(mt_stutzen.c.aktiv.is_(not archiv))
    rows = [dict(r) for r in con.execute(qy.order_by(mt_stutzen.c.reihenfolge, mt_stutzen.c.id)).mappings()]
    letzte = {r.stutzen_id: (r.datum, r.anzahl) for r in con.execute(
        select(mt_protokolle.c.stutzen_id, func.max(mt_protokolle.c.datum).label("datum"), func.count().label("anzahl"))
        .group_by(mt_protokolle.c.stutzen_id))}
    alle_d: dict[int, list] = {}
    for d in con.execute(select(mt_stutzen_dichtungen).order_by(mt_stutzen_dichtungen.c.pos)).mappings():
        alle_d.setdefault(d["stutzen_id"], []).append(dict(d))
    q = q.strip().casefold()
    aus = []
    for s in rows:
        s["dichtungen"] = alle_d.get(s["id"], [])
        s["label"] = stutzen_label(s)
        s["ungeklaert"] = ungeklaert(s["drehmoment"], s["schraube_laenge"], s["gewinde"], s["schrauben_anzahl"])
        s["letztes_datum"], s["protokolle"] = letzte.get(s["id"], (None, 0))
        if gruppe and (s["gruppe"] or "") != gruppe:
            continue
        if q:
            text = " ".join(str(x or "") for x in [s["kuerzel"], s["bezeichnung"], s["gruppe"], s["anlage"], s["gewinde"]]
                            + [f"{d['dichtungsart']} {d['durchmesser']} {d['artikel_nr']}" for d in s["dichtungen"]]).casefold()
            if q not in text and q.replace(" ", "") not in text.replace(" ", ""):
                continue
        aus.append(s)
    return aus


def stutzen_get(con: Connection, sid: int) -> dict | None:
    s = con.execute(select(mt_stutzen).where(mt_stutzen.c.id == sid)).mappings().first()
    if not s:
        return None
    s = dict(s)
    s["dichtungen"] = dichtungen_von(con, sid)
    s["label"] = stutzen_label(s)
    s["ungeklaert"] = ungeklaert(s["drehmoment"], s["schraube_laenge"], s["gewinde"])
    return s


def gruppen(con: Connection) -> list[str]:
    return [r[0] for r in con.execute(select(mt_stutzen.c.gruppe).where(mt_stutzen.c.gruppe.is_not(None), mt_stutzen.c.aktiv)
                                      .group_by(mt_stutzen.c.gruppe).order_by(func.min(mt_stutzen.c.reihenfolge)))]


def artikel_zu(con: Connection, artikel_nr: str | None) -> int | None:
    """Lagerartikel zur Dichtungsbezeichnung (Artikelnummer, Hersteller-, Lieferanten- oder Typenbezeichnung)."""
    if not artikel_nr:
        return None
    k = " ".join(artikel_nr.split()).casefold()
    for spalte in (artikel.c.nummer, artikel.c.hersteller_nr, artikel.c.lieferant_artnr, artikel.c.typ):
        for aid, wert in con.execute(select(artikel.c.id, spalte).where(artikel.c.aktiv, spalte.is_not(None))):
            if " ".join(str(wert).split()).casefold() == k:
                return aid
    return None


def _schrauben_anzahl(v) -> int | None:
    if v in (None, ""):
        return None
    n = parse_num(v)
    if n is None or n != int(n) or not 1 <= n <= MAX_SCHRAUBEN:
        raise BuchungsFehler(f"Anzahl Schrauben „{v}“: bitte eine ganze Zahl von 1 bis {MAX_SCHRAUBEN}.")
    return int(n)


def stutzen_speichern(con: Connection, sid: int | None, daten: dict, dichtungen: list[dict], benutzer: str) -> int:
    werte = {f: _t(daten.get(f), 2000 if f == "bemerkung" else 200) for f in STUTZEN_FELDER if f != "schrauben_anzahl"}
    werte["schrauben_anzahl"] = _schrauben_anzahl(daten.get("schrauben_anzahl"))
    if not werte["kuerzel"]:
        raise BuchungsFehler("Bitte die Stutzen-Bezeichnung (Kürzel, z. B. RL 1) angeben.")
    doppelt = con.execute(select(mt_stutzen.c.id).where(
        func.coalesce(mt_stutzen.c.gruppe, "") == (werte["gruppe"] or ""), mt_stutzen.c.kuerzel == werte["kuerzel"],
        func.coalesce(mt_stutzen.c.bezeichnung, "") == (werte["bezeichnung"] or ""), mt_stutzen.c.id != (sid or 0))).scalar()
    if doppelt:
        raise BuchungsFehler(f"Den Stutzen {stutzen_label(werte)} gibt es schon.")
    jetzt = datetime.now().replace(microsecond=0)
    if sid:
        con.execute(update(mt_stutzen).where(mt_stutzen.c.id == sid).values(geaendert_am=jetzt, geaendert_von=benutzer, **werte))
    else:
        rf = (con.execute(select(func.max(mt_stutzen.c.reihenfolge))).scalar() or 0) + 1
        sid = con.execute(insert(mt_stutzen).values(erstellt_am=jetzt, erstellt_von=benutzer, reihenfolge=rf, aktiv=True, **werte)).inserted_primary_key[0]
    _dichtungen_setzen(con, sid, dichtungen)
    return sid


def _dichtungen_setzen(con: Connection, sid: int, dichtungen: list[dict]) -> None:
    con.execute(mt_stutzen_dichtungen.delete().where(mt_stutzen_dichtungen.c.stutzen_id == sid))
    pos = 0
    for d in dichtungen:
        w = {f: _t(d.get(f), 200) for f in ("einbauort", "dichtungsart", "durchmesser", "artikel_nr")}
        if not any(w.values()):
            continue
        pos += 1
        if pos > 3:
            raise BuchungsFehler("Das Montageprotokoll hat Platz für höchstens 3 Dichtungen je Stutzen.")
        nd = d.get("nenndicke")
        nd = parse_num(nd) if not isinstance(nd, (int, float)) else float(nd)
        menge = d.get("menge")
        menge = parse_num(menge) if not isinstance(menge, (int, float)) else float(menge)
        aid = d.get("artikel_id")
        aid = int(aid) if str(aid or "").isdigit() else artikel_zu(con, w["artikel_nr"])
        con.execute(insert(mt_stutzen_dichtungen).values(stutzen_id=sid, pos=pos, nenndicke=nd, menge=menge, artikel_id=aid, **w))


# ------------------------------------------------------------------ Import aus der Excel-Vorlage
def _kopf_finden(ws, pflicht: tuple[str, ...]):
    for r in range(1, min(ws.max_row, 15) + 1):
        werte = {}
        for c in range(1, min(ws.max_column, 40) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                werte[" ".join(v.split()).casefold()] = c
        if all(any(p in k for k in werte) for p in pflicht):
            return r, werte
    return None, None


def _spalte(kopf: dict, *namen) -> int | None:
    for n in namen:
        for k, c in kopf.items():
            if k.startswith(n):
                return c
    return None


DICKE_IM_CODE = re.compile(r"-(\d{1,2}[,.]\d{1,3})\s*w\b", re.I)


def import_lesen(inhalt: bytes, gruppe_anfang: str = "") -> dict:
    """Excel lesen (ohne zu speichern): Stutzen mit ihren Dichtungen, Hinweise. Spalte ohne Überschrift nach
    „Schrauben Länge Soll“ = Gewinde/Schraubengröße (wie in der Vorlage)."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(inhalt), data_only=True, read_only=False)
    except Exception as e:
        raise BuchungsFehler(f"Die Datei lässt sich nicht als Excel-Datei (.xlsx) öffnen: {e}") from e
    blatt = kopf = kopfzeile = None
    for ws in wb.worksheets:
        kz, k = _kopf_finden(ws, ("stutzen", "dichtungsart", "drehmoment"))
        if kz:
            blatt, kopf, kopfzeile = ws, k, kz
            break
    if not blatt:
        raise BuchungsFehler("Kein Blatt mit den Spalten „Stutzen“, „Dichtungsart“ und „Soll Drehmoment“ gefunden (Blatt „Stutzen Übersicht“).")
    sp = {"bezeichnung": _spalte(kopf, "bezeichnung"), "kuerzel": _spalte(kopf, "stutzen"), "dichtungsart": _spalte(kopf, "dichtungsart"),
          "durchmesser": _spalte(kopf, "dichtungsdurchmesser", "durchmesser"), "artikel_nr": _spalte(kopf, "auftragsnummer", "artikel"),
          "drehmoment": _spalte(kopf, "soll drehmoment", "drehmoment"), "schraube_laenge": _spalte(kopf, "schrauben länge", "schraubenlänge", "länge"),
          "gewinde": _spalte(kopf, "gewinde", "schraubengröße", "größe"), "schrauben_anzahl": _spalte(kopf, "anzahl schrauben", "schraubenanzahl", "anzahl"),
          "nenndicke": _spalte(kopf, "nenndicke", "dicke- soll", "dicke soll")}
    hinweise = []
    if not sp["gewinde"] and sp["schraube_laenge"]:
        c = sp["schraube_laenge"] + 1
        if not blatt.cell(kopfzeile, c).value:
            sp["gewinde"] = c
    # Nenndicke aus „Zuordnung Dichtungen“ (Auftragsnummer -> Dicke-Soll)
    dicken: dict[str, float] = {}
    for ws in wb.worksheets:
        kz, k = _kopf_finden(ws, ("auftragsnummer", "dicke"))
        if not kz or ws is blatt:
            continue
        ca, cd = _spalte(k, "auftragsnummer"), _spalte(k, "dicke- soll", "dicke soll", "dicke-soll", "nenndicke")
        if ca and cd:
            for r in range(kz + 1, ws.max_row + 1):
                a, d = ws.cell(r, ca).value, ws.cell(r, cd).value
                if a and isinstance(d, (int, float)):
                    dicken[" ".join(str(a).split()).casefold()] = float(d)
    stutzen: dict[tuple, dict] = {}
    gruppe = _t(gruppe_anfang, 100)
    leer = 0
    for r in range(kopfzeile + 1, blatt.max_row + 1):
        w = {k: (blatt.cell(r, c).value if c else None) for k, c in sp.items()}
        if all(v in (None, "") for v in w.values()):
            leer += 1
            if leer > 20:
                break
            continue
        leer = 0
        sonst = [k for k, v in w.items() if v not in (None, "") and k != "kuerzel" and k != "bezeichnung"]
        if not sonst and bool(w["kuerzel"]) != bool(w["bezeichnung"]):  # Zwischenüberschrift, z. B. „WHRU Stutzen“, „Verlängerung 1“
            gruppe = _t(w["kuerzel"] or w["bezeichnung"], 100)
            continue
        kuerzel = _t(w["kuerzel"], 40)
        if not kuerzel:
            hinweise.append(f"Zeile {r}: ohne Stutzen-Bezeichnung – übersprungen.")
            continue
        bez = _t(w["bezeichnung"], 200)
        key = (gruppe or "", kuerzel, bez or "")
        s = stutzen.setdefault(key, {"gruppe": gruppe, "kuerzel": kuerzel, "bezeichnung": bez, "dichtungen": [], "zeile": r})
        for f in ("drehmoment", "schraube_laenge", "gewinde"):
            v = _zahl_text(w[f])
            if v and not s.get(f):
                s[f] = v
            elif v and s.get(f) != v:
                hinweise.append(f"Zeile {r}: {kuerzel} hat unterschiedliche Werte für {FELD_NAMEN.get(f, f)} ({s[f]} / {v}) – erster Wert übernommen.")
        if w["schrauben_anzahl"] not in (None, "") and not s.get("schrauben_anzahl"):
            try:
                s["schrauben_anzahl"] = _schrauben_anzahl(w["schrauben_anzahl"])
            except BuchungsFehler as e:
                hinweise.append(f"Zeile {r}: {e}")
        an = _t(w["artikel_nr"], 200)
        if w["dichtungsart"] or w["durchmesser"] or an:
            nd = w["nenndicke"] if isinstance(w["nenndicke"], (int, float)) else dicken.get((an or "").casefold())
            if nd is None and an and (m := DICKE_IM_CODE.search(an)):
                nd = parse_num(m.group(1))
            s["dichtungen"].append({"dichtungsart": _t(w["dichtungsart"], 100), "durchmesser": _zahl_text(w["durchmesser"]),
                                    "artikel_nr": an, "nenndicke": nd})
    for s in stutzen.values():
        if len(s["dichtungen"]) > 3:
            hinweise.append(f"{stutzen_label(s)}: {len(s['dichtungen'])} Dichtungen – das Protokoll hat 3 Zeilen, nur die ersten 3 übernommen.")
            s["dichtungen"] = s["dichtungen"][:3]
        if ungeklaert(s.get("drehmoment"), s.get("schraube_laenge")):
            hinweise.append(f"{stutzen_label(s)}: Wert mit „?“ ({s.get('drehmoment') or ''} {s.get('schraube_laenge') or ''}) – als ungeklärt markiert.")
    return {"blatt": blatt.title, "stutzen": list(stutzen.values()), "hinweise": hinweise}


def import_uebernehmen(con: Connection, gelesen: dict, benutzer: str) -> dict:
    """Neue Stutzen anlegen, vorhandene (gleiche Gruppe, Kürzel, Bezeichnung) ergänzen. Löscht nichts. Werte aus der Datei
    überschreiben nur, wo die Datei einen Wert hat; die Dichtungen eines Stutzens werden durch die aus der Datei ersetzt."""
    jetzt = datetime.now().replace(microsecond=0)
    neu = geaendert = 0
    rf = con.execute(select(func.max(mt_stutzen.c.reihenfolge))).scalar() or 0
    for s in gelesen["stutzen"]:
        vorh = con.execute(select(mt_stutzen).where(
            func.coalesce(mt_stutzen.c.gruppe, "") == (s["gruppe"] or ""), mt_stutzen.c.kuerzel == s["kuerzel"],
            func.coalesce(mt_stutzen.c.bezeichnung, "") == (s["bezeichnung"] or ""))).mappings().first()
        werte = {f: s.get(f) for f in ("drehmoment", "schraube_laenge", "gewinde", "schrauben_anzahl") if s.get(f) not in (None, "")}
        anders = False
        if vorh:
            aend = {k: v for k, v in werte.items() if vorh[k] != v}
            if aend or not vorh["aktiv"]:
                con.execute(update(mt_stutzen).where(mt_stutzen.c.id == vorh["id"]).values(aktiv=True, geaendert_am=jetzt, geaendert_von=benutzer, **aend))
                anders = True
            sid = vorh["id"]
        else:
            rf += 1
            sid = con.execute(insert(mt_stutzen).values(gruppe=s["gruppe"], kuerzel=s["kuerzel"], bezeichnung=s["bezeichnung"], reihenfolge=rf,
                                                        aktiv=True, erstellt_am=jetzt, erstellt_von=benutzer, **werte)).inserted_primary_key[0]
            neu += 1
        if s["dichtungen"]:
            alt = [(d["dichtungsart"], d["durchmesser"], d["artikel_nr"], d["nenndicke"]) for d in dichtungen_von(con, sid)]
            if alt != [(d["dichtungsart"], d["durchmesser"], d["artikel_nr"], d["nenndicke"]) for d in s["dichtungen"]]:
                _dichtungen_setzen(con, sid, s["dichtungen"])
                anders = True
        if vorh and anders:
            geaendert += 1
    return {"neu": neu, "geaendert": geaendert, "gesamt": len(gelesen["stutzen"]),
            "dichtungen": sum(len(s["dichtungen"]) for s in gelesen["stutzen"])}


# ------------------------------------------------------------------ Protokoll: Daten
def leere_dichtungen() -> list[dict]:
    return [{f: "" for f in DICHTUNG_FELDER} for _ in range(3)]


def vorbelegung(st: dict | None, n: int | None = None) -> dict:
    """Soll-Werte aus der Stutzenübersicht: Dichtungen 1–3, Schrauben (Zeile 1 mit Werten, darunter „#“)."""
    d = leere_dichtungen()
    zeile = {f: "" for f in SCHRAUBEN_FELDER}
    if st:
        for i, x in enumerate((st.get("dichtungen") or [])[:3]):
            art = " ".join(v for v in [x.get("dichtungsart"), x.get("durchmesser")] if v)
            d[i].update(einbauort=x.get("einbauort") or "", dichtungsart=art, artikel_nr=x.get("artikel_nr") or "",
                        nenndicke=fmt_num(x["nenndicke"]) if x.get("nenndicke") is not None else "")
        zeile.update(typ=st.get("schraube_typ") or "", groesse=st.get("gewinde") or "", laenge_soll=st.get("schraube_laenge") or "",
                     werkstoff=st.get("schraube_werkstoff") or "", soll_nm=st.get("drehmoment") or "")
        n = n or st.get("schrauben_anzahl")
    schr = []
    for i in range(n or 0):
        z = dict(zeile) if i == 0 else {f: (DITTO if zeile.get(f) and f in DITTO_FELDER else "") for f in SCHRAUBEN_FELDER}
        schr.append(z)
    return {"dichtungen": d, "schrauben": schr, "schrauben_anzahl": n,
            "anlage": (st or {}).get("anlage") or "", "schmiermittel": (st or {}).get("schmiermittel") or ""}


def ditto_aufloesen(zeilen: list[dict]) -> list[dict]:
    """„#“ (oder Anführungszeichen) = Wert der Zeile darüber – vor dem Speichern in echte Werte umwandeln."""
    aus, vorher = [], {}
    for z in zeilen:
        neu = {}
        for f in SCHRAUBEN_FELDER:
            v = (z.get(f) or "").strip() if isinstance(z.get(f), str) else z.get(f)
            if f in DITTO_FELDER and v in (DITTO, '"', "〃", "''"):
                v = vorher.get(f, "")
            neu[f] = v or ""
        aus.append(neu)
        vorher = neu
    return aus


def ditto_anzeige(zeilen: list[dict]) -> list[dict]:
    """Für Formular und Ausdruck: Wert gleich wie in der Zeile darüber -> „#“."""
    aus, vorher = [], None
    for z in zeilen:
        neu = dict(z)
        if vorher is not None:
            for f in DITTO_FELDER:
                if z.get(f) and z.get(f) == vorher.get(f):
                    neu[f] = DITTO
        aus.append(neu)
        vorher = z
    return aus


def kennzeichnung(kuerzel: str | None, pos: int, ist_nm) -> str:
    """Format laut Ausfüllhinweisen: Stutzen – Position – Ist-Drehmoment, z. B. RO-1-65 Nm."""
    k = (kuerzel or "").replace(" ", "")
    t = f"{k}-{pos}" if k else str(pos)
    return f"{t}-{ist_nm} Nm" if ist_nm not in (None, "") else t


def laden(con: Connection, pid: int) -> dict | None:
    p = con.execute(select(mt_protokolle).where(mt_protokolle.c.id == pid)).mappings().first()
    if not p:
        return None
    p = dict(p)
    p["dichtungen"] = json.loads(p["dichtungen"] or "[]") or leere_dichtungen()
    while len(p["dichtungen"]) < 3:
        p["dichtungen"].append({f: "" for f in DICHTUNG_FELDER})
    p["schrauben"] = json.loads(p["schrauben"] or "[]")
    p["reihenfolge"] = json.loads(p["reihenfolge"] or "[]")
    for i, z in enumerate(p["schrauben"]):
        z["kennzeichnung"] = kennzeichnung(p["stutzen"], i + 1, z.get("ist_nm"))
    p["verlauf"] = [dict(r) for r in con.execute(select(mt_verlauf).where(mt_verlauf.c.protokoll_id == pid).order_by(mt_verlauf.c.zeit, mt_verlauf.c.id)).mappings()]
    for v in p["verlauf"]:
        v["aenderungen"] = json.loads(v["aenderungen"]) if v["aenderungen"] else []
    return p


def liste(con: Connection, q: str = "", status: str = "", stutzen_id: int | None = None, von: date | None = None, bis: date | None = None,
          limit: int = 500) -> list[dict]:
    qy = select(mt_protokolle.c.id, mt_protokolle.c.nummer, mt_protokolle.c.status, mt_protokolle.c.stutzen, mt_protokolle.c.stutzen_bez,
                mt_protokolle.c.stutzen_id, mt_protokolle.c.anlage, mt_protokolle.c.datum, mt_protokolle.c.monteur, mt_protokolle.c.pruefer,
                mt_protokolle.c.arbeitsauftrag, mt_protokolle.c.schrauben_anzahl, mt_protokolle.c.lecktest, mt_protokolle.c.montage_abgeschlossen,
                mt_protokolle.c.geaendert_am, mt_protokolle.c.erstellt_am, mt_protokolle.c.erstellt_von, mt_protokolle.c.reihenfolge,
                mt_protokolle.c.schrauben)
    if status:
        qy = qy.where(mt_protokolle.c.status == status)
    if stutzen_id:
        qy = qy.where(mt_protokolle.c.stutzen_id == stutzen_id)
    if von:
        qy = qy.where(mt_protokolle.c.datum >= von)
    if bis:
        qy = qy.where(mt_protokolle.c.datum <= bis)
    rows = []
    q = q.strip().casefold()
    for r in con.execute(qy.order_by(mt_protokolle.c.datum.desc(), mt_protokolle.c.id.desc())).mappings():
        r = dict(r)
        if q and q not in " ".join(str(r[k] or "") for k in ("nummer", "stutzen", "stutzen_bez", "anlage", "monteur", "pruefer", "arbeitsauftrag")).casefold():
            continue
        schr = json.loads(r.pop("schrauben") or "[]")
        r["ist_fehlt"] = sum(1 for z in schr if not str(z.get("ist_nm") or "").strip())
        r["folge"] = len(json.loads(r.pop("reihenfolge") or "[]"))
        rows.append(r)
        if len(rows) >= limit:
            break
    return rows


def neue_nummer(con: Connection, jahr: int) -> str:
    praefix = f"MP-{jahr}-"
    letzte = con.execute(select(func.max(mt_protokolle.c.nummer)).where(mt_protokolle.c.nummer.like(praefix + "%"))).scalar()
    n = int(letzte.rsplit("-", 1)[1]) + 1 if letzte else 1
    return f"{praefix}{n:04d}"


def aus_formular(form, st: dict | None) -> dict:
    """Formular -> Protokoll-Daten (ohne Status). ``form`` ist ein Starlette-FormData (mehrfache Felder)."""
    g = lambda k, n=300: _t(form.get(k), n)  # noqa: E731
    d = {k: g(k, 4000 if k in ("bemerkungen", "bemerkung_dichtungen") else 300) for k in KOPF_FELDER}
    d["datum"] = None
    if form.get("datum"):
        try:
            d["datum"] = date.fromisoformat(form.get("datum"))
        except ValueError as e:
            raise BuchungsFehler("Datum bitte als TT.MM.JJJJ angeben.") from e
    if d["montage_abgeschlossen"] not in ("ja", "nein"):
        d["montage_abgeschlossen"] = None
    if d["lecktest"] not in LECKTEST:
        d["lecktest"] = None
    n = _schrauben_anzahl(form.get("schrauben_anzahl"))
    d["schrauben_anzahl"] = n
    d["dichtungen"] = []
    for i in range(3):
        x = {f: _t(form.get(f"d{i}_{f}"), 200) or "" for f in DICHTUNG_FELDER}
        if x["alt_neu"] not in ("alt", "neu"):
            x["alt_neu"] = ""
        for f in ("nenndicke", "ist_dicke"):
            if x[f] and parse_num(x[f]) is None:
                raise BuchungsFehler(f"Dichtung {i + 1}, {FELD_NAMEN[f]}: „{x[f]}“ ist keine Zahl.")
        d["dichtungen"].append(x)
    zeilen = []
    for i in range(n or 0):
        z = {f: _t(form.get(f"s{i}_{f}"), 200) or "" for f in SCHRAUBEN_FELDER}
        if z["alt_neu"] not in ("alt", "neu"):
            z["alt_neu"] = ""
        zeilen.append(z)
    d["schrauben"] = ditto_aufloesen(zeilen)
    for i, z in enumerate(d["schrauben"]):
        for f in ("laenge_ist", "ist_nm"):
            if z[f] and parse_num(z[f]) is None:
                raise BuchungsFehler(f"Schraube Pos. {i + 1}, {FELD_NAMEN[f]}: „{z[f]}“ ist keine Zahl.")
    try:
        folge = [int(x) for x in json.loads(form.get("reihenfolge") or "[]")]
    except (ValueError, TypeError) as e:
        raise BuchungsFehler("Reihenfolge der Schrauben ist ungültig.") from e
    folge = [x for x in folge if 1 <= x <= (n or 0)]
    if len(set(folge)) != len(folge):
        raise BuchungsFehler("Reihenfolge: ein Schraubenloch ist doppelt nummeriert.")
    d["reihenfolge"] = folge
    if st:
        d["stutzen_id"], d["stutzen"], d["stutzen_bez"] = st["id"], st["kuerzel"], stutzen_label(st)
    else:
        d["stutzen_id"], d["stutzen"] = None, g("stutzen", 40)
        d["stutzen_bez"] = d["stutzen"]
    return d


def fehlende_angaben(p: dict) -> list[str]:
    """Was vor dem Abschluss noch fehlt (Hinweis, kein Zwang – „trotzdem abschließen“ ist möglich)."""
    f = []
    for k in ("stutzen", "anlage", "datum", "monteur", "pruefer"):
        if not p.get(k):
            f.append(FELD_NAMEN[k])
    n = p.get("schrauben_anzahl") or 0
    if not n:
        f.append("Anzahl Schrauben")
    else:
        if len(p.get("reihenfolge") or []) < n:
            f.append(f"Reihenfolge in der Skizze ({len(p.get('reihenfolge') or [])} von {n} Schrauben nummeriert)")
        leer = [str(i + 1) for i, z in enumerate(p.get("schrauben") or []) if not str(z.get("ist_nm") or "").strip()]
        if leer:
            f.append(f"Ist-Drehmoment bei Pos. {', '.join(leer[:12])}{' …' if len(leer) > 12 else ''}")
    if not any(x.get("dichtungsart") for x in p.get("dichtungen") or []):
        f.append("Dichtungen")
    if not p.get("montage_abgeschlossen"):
        f.append("Montage abgeschlossen (Ja/Nein)")
    if not p.get("lecktest"):
        f.append("Lecktest")
    return f


def _vergleich(alt: dict, neu: dict) -> list[list]:
    """Änderungen als [Feld, alt, neu] – lesbar für den Verlauf."""
    aus = []
    for k in ["stutzen"] + KOPF_FELDER + ["schrauben_anzahl"]:
        a, b = alt.get(k), neu.get(k)
        a = a.strftime("%d.%m.%Y") if isinstance(a, date) else a
        b = b.strftime("%d.%m.%Y") if isinstance(b, date) else b
        if (a or "") != (b or ""):
            aus.append([FELD_NAMEN.get(k, k), a, b])
    for i in range(3):
        da, db = (alt.get("dichtungen") or [{}] * 3)[i] if i < len(alt.get("dichtungen") or []) else {}, neu["dichtungen"][i]
        for f in DICHTUNG_FELDER:
            if (da.get(f) or "") != (db.get(f) or ""):
                aus.append([f"Dichtung {i + 1} {FELD_NAMEN[f]}", da.get(f), db.get(f)])
    sa, sb = alt.get("schrauben") or [], neu.get("schrauben") or []
    for i in range(max(len(sa), len(sb))):
        za, zb = sa[i] if i < len(sa) else {}, sb[i] if i < len(sb) else {}
        for f in SCHRAUBEN_FELDER:
            if (za.get(f) or "") != (zb.get(f) or ""):
                aus.append([f"Schraube Pos. {i + 1} {FELD_NAMEN[f]}", za.get(f), zb.get(f)])
    if (alt.get("reihenfolge") or []) != (neu.get("reihenfolge") or []):
        aus.append(["Reihenfolge (Loch je Pos.)", ", ".join(map(str, alt.get("reihenfolge") or [])), ", ".join(map(str, neu["reihenfolge"]))])
    return aus


def _verlauf(con, pid: int, benutzer: str, art: str, grund: str | None = None, aenderungen: list | None = None) -> None:
    con.execute(insert(mt_verlauf).values(protokoll_id=pid, zeit=datetime.now().replace(microsecond=0), benutzer=benutzer, art=art,
                                          grund=grund, aenderungen=json.dumps(aenderungen, ensure_ascii=False, default=str) if aenderungen else None))


def speichern(con: Connection, pid: int | None, daten: dict, benutzer: str, abschliessen: bool = False,
              darf_korrigieren: bool = False, grund: str = "") -> int:
    """Neu anlegen oder ändern. Abgeschlossene Protokolle nur mit Korrekturrecht und Grund; jede Änderung kommt in den Verlauf."""
    jetzt = datetime.now()  # mit Mikrosekunden: „geaendert_am“ dient auch als Stand gegen gleichzeitiges Bearbeiten
    werte = {k: v for k, v in daten.items() if k in mt_protokolle.c and k not in ("id", "nummer", "status")}
    for k in ("dichtungen", "schrauben", "reihenfolge"):
        werte[k] = json.dumps(daten[k], ensure_ascii=False)
    if pid is None:
        nummer = neue_nummer(con, (daten.get("datum") or jetzt.date()).year)
        status = "abgeschlossen" if abschliessen else "entwurf"
        extra = dict(abgeschlossen_am=jetzt, abgeschlossen_von=benutzer) if abschliessen else {}
        pid = con.execute(insert(mt_protokolle).values(nummer=nummer, status=status, erstellt_am=jetzt, erstellt_von=benutzer,
                                                       geaendert_am=jetzt, geaendert_von=benutzer, **extra, **werte)).inserted_primary_key[0]
        _verlauf(con, pid, benutzer, "angelegt")
        if abschliessen:
            _verlauf(con, pid, benutzer, "abgeschlossen")
        return pid
    alt = laden(con, pid)
    if not alt:
        raise BuchungsFehler("Protokoll nicht gefunden.")
    aenderungen = _vergleich(alt, daten)
    if alt["status"] == "abgeschlossen":
        if not darf_korrigieren:
            raise BuchungsFehler("Das Protokoll ist abgeschlossen. Ändern dürfen nur Instandhaltungsingenieure und -manager.")
        if not aenderungen:
            return pid
        if not (grund or "").strip():
            raise BuchungsFehler("Bitte einen Grund für die Änderung des abgeschlossenen Protokolls angeben.")
        con.execute(update(mt_protokolle).where(mt_protokolle.c.id == pid).values(geaendert_am=jetzt, geaendert_von=benutzer, **werte))
        _verlauf(con, pid, benutzer, "korrigiert", grund.strip()[:1000], aenderungen)
        return pid
    extra = dict(status="abgeschlossen", abgeschlossen_am=jetzt, abgeschlossen_von=benutzer) if abschliessen else {}
    if aenderungen or abschliessen:
        con.execute(update(mt_protokolle).where(mt_protokolle.c.id == pid).values(geaendert_am=jetzt, geaendert_von=benutzer, **extra, **werte))
    if aenderungen:
        _verlauf(con, pid, benutzer, "gespeichert", None, aenderungen)
    if abschliessen:
        _verlauf(con, pid, benutzer, "abgeschlossen")
    return pid


def wieder_oeffnen(con: Connection, pid: int, benutzer: str, grund: str) -> None:
    if not (grund or "").strip():
        raise BuchungsFehler("Bitte einen Grund angeben.")
    con.execute(update(mt_protokolle).where(mt_protokolle.c.id == pid, mt_protokolle.c.status == "abgeschlossen")
                .values(status="entwurf", abgeschlossen_am=None, abgeschlossen_von=None, geaendert_am=datetime.now(),
                        geaendert_von=benutzer))
    _verlauf(con, pid, benutzer, "geoeffnet", grund.strip()[:1000])


# ------------------------------------------------------------------ Skizze
def skizze(n: int, folge: list[int] | None = None, groesse: float = 300.0) -> dict:
    """Geometrie des Flansches (gleiche Form wie die Vorlage): äußerer Ring, innere Öffnung, n Löcher gleichmäßig, Loch 1 oben,
    im Uhrzeigersinn. Liefert Mittelpunkt, Radien, Löcher (x, y, Loch-Nr., Pos.) und ob die Nummern außen stehen."""
    folge = folge or []
    pos_von = {loch: i + 1 for i, loch in enumerate(folge)}
    r_aussen = groesse * 0.45
    cx = cy = groesse / 2
    r_loch_kreis = r_aussen * 0.875
    n = max(0, min(int(n or 0), MAX_SCHRAUBEN))
    r_loch = min(r_aussen * 0.11, r_loch_kreis * math.sin(math.pi / n) * 0.55) if n else 0
    aussen = n > 24  # bei vielen Löchern Nummern außerhalb des Rings
    loecher = []
    for i in range(n):
        w = -math.pi / 2 + 2 * math.pi * i / n
        x, y = cx + r_loch_kreis * math.cos(w), cy + r_loch_kreis * math.sin(w)
        tx, ty = (cx + r_aussen * 1.09 * math.cos(w), cy + r_aussen * 1.09 * math.sin(w)) if aussen else (x, y)
        loecher.append({"x": round(x, 2), "y": round(y, 2), "tx": round(tx, 2), "ty": round(ty, 2), "loch": i + 1, "pos": pos_von.get(i + 1)})
    schrift = (min(r_loch * 1.15, groesse * 0.05) if not aussen else min(groesse * 0.032, r_aussen * 0.6 * math.pi / n * 1.6))
    return {"groesse": groesse, "cx": cx, "cy": cy, "r_aussen": r_aussen, "r_innen": r_aussen * 0.74, "r_loch": round(r_loch, 2),
            "loecher": loecher, "aussen": aussen, "schrift": round(max(schrift, 3.2), 2), "n": n}


def skizze_svg(n: int, folge: list[int] | None = None, breite: str = "100%") -> str:
    """Skizze als SVG (für Ansicht und Druck)."""
    g = skizze(n, folge)
    s = g["groesse"]
    teile = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s:g} {s:g}" width="{breite}" role="img" aria-label="Stutzenskizze mit {g["n"]} Schrauben">',
             f'<circle cx="{g["cx"]}" cy="{g["cy"]}" r="{g["r_aussen"]:.2f}" fill="#fff" stroke="#1B2A36" stroke-width="2.2"/>',
             f'<circle cx="{g["cx"]}" cy="{g["cy"]}" r="{g["r_innen"]:.2f}" fill="#F2F2F2" stroke="#1B2A36" stroke-width="0.9"/>']
    for h in g["loecher"]:
        teile.append(f'<circle cx="{h["x"]}" cy="{h["y"]}" r="{g["r_loch"]}" fill="{"#FDE7E7" if h["pos"] else "#fff"}" stroke="#1B2A36" stroke-width="1"/>')
        if h["pos"]:
            teile.append(f'<text x="{h["tx"]}" y="{h["ty"]}" font-family="Arial" font-weight="700" font-size="{g["schrift"]}" fill="#C00000" '
                         f'text-anchor="middle" dominant-baseline="central">{h["pos"]}</text>')
    teile.append("</svg>")
    return "".join(teile)


# ------------------------------------------------------------------ Excel (gleiches Blatt wie die Vorlage, ausgefüllt)
ROT, DUNKEL, GRAU, RAHMEN = "C00000", "1F2937", "E7E6E6", "7F7F7F"
BREITEN = {"A": 7.6, "B": 7.5, "C": 8.43, "D": 8.0, "E": 5.6, "F": 4.3, "G": 3.5, "H": 7.5, "I": 8.43, "J": 6.4, "K": 7.5, "L": 12.7,
           "M": 13.4, "N": 13.7, "O": 7.6, "P": 7.5, "Q": 3.7, "R": 4.6}
KREUZ = {True: "☒", False: "☐"}


def excel(p: dict, firmenname: str = "") -> bytes:
    """Montageprotokoll als Excel-Datei im Layout der Vorlage „Blanko Stutzenblatt“ (A4 hoch, eine Seite bis ca. 24 Schrauben).
    Die Skizze ist eine Zeichnung aus Formen (Kreise) mit genau so vielen Löchern wie Schrauben, nummeriert nach Reihenfolge;
    die Schraubentabelle hat genau so viele Zeilen wie Schrauben."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.page import PageMargins

    wb = Workbook()
    ws = wb.active
    ws.title = "Montageprotokoll"
    ws.sheet_view.showGridLines = False
    for c, w in BREITEN.items():
        ws.column_dimensions[c].width = w
    rot = PatternFill("solid", fgColor=ROT)
    grau = PatternFill("solid", fgColor=GRAU)
    weiss = PatternFill("solid", fgColor="FFFFFF")
    s = Side(style="thin", color=RAHMEN)
    rahmen = Border(left=s, right=s, top=s, bottom=s)
    mitte = Alignment(horizontal="center", vertical="center", wrap_text=True)
    links = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
    oben = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=1)

    def feld(bereich: str, wert=None, *, label=False, groesse=9, fett=False, farbe=DUNKEL, fill=None, ausr=None, rand=True):
        erste = bereich.split(":")[0]
        if ":" in bereich:
            ws.merge_cells(bereich)
        c = ws[erste]
        c.value = wert if wert not in ("", None) else None
        c.font = Font(name="Arial", size=8 if label else groesse, bold=label or fett, color=farbe)
        c.alignment = ausr or mitte
        fl = fill or (grau if label else weiss)
        for zeile in ws[bereich] if ":" in bereich else [[c]]:
            for z in zeile:
                z.fill = fl
                if rand:
                    z.border = rahmen
        return c

    hoehe = {}
    r = 1
    # Kopf
    feld("A1:L1", "MONTAGEPROTOKOLL – REAKTORSTUTZEN / DICHTUNGEN / SCHRAUBEN", fett=True, groesse=12, farbe="FFFFFF", fill=rot, rand=False)
    feld("M1:R1", (firmenname or "").upper(), fett=True, groesse=15, farbe="FFFFFF", fill=rot, rand=False,
         ausr=Alignment(horizontal="right", vertical="center", indent=1))
    hoehe[1] = 30
    hoehe[2] = 10
    datum = p["datum"].strftime("%d.%m.%Y") if isinstance(p.get("datum"), date) else (p.get("datum") or "")
    feld("A3:B3", "Anlage / Reaktor", label=True); feld("C3:E3", p.get("anlage"))
    feld("F3:G3", "Stutzen", label=True); feld("H3:K3", p.get("stutzen_bez") or p.get("stutzen"), fett=True)
    feld("L3:M3", "Datum", label=True); feld("N3:R3", datum)
    feld("A4:B4", "Monteur", label=True); feld("C4:E4", p.get("monteur"))
    feld("F4:G4", "Prüfer", label=True); feld("H4:K4", p.get("pruefer"))
    feld("L4:M4", "Arbeitsauftrag", label=True); feld("N4:R4", p.get("arbeitsauftrag"))
    feld("A5:B5", "Reinigung", label=True); feld("C5:H5", p.get("reinigung"))
    feld("I5:K5", "Schmiermittel", label=True); feld("L5:R5", p.get("schmiermittel"))
    hoehe.update({3: 20, 4: 23, 5: 26.4, 6: 12})
    # Skizze + Dichtungen
    feld("A7:G7", "STUTZENSKIZZE / SCHRAUBENPOSITIONEN", fett=True, farbe="FFFFFF", fill=rot, rand=False)
    feld("H7:R7", "DICHTUNGEN", fett=True, farbe="FFFFFF", fill=rot, rand=False)
    hoehe[7] = 19.2
    ws.merge_cells("A8:G13")
    for zeile in ws["A8:G13"]:
        for z in zeile:
            z.border = rahmen
            z.fill = weiss
    for bereich, text in [("H8", "Pos."), ("I8", "Einbauort"), ("J8:L8", "Dichtungsart"), ("M8:N8", "Artikel-Nr."), ("O8", "Nenn D.\n[mm]"),
                          ("P8", "Ist-Dicke\n[mm]"), ("Q8", "Alt"), ("R8", "Neu")]:
        feld(bereich, text, label=True).font = Font(name="Arial", size=7, bold=True, color=DUNKEL)
    hoehe[8] = 22.2
    for i, d in enumerate(p.get("dichtungen") or leere_dichtungen()):
        z = 9 + i
        feld(f"H{z}", f"Dichtung {i + 1}", label=True).font = Font(name="Arial", size=7, bold=True, color=DUNKEL)
        feld(f"I{z}", d.get("einbauort"), groesse=7)
        feld(f"J{z}:L{z}", d.get("dichtungsart"), groesse=8)
        feld(f"M{z}:N{z}", d.get("artikel_nr"), groesse=7)
        feld(f"O{z}", parse_num(d.get("nenndicke")) if d.get("nenndicke") else None, groesse=8).number_format = "0.00"
        feld(f"P{z}", parse_num(d.get("ist_dicke")) if d.get("ist_dicke") else None, groesse=8).number_format = "0.00"
        feld(f"Q{z}", KREUZ[d.get("alt_neu") == "alt"], groesse=11)
        feld(f"R{z}", KREUZ[d.get("alt_neu") == "neu"], groesse=11)
        hoehe[z] = 27
    feld("H12:I13", "Bemerkung\nDichtungen", label=True)
    feld("J12:R13", p.get("bemerkung_dichtungen"), groesse=8, ausr=oben)
    hoehe[12], hoehe[13] = 18, 92
    n = p.get("schrauben_anzahl") or 0
    c = ws["A14"]
    ws.merge_cells("A14:R14")
    c.value = ("Hinweis: Die tatsächlich vorhandenen Schraubenpositionen sind entsprechend der Anzahl zu markieren und fortlaufend "
               "in der Reihenfolge des erfolgten Anziehens zu nummerieren. „#“ = gleicher Wert wie in der Zeile darüber.")
    c.font = Font(name="Arial", size=8, color=ROT)
    c.alignment = mitte
    hoehe[14] = 26
    feld("A15:R15", f"SCHRAUBEN – POSITIONEN 1 BIS {n}" if n else "SCHRAUBEN", fett=True, farbe="FFFFFF", fill=rot, rand=False)
    hoehe[15] = 19.2
    for bereich, text in [("A16", "Pos."), ("B16:D16", "Kennzeichnung\nz. B. RO-1-65 Nm"), ("E16:F16", "Typ / Norm"), ("G16:H16", "Größe / Gewinde"),
                          ("I16", "Länge-Soll\n[mm]"), ("J16", "Länge-Ist\n[mm]"), ("K16:L16", "Werkstoff /\nKlasse"), ("M16", "Soll\n[Nm]"),
                          ("N16", "Ist\n[Nm]"), ("O16", "Alt"), ("P16", "Neu"), ("Q16:R16", "Bemerkung")]:
        feld(bereich, text, label=True).font = Font(name="Arial", size=7, bold=True, color=DUNKEL)
    hoehe[16] = 25.2
    zeilen = ditto_anzeige(p.get("schrauben") or [])
    for i, zl in enumerate(zeilen):
        z = 17 + i
        roh = (p.get("schrauben") or [])[i]

        def zahl(v):
            return v if v == DITTO else (parse_num(v) if parse_num(v) is not None else v) or None
        feld(f"A{z}", i + 1, fett=True, groesse=8, ausr=Alignment(horizontal="right", vertical="center", indent=1))
        feld(f"B{z}:D{z}", kennzeichnung(p.get("stutzen"), i + 1, roh.get("ist_nm")), groesse=8)
        feld(f"E{z}:F{z}", zl.get("typ"), groesse=8)
        feld(f"G{z}:H{z}", zl.get("groesse"), groesse=8)
        feld(f"I{z}", zahl(zl.get("laenge_soll")), groesse=8)
        feld(f"J{z}", zahl(zl.get("laenge_ist")), groesse=8)
        feld(f"K{z}:L{z}", zl.get("werkstoff"), groesse=8)
        feld(f"M{z}", zahl(zl.get("soll_nm")), groesse=8)
        feld(f"N{z}", zahl(zl.get("ist_nm")), groesse=9, fett=True)
        feld(f"O{z}", KREUZ[roh.get("alt_neu") == "alt"], groesse=10)
        feld(f"P{z}", KREUZ[roh.get("alt_neu") == "neu"], groesse=10)
        feld(f"Q{z}:R{z}", roh.get("bemerkung"), groesse=7)
        hoehe[z] = 18.6
    r = 17 + len(zeilen)
    hoehe[r] = 14
    r += 1
    feld(f"A{r}:C{r + 1}", "ALLGEMEINE\nBEMERKUNGEN", label=True)
    feld(f"D{r}:R{r + 1}", p.get("bemerkungen"), groesse=8, ausr=oben)
    hoehe[r], hoehe[r + 1] = 18.6, 70
    r += 2
    hoehe[r] = 14
    r += 1
    ma = p.get("montage_abgeschlossen")
    lt = p.get("lecktest")
    feld(f"A{r}:C{r}", "Montage abgeschlossen", label=True)
    feld(f"D{r}:F{r}", f"{KREUZ[ma == 'ja']} Ja     {KREUZ[ma == 'nein']} Nein")
    feld(f"G{r}:H{r}", "Lecktest", label=True)
    feld(f"I{r}:M{r}", f"{KREUZ[lt == 'bestanden']} bestanden   {KREUZ[lt == 'offen']} offen   {KREUZ[lt == 'nb']} n. b.", groesse=8)
    feld(f"N{r}:O{r}", "Datum / Uhrzeit", label=True)
    feld(f"P{r}:R{r}", p.get("abschluss_zeit"), groesse=8)
    hoehe[r] = 38.4
    r += 1
    feld(f"A{r}:D{r}", "Unterschrift Monteur:", label=True)
    feld(f"E{r}:H{r}", None)
    feld(f"I{r}:M{r}", "Unterschrift Prüfer:", label=True)
    feld(f"N{r}:R{r}", None)
    hoehe[r] = 38.4
    r += 1
    c = ws[f"A{r}"]
    ws.merge_cells(f"A{r}:R{r}")
    c.value = f"{p.get('nummer') or ''} · Status: {STATUS.get(p.get('status'), p.get('status') or '')} · gedruckt {datetime.now():%d.%m.%Y %H:%M}"
    c.font = Font(name="Arial", size=7, color="595959")
    c.alignment = Alignment(horizontal="right", vertical="center")
    hoehe[r] = 14
    for zeile, h in hoehe.items():
        ws.row_dimensions[zeile].height = h
    ws.print_area = f"A1:R{r}"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if n <= 24 else 0
    ws.print_options.horizontalCentered = True
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.3, bottom=0.3, header=0, footer=0)
    ws.print_title_rows = "15:16" if n > 24 else None
    buf = io.BytesIO()
    wb.save(buf)
    return _skizze_einfuegen(buf.getvalue(), n, p.get("reihenfolge") or [], hoehe)


EMU_PT = 12700


def _spalten_emu() -> list[int]:
    # Spaltenbreite (Zeichen) -> Pixel wie Excel bei Calibri 11 (7 px je Zeichen + 5 px Rand), 1 px = 9525 EMU
    return [int((BREITEN[c] * 7 + 5)) * 9525 for c in "ABCDEFGHIJKLMNOPQR"]


def _skizze_einfuegen(xlsx: bytes, n: int, folge: list[int], hoehe: dict) -> bytes:
    """Zeichnung (Gruppe aus Kreisen) in A8:G13 einsetzen: direkt im Dateiformat, ohne Bildbibliothek."""
    if not n:
        return xlsx
    spalten = _spalten_emu()
    bereich_b = sum(spalten[:7])
    zeilen_y = [0]
    for z in range(1, 14):
        zeilen_y.append(zeilen_y[-1] + int(hoehe.get(z, 15) * EMU_PT))
    oben, bereich_h = zeilen_y[7], zeilen_y[13] - zeilen_y[7]
    rand = 6 * 9525
    seite = min(bereich_b, bereich_h) - 2 * rand
    x0 = (bereich_b - seite) // 2
    y0 = oben + (bereich_h - seite) // 2
    # Ankerzelle und Versatz (Versatz innerhalb der Zelle halten)
    col, rest = 0, x0
    while col < 6 and rest >= spalten[col]:
        rest -= spalten[col]
        col += 1
    row = 0
    while row < 12 and y0 >= zeilen_y[row + 1]:
        row += 1
    roff = y0 - zeilen_y[row]
    g = skizze(n, folge, groesse=float(seite))
    ids = iter(range(3, 10_000))

    def kreis(name, x, y, r, fill, linie_pt, text=None, schrift_pt=None, ohne_rand=False):
        d = int(round(2 * r))
        sp = (f'<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="{next(ids)}" name="{escape(name)}"/><xdr:cNvSpPr/></xdr:nvSpPr>'
              f'<xdr:spPr><a:xfrm><a:off x="{int(round(x - r))}" y="{int(round(y - r))}"/><a:ext cx="{d}" cy="{d}"/></a:xfrm>'
              f'<a:prstGeom prst="{"rect" if ohne_rand else "ellipse"}"><a:avLst/></a:prstGeom>'
              + ('<a:noFill/><a:ln><a:noFill/></a:ln>' if ohne_rand else
                 f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln w="{int(linie_pt * EMU_PT)}"><a:solidFill><a:srgbClr val="1B2A36"/></a:solidFill></a:ln>')
              + '</xdr:spPr>')
        if text is not None:
            sp += (f'<xdr:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr" anchorCtr="1"/><a:lstStyle/>'
                   f'<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="de-DE" sz="{int(schrift_pt * 100)}" b="1"><a:solidFill><a:srgbClr val="C00000"/></a:solidFill>'
                   f'<a:latin typeface="Arial"/></a:rPr><a:t>{escape(str(text))}</a:t></a:r></a:p></xdr:txBody>')
        return sp + "</xdr:sp>"

    emu_je_einheit = 1.0
    pt = lambda emu: emu / EMU_PT  # noqa: E731
    formen = [kreis("Flansch", g["cx"], g["cy"], g["r_aussen"], "FFFFFF", 2.0),
              kreis("Öffnung", g["cx"], g["cy"], g["r_innen"], "F2F2F2", 0.75)]
    schrift_pt = max(5.0, min(11.0, pt(g["schrift"] * emu_je_einheit) * 0.95))
    for h in g["loecher"]:
        innen = h["pos"] and not g["aussen"]
        formen.append(kreis(f"Loch {h['loch']}", h["x"], h["y"], g["r_loch"], "FDE7E7" if h["pos"] else "FFFFFF", 0.75,
                            h["pos"] if innen else None, schrift_pt))
        if h["pos"] and g["aussen"]:
            formen.append(kreis(f"Nr {h['loch']}", h["tx"], h["ty"], g["r_loch"] * 1.6, None, 0, h["pos"], schrift_pt, ohne_rand=True))
    drawing = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
               'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
               f'<xdr:oneCellAnchor><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>{rest}</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>{roff}</xdr:rowOff></xdr:from>'
               f'<xdr:ext cx="{seite}" cy="{seite}"/>'
               f'<xdr:grpSp><xdr:nvGrpSpPr><xdr:cNvPr id="2" name="Stutzenskizze"/><xdr:cNvGrpSpPr/></xdr:nvGrpSpPr>'
               f'<xdr:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{seite}" cy="{seite}"/><a:chOff x="0" y="0"/><a:chExt cx="{seite}" cy="{seite}"/></a:xfrm></xdr:grpSpPr>'
               + "".join(formen) + '</xdr:grpSp><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>')
    rid = "rIdSkizze"
    rel = (f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
           'Target="../drawings/drawing_skizze.xml"/>')
    ein, aus = zipfile.ZipFile(io.BytesIO(xlsx)), io.BytesIO()
    with zipfile.ZipFile(aus, "w", zipfile.ZIP_DEFLATED) as z:
        namen = ein.namelist()
        for name in namen:
            daten = ein.read(name)
            if name == "xl/worksheets/sheet1.xml":
                t = daten.decode("utf-8")
                tag = f'<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rid}"/>'
                m = re.search(r"<(legacyDrawing|legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b", t)
                t = t[:m.start()] + tag + t[m.start():] if m else t.replace("</worksheet>", tag + "</worksheet>")
                daten = t.encode("utf-8")
            elif name == "xl/worksheets/_rels/sheet1.xml.rels":
                daten = daten.decode("utf-8").replace("</Relationships>", rel + "</Relationships>").encode("utf-8")
            elif name == "[Content_Types].xml":
                daten = daten.decode("utf-8").replace("</Types>", '<Override PartName="/xl/drawings/drawing_skizze.xml" '
                                                      'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>').encode("utf-8")
            z.writestr(name, daten)
        if "xl/worksheets/_rels/sheet1.xml.rels" not in namen:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rel + "</Relationships>")
        z.writestr("xl/drawings/drawing_skizze.xml", drawing)
    return aus.getvalue()
