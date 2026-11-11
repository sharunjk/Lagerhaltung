"""Schichtbuch (ab 2.8.0): Schichtteams, Schichtzeiten, Schichten, Meldungen und Übergaben.

Ablauf je Schicht:
* Schichtbeginn – vorherige Einträge und offene Übergaben lesen, Übergaben übernehmen.
* Während der Schicht – besondere Ereignisse sofort als Meldung erfassen, nach Maßnahmen ergänzen, Status ändern,
  bei Bedarf den Wartungsauftrag (Work Order) prüfen.
* Schichtende – offene Meldungen prüfen, relevante Punkte an die nächste Schicht übergeben, Schicht beenden.

Eine Schicht gehört zu einer Schichtzeit (z. B. Tag/Nacht) und einem Datum (Tag des Schichtbeginns). Welches Team
Dienst hat, legt der Schichtbeginn fest (vorbelegt: das Team des Benutzers).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, func, insert, or_, select, true, update
from sqlalchemy.engine import Connection

from ..db import ih_auftraege, ih_plaetze, sb_meldungen, sb_mitglieder, sb_schichten, sb_teams, sb_verlauf, sb_zeiten, settings

STATUS = {"offen": "Offen", "in_arbeit": "In Bearbeitung", "erledigt": "Erledigt"}
PRIO = {"hoch": "Hoch", "mittel": "Mittel", "niedrig": "Niedrig"}
STANDARD_TEAMS = [("Grün", "#2E9E5B"), ("Blau", "#2F6FD6"), ("Gelb", "#D4A600"), ("Rot", "#D64545")]
STANDARD_ZEITEN = [("Tag", "06:00", "18:00"), ("Nacht", "18:00", "06:00")]
STANDARD_TYPEN = ["Störung", "Prozessabweichung", "Sicherheit / Beinahe-Unfall", "Umwelt", "Qualität", "Instandhaltung / Wartung",
                  "Betriebszustand / Umstellung", "Information"]
SETTING_TYPEN = "schichtbuch.ereignistypen"
FARBE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class SchichtFehler(Exception):
    pass


# ------------------------------------------------------------------ Grunddaten
def sicherstellen(con: Connection) -> None:
    """Beim ersten Aufruf: vier Teams (Grün, Blau, Gelb, Rot) und Tag/Nacht anlegen – danach frei änderbar."""
    if not con.execute(select(func.count()).select_from(sb_teams)).scalar():
        for i, (name, farbe) in enumerate(STANDARD_TEAMS):
            con.execute(insert(sb_teams).values(name=name, farbe=farbe, reihenfolge=i, aktiv=True))
    if not con.execute(select(func.count()).select_from(sb_zeiten)).scalar():
        for i, (name, b, e) in enumerate(STANDARD_ZEITEN):
            con.execute(insert(sb_zeiten).values(name=name, beginn=b, ende=e, reihenfolge=i, aktiv=True))


def grunddaten_vorhanden(con: Connection) -> bool:
    return bool(con.execute(select(func.count()).select_from(sb_teams)).scalar() and con.execute(select(func.count()).select_from(sb_zeiten)).scalar())


def teams(con: Connection, alle: bool = False) -> list[dict]:
    q = select(sb_teams).order_by(sb_teams.c.reihenfolge, sb_teams.c.id)
    if not alle:
        q = q.where(sb_teams.c.aktiv)
    return [dict(r) for r in con.execute(q).mappings()]


def zeiten(con: Connection, alle: bool = False) -> list[dict]:
    q = select(sb_zeiten).order_by(sb_zeiten.c.reihenfolge, sb_zeiten.c.id)
    if not alle:
        q = q.where(sb_zeiten.c.aktiv)
    return [dict(r) for r in con.execute(q).mappings()]


def ereignistypen(con: Connection) -> list[str]:
    wert = con.execute(select(settings.c.wert).where(settings.c.schluessel == SETTING_TYPEN)).scalar()
    liste = [z.strip() for z in (wert or "").splitlines() if z.strip()]
    return liste or list(STANDARD_TYPEN)


def typen_speichern(con: Connection, liste: list[str]) -> None:
    text = "\n".join(dict.fromkeys(z.strip()[:60] for z in liste if z.strip()))
    if con.execute(select(settings.c.schluessel).where(settings.c.schluessel == SETTING_TYPEN)).scalar():
        con.execute(update(settings).where(settings.c.schluessel == SETTING_TYPEN).values(wert=text))
    else:
        con.execute(insert(settings).values(schluessel=SETTING_TYPEN, wert=text))


def uhrzeit(text: str) -> str:
    """„6:00“, „06.00“, „0600“ → „06:00“."""
    t = (text or "").strip().replace(".", ":")
    if re.fullmatch(r"\d{3,4}", t):
        t = t[:-2] + ":" + t[-2:]
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise SchichtFehler(f"Uhrzeit „{text}“: bitte als HH:MM angeben, z. B. 06:00.")
    return f"{int(m[1]):02d}:{m[2]}"


def team_von(con: Connection, user_id: int | None) -> dict | None:
    if not user_id:
        return None
    r = con.execute(select(sb_teams).select_from(sb_mitglieder.join(sb_teams, sb_teams.c.id == sb_mitglieder.c.team_id))
                    .where(sb_mitglieder.c.user_id == user_id)).mappings().first()
    return dict(r) if r else None


# ------------------------------------------------------------------ Schichtzeiten und Schichten
def fenster(datum: date, z: dict) -> tuple[datetime, datetime]:
    """Beginn und Ende einer Schicht; ein Ende vor/gleich dem Beginn liegt am Folgetag (Nachtschicht)."""
    b = datetime.combine(datum, time.fromisoformat(z["beginn"]))
    e = datetime.combine(datum, time.fromisoformat(z["ende"]))
    if e <= b:
        e += timedelta(days=1)
    return b, e


def slot(con: Connection, jetzt: datetime | None = None) -> tuple[date, dict]:
    """Welche Schicht ist gerade (Datum des Schichtbeginns, Schichtzeit)?"""
    jetzt = jetzt or datetime.now()
    zs = zeiten(con)
    if not zs:
        raise SchichtFehler("Es ist keine Schichtzeit eingerichtet (Schichtbuch → Einrichten).")
    for d in (jetzt.date(), jetzt.date() - timedelta(days=1)):
        for z in zs:
            b, e = fenster(d, z)
            if b <= jetzt < e:
                return d, z
    # Lücke zwischen zwei Schichten: die zuletzt begonnene
    kandidaten = [(fenster(d, z)[0], d, z) for d in (jetzt.date(), jetzt.date() - timedelta(days=1)) for z in zs if fenster(d, z)[0] <= jetzt]
    _, d, z = max(kandidaten, key=lambda x: x[0])
    return d, z


def bezeichnung(datum: date, z: dict | None) -> str:
    if not z:
        return f"{datum:%d.%m.%Y}"
    b, e = fenster(datum, z)
    tage = f"{datum:%d.%m.}–{e:%d.%m.%Y}" if e.date() != b.date() else f"{datum:%d.%m.%Y}"
    return f"{z['name']} {tage}"


def _schicht_select():
    return (select(sb_schichten, sb_zeiten.c.name.label("zeit"), sb_zeiten.c.beginn, sb_zeiten.c.ende, sb_teams.c.name.label("team"),
                   sb_teams.c.farbe.label("team_farbe"))
            .select_from(sb_schichten.join(sb_zeiten, sb_zeiten.c.id == sb_schichten.c.zeit_id)
                         .outerjoin(sb_teams, sb_teams.c.id == sb_schichten.c.team_id)))


def _mit_text(r) -> dict:
    s = dict(r)
    z = {"name": s["zeit"], "beginn": s["beginn"], "ende": s["ende"]}
    s["text"] = bezeichnung(s["datum"], z)
    s["start"], s["schluss"] = fenster(s["datum"], z)
    return s


def schicht(con: Connection, schicht_id: int | None = None, datum: date | None = None, zeit_id: int | None = None) -> dict | None:
    q = _schicht_select()
    q = q.where(sb_schichten.c.id == schicht_id) if schicht_id else q.where(sb_schichten.c.datum == datum, sb_schichten.c.zeit_id == zeit_id)
    r = con.execute(q).mappings().first()
    return _mit_text(r) if r else None


def schicht_holen(con: Connection, datum: date, zeit_id: int, team_id: int | None) -> int:
    """Schicht zu Datum und Schichtzeit – bei Bedarf anlegen (Team = Team des ersten Eintrags)."""
    sid = con.execute(select(sb_schichten.c.id).where(sb_schichten.c.datum == datum, sb_schichten.c.zeit_id == zeit_id)).scalar()
    if sid:
        if team_id and not con.execute(select(sb_schichten.c.team_id).where(sb_schichten.c.id == sid)).scalar():
            con.execute(update(sb_schichten).where(sb_schichten.c.id == sid).values(team_id=team_id))
        return sid
    return con.execute(insert(sb_schichten).values(datum=datum, zeit_id=zeit_id, team_id=team_id)).inserted_primary_key[0]


def aktuelle_schicht_id(con: Connection, user: dict, jetzt: datetime | None = None) -> int:
    d, z = slot(con, jetzt)
    t = team_von(con, user.get("id"))
    return schicht_holen(con, d, z["id"], t["id"] if t else None)


def beginnen(con: Connection, datum: date, zeit_id: int, team_id: int | None, schichtfuehrer: str, benutzer: str) -> int:
    sid = schicht_holen(con, datum, zeit_id, team_id)
    s = con.execute(select(sb_schichten).where(sb_schichten.c.id == sid)).mappings().first()
    werte = {"team_id": team_id or s["team_id"], "schichtfuehrer": (schichtfuehrer or "").strip()[:200] or benutzer}
    if not s["begonnen_am"]:
        werte.update(begonnen_am=datetime.now().replace(microsecond=0), begonnen_von=benutzer)
    con.execute(update(sb_schichten).where(sb_schichten.c.id == sid).values(**werte))
    return sid


def nicht_beendet(con: Connection, ausser: int | None = None) -> list[dict]:
    """Begonnene, aber nicht beendete Schichten (z. B. Übergabe vergessen) – älteste zuerst."""
    q = _schicht_select().where(sb_schichten.c.begonnen_am.isnot(None), sb_schichten.c.beendet_am.is_(None))
    if ausser:
        q = q.where(sb_schichten.c.id != ausser)
    return sorted((_mit_text(r) for r in con.execute(q).mappings()), key=lambda s: s["start"])


def letzte_schichten(con: Connection, vor: datetime, anzahl: int = 6, team_id: int | None = None) -> list[dict]:
    """Schichten, die vor ``vor`` begonnen haben, neueste zuerst – nur solche mit Beginn oder Einträgen."""
    q = _schicht_select().where(sb_schichten.c.datum <= vor.date(), sb_schichten.c.datum >= vor.date() - timedelta(days=60))
    if team_id:
        q = q.where(sb_schichten.c.team_id == team_id)
    liste = [_mit_text(r) for r in con.execute(q.order_by(sb_schichten.c.datum.desc()).limit(200)).mappings()]
    liste = sorted((s for s in liste if s["start"] < vor), key=lambda s: s["start"], reverse=True)
    if not liste:
        return []
    ids = [s["id"] for s in liste]
    eintraege: dict[int, list] = {}
    for m in con.execute(select(sb_meldungen.c.id, sb_meldungen.c.schicht_id, sb_meldungen.c.titel, sb_meldungen.c.status,
                                sb_meldungen.c.prioritaet, sb_meldungen.c.sicherheitsrelevant, sb_meldungen.c.stillstand)
                         .where(sb_meldungen.c.schicht_id.in_(ids)).order_by(sb_meldungen.c.id)).mappings():
        eintraege.setdefault(m["schicht_id"], []).append(dict(m))
    out = []
    for s in liste:
        s["meldungen"] = eintraege.get(s["id"], [])
        if s["begonnen_am"] or s["meldungen"] or s["beendet_am"]:
            out.append(s)
        if len(out) >= anzahl:
            break
    return out


def beenden(con: Connection, sid: int, benutzer: str, uebergaben: dict[int, str], notiz: str) -> int:
    """Schicht beenden: ausgewählte Meldungen an die nächste Schicht übergeben (mit Hinweis), Übergabenotiz speichern."""
    s = con.execute(select(sb_schichten).where(sb_schichten.c.id == sid)).mappings().first()
    if not s:
        raise SchichtFehler("Schicht nicht gefunden.")
    if s["beendet_am"]:
        raise SchichtFehler("Diese Schicht ist schon beendet.")
    jetzt = datetime.now().replace(microsecond=0)
    n = 0
    for mid, text in uebergaben.items():
        m = con.execute(select(sb_meldungen.c.id).where(sb_meldungen.c.id == mid)).scalar()
        if not m:
            continue
        con.execute(update(sb_meldungen).where(sb_meldungen.c.id == mid).values(
            uebergabe=True, uebergabe_text=(text or "").strip() or None, uebergeben_schicht_id=sid,
            uebernommen_am=None, uebernommen_von=None, uebernommen_schicht_id=None))
        _verlauf(con, mid, sid, benutzer, "uebergabe", (text or "").strip() or None)
        n += 1
    con.execute(update(sb_schichten).where(sb_schichten.c.id == sid).values(
        beendet_am=jetzt, beendet_von=benutzer, uebergabe_notiz=(notiz or "").strip() or None,
        begonnen_am=s["begonnen_am"] or jetzt, begonnen_von=s["begonnen_von"] or benutzer))
    return n


# ------------------------------------------------------------------ Meldungen
def _verlauf(con, mid, sid, benutzer, art, text=None, status=None):
    con.execute(insert(sb_verlauf).values(meldung_id=mid, schicht_id=sid, zeit=datetime.now().replace(microsecond=0), benutzer=benutzer,
                                          art=art, text=text, status=status))


def asset_aufloesen(con: Connection, text: str) -> tuple[int | None, str | None, str | None]:
    """Tag-Nr. (auch „Tag-Nr. – Bezeichnung“ aus der Auswahlliste) → (Anlagen-ID, Tag-Nr., Functional Location = übergeordnete Ebene)."""
    from .asset_import import schluessel
    code = " ".join((text or "").split(" – ")[0].split())
    if not code:
        return None, None, None
    r = con.execute(select(ih_plaetze.c.id, ih_plaetze.c.code, ih_plaetze.c.eltern_id).where(ih_plaetze.c.schluessel == schluessel(code))).first()
    if not r:
        return None, code[:120], None
    fl = None
    if r.eltern_id:
        e = con.execute(select(ih_plaetze.c.code, ih_plaetze.c.bezeichnung).where(ih_plaetze.c.id == r.eltern_id)).first()
        if e:
            fl = e.code + (f" {e.bezeichnung}" if e.bezeichnung and not e.bezeichnung.endswith(e.code) else "")
    return r.id, r.code, fl


def work_order_aufloesen(con: Connection, text: str) -> int | None:
    """„A-00012“, „A12“ oder „12“ → Instandhaltungsauftrag, wenn es ihn gibt (sonst bleibt die Nummer nur als Text)."""
    m = re.fullmatch(r"\s*(?:A\s*-?\s*)?0*(\d{1,7})\s*", text or "", re.IGNORECASE)
    if not m:
        return None
    return con.execute(select(ih_auftraege.c.id).where(ih_auftraege.c.id == int(m[1]))).scalar()


FELDER = ("titel", "ereignistyp", "beschreibung", "massnahme", "prioritaet", "asset", "functional_location", "work_order",
          "sicherheitsrelevant", "stillstand", "stillstand_h")


def werte_aus_formular(con: Connection, f) -> tuple[dict, list[str]]:
    fehler = []
    w = {k: (f.get(k) or "").strip() or None for k in ("titel", "ereignistyp", "beschreibung", "massnahme", "functional_location", "work_order")}
    if not w["titel"]:
        fehler.append("Bitte einen Titel angeben (kurz: was ist passiert?).")
    w["titel"] = (w["titel"] or "")[:200]
    w["prioritaet"] = f.get("prioritaet") if f.get("prioritaet") in PRIO else "mittel"
    w["sicherheitsrelevant"] = f.get("sicherheitsrelevant") == "on"
    w["stillstand"] = f.get("stillstand") == "on"
    h = (f.get("stillstand_h") or "").strip().replace(",", ".")
    try:
        w["stillstand_h"] = float(h) if h else None
        if w["stillstand_h"] is not None and not (0 <= w["stillstand_h"] <= 10000):
            raise ValueError
    except ValueError:
        fehler.append("Stillstandsdauer: Stunden als Zahl, z. B. 1,5.")
        w["stillstand_h"] = None
    if w["stillstand_h"] and not w["stillstand"]:
        w["stillstand"] = True
    pid, code, fl = asset_aufloesen(con, f.get("asset") or "")
    w["platz_id"], w["asset"] = pid, code
    if fl and not w["functional_location"]:
        w["functional_location"] = fl
    if w["work_order"]:
        w["work_order"] = w["work_order"][:60]
    w["auftrag_id"] = work_order_aufloesen(con, w["work_order"] or "")
    return w, fehler


def anlegen(con: Connection, w: dict, status: str, benutzer: str, sid: int) -> int:
    jetzt = datetime.now().replace(microsecond=0)
    status = status if status in STATUS else "offen"
    werte = {**w, "status": status, "schicht_id": sid, "erstellt_am": jetzt, "erstellt_von": benutzer}
    if status == "erledigt":
        werte.update(erledigt_am=jetzt, erledigt_von=benutzer, erledigt_schicht_id=sid)
    mid = con.execute(insert(sb_meldungen).values(**werte)).inserted_primary_key[0]
    _verlauf(con, mid, sid, benutzer, "angelegt", None, status)
    return mid


def aendern(con: Connection, mid: int, w: dict, benutzer: str, sid: int) -> list[str]:
    alt = con.execute(select(sb_meldungen).where(sb_meldungen.c.id == mid)).mappings().first()
    geaendert = [k for k, v in w.items() if alt[k] != v and not (alt[k] in (None, "") and v in (None, ""))]
    if geaendert:
        con.execute(update(sb_meldungen).where(sb_meldungen.c.id == mid).values(geaendert_am=datetime.now().replace(microsecond=0),
                                                                                 geaendert_von=benutzer, **w))
        namen = {"titel": "Titel", "ereignistyp": "Ereignistyp", "beschreibung": "Beschreibung", "massnahme": "Maßnahme", "prioritaet": "Priorität",
                 "asset": "Asset", "functional_location": "Functional Location", "work_order": "Work Order", "sicherheitsrelevant": "Sicherheitsrelevant",
                 "stillstand": "Stillstand", "stillstand_h": "Stillstandsdauer", "platz_id": None, "auftrag_id": None}
        _verlauf(con, mid, sid, benutzer, "geaendert", "Geändert: " + ", ".join(n for k in geaendert if (n := namen.get(k))))
    return geaendert


def ergaenzen(con: Connection, mid: int, benutzer: str, sid: int, text: str, status: str | None) -> None:
    alt = con.execute(select(sb_meldungen.c.status).where(sb_meldungen.c.id == mid)).scalar()
    if alt is None:
        raise SchichtFehler("Meldung nicht gefunden.")
    text = (text or "").strip()
    neu = status if status in STATUS and status != alt else None
    if not text and not neu:
        raise SchichtFehler("Bitte eine Ergänzung schreiben oder den Status ändern.")
    jetzt = datetime.now().replace(microsecond=0)
    werte = {"geaendert_am": jetzt, "geaendert_von": benutzer}
    if neu:
        werte["status"] = neu
        if neu == "erledigt":
            werte.update(erledigt_am=jetzt, erledigt_von=benutzer, erledigt_schicht_id=sid)
        elif alt == "erledigt":
            werte.update(erledigt_am=None, erledigt_von=None, erledigt_schicht_id=None)
    con.execute(update(sb_meldungen).where(sb_meldungen.c.id == mid).values(**werte))
    _verlauf(con, mid, sid, benutzer, "status" if neu else "ergaenzung", text or None, neu)


def uebernehmen(con: Connection, mid: int, benutzer: str, sid: int, kommentar: str = "") -> bool:
    n = con.execute(update(sb_meldungen).where(sb_meldungen.c.id == mid, sb_meldungen.c.uebergabe, sb_meldungen.c.uebernommen_am.is_(None))
                    .values(uebernommen_am=datetime.now().replace(microsecond=0), uebernommen_von=benutzer, uebernommen_schicht_id=sid)).rowcount
    if n:
        _verlauf(con, mid, sid, benutzer, "uebernahme", (kommentar or "").strip() or None)
    return bool(n)


def _meldung_select():
    s, z, t = sb_schichten, sb_zeiten, sb_teams
    return (select(sb_meldungen, s.c.datum.label("schicht_datum"), z.c.name.label("schicht_zeit"), z.c.beginn.label("schicht_beginn"),
                   z.c.ende.label("schicht_ende"), t.c.name.label("team"), t.c.farbe.label("team_farbe"), s.c.schichtfuehrer,
                   ih_auftraege.c.status.label("auftrag_status"), ih_auftraege.c.titel.label("auftrag_titel"))
            .select_from(sb_meldungen.outerjoin(s, s.c.id == sb_meldungen.c.schicht_id).outerjoin(z, z.c.id == s.c.zeit_id)
                         .outerjoin(t, t.c.id == s.c.team_id).outerjoin(ih_auftraege, ih_auftraege.c.id == sb_meldungen.c.auftrag_id)))


def _m(r) -> dict:
    m = dict(r)
    m["schicht_text"] = bezeichnung(m["schicht_datum"], {"name": m["schicht_zeit"], "beginn": m["schicht_beginn"], "ende": m["schicht_ende"]}) \
        if m.get("schicht_datum") and m.get("schicht_zeit") else ""
    return m


def meldung(con: Connection, mid: int) -> dict | None:
    r = con.execute(_meldung_select().where(sb_meldungen.c.id == mid)).mappings().first()
    return _m(r) if r else None


_PRIO_SORT = {"hoch": 0, "mittel": 1, "niedrig": 2}


def _sortiert(liste: list[dict]) -> list[dict]:
    return sorted(liste, key=lambda m: (not m["sicherheitsrelevant"], not (m["stillstand"] and m["status"] != "erledigt"),
                                        _PRIO_SORT.get(m["prioritaet"], 1), -m["id"]))


def offene(con: Connection) -> list[dict]:
    return _sortiert([_m(r) for r in con.execute(_meldung_select().where(sb_meldungen.c.status != "erledigt")).mappings()])


def offene_uebergaben(con: Connection) -> list[dict]:
    rows = [_m(r) for r in con.execute(_meldung_select().where(sb_meldungen.c.uebergabe, sb_meldungen.c.uebernommen_am.is_(None))).mappings()]
    for m in rows:
        m["von"] = schicht(con, m["uebergeben_schicht_id"]) if m["uebergeben_schicht_id"] else None
    return _sortiert(rows)


def der_schicht(con: Connection, sid: int) -> list[dict]:
    return [_m(r) for r in con.execute(_meldung_select().where(sb_meldungen.c.schicht_id == sid).order_by(sb_meldungen.c.id.desc())).mappings()]


def seit(con: Connection, ab: datetime, grenze: int = 50) -> list[dict]:
    """Meldungen, die seit ``ab`` angelegt oder geändert wurden (für „Seit Ihrer letzten Schicht“)."""
    return [_m(r) for r in con.execute(_meldung_select().where(or_(sb_meldungen.c.erstellt_am > ab, sb_meldungen.c.geaendert_am > ab))
                                       .order_by(sb_meldungen.c.id.desc()).limit(grenze)).mappings()]


def verlauf(con: Connection, mid: int) -> list[dict]:
    rows = [dict(r) for r in con.execute(select(sb_verlauf).where(sb_verlauf.c.meldung_id == mid).order_by(sb_verlauf.c.id)).mappings()]
    cache: dict[int, dict | None] = {}
    for v in rows:
        if v["schicht_id"] and v["schicht_id"] not in cache:
            cache[v["schicht_id"]] = schicht(con, v["schicht_id"])
        v["schicht"] = cache.get(v["schicht_id"])
    return rows


def suche(con: Connection, q: str = "", status: str = "", team: str = "", typ: str = "", von: date | None = None, bis: date | None = None,
          nur: str = "", platz_id: int | None = None, grenze: int | None = 500) -> list[dict]:
    bed = []
    if q.strip():
        muster = f"%{q.strip().replace('%', '').replace('_', '')}%"
        bed.append(or_(*(c.ilike(muster) for c in (sb_meldungen.c.titel, sb_meldungen.c.beschreibung, sb_meldungen.c.massnahme,
                                                    sb_meldungen.c.asset, sb_meldungen.c.functional_location, sb_meldungen.c.work_order))))
    if status == "offen_alle":
        bed.append(sb_meldungen.c.status != "erledigt")
    elif status in STATUS:
        bed.append(sb_meldungen.c.status == status)
    if team.isdigit():
        bed.append(sb_schichten.c.team_id == int(team))
    if typ:
        bed.append(sb_meldungen.c.ereignistyp == typ)
    if von:
        bed.append(sb_meldungen.c.erstellt_am >= datetime.combine(von, time.min))
    if bis:
        bed.append(sb_meldungen.c.erstellt_am < datetime.combine(bis + timedelta(days=1), time.min))
    if nur == "sicherheit":
        bed.append(sb_meldungen.c.sicherheitsrelevant)
    elif nur == "stillstand":
        bed.append(sb_meldungen.c.stillstand)
    elif nur == "uebergabe":
        bed.append(sb_meldungen.c.uebergabe)
    if platz_id:
        bed.append(sb_meldungen.c.platz_id == platz_id)
    q2 = _meldung_select().where(and_(true(), *bed)).order_by(sb_meldungen.c.id.desc())
    if grenze:
        q2 = q2.limit(grenze)
    return [_m(r) for r in con.execute(q2).mappings()]


def kommentare(con: Connection, ids: list[int]) -> dict[int, str]:
    """Übernahme-Kommentare und Ergänzungen späterer Schichten je Meldung (Spalte „Kommentar nächste Schicht“)."""
    out: dict[int, list[str]] = {}
    if not ids:
        return {}
    for v in con.execute(select(sb_verlauf.c.meldung_id, sb_verlauf.c.text, sb_verlauf.c.benutzer, sb_verlauf.c.zeit, sb_verlauf.c.schicht_id,
                                sb_meldungen.c.schicht_id.label("ursprung"))
                         .select_from(sb_verlauf.join(sb_meldungen, sb_meldungen.c.id == sb_verlauf.c.meldung_id))
                         .where(sb_verlauf.c.meldung_id.in_(ids), sb_verlauf.c.text.isnot(None), sb_verlauf.c.art.in_(("uebernahme", "ergaenzung", "status")))
                         .order_by(sb_verlauf.c.id)):
        if v.schicht_id != v.ursprung:
            out.setdefault(v.meldung_id, []).append(f"{v.zeit:%d.%m. %H:%M} {v.benutzer}: {v.text}")
    return {k: "\n".join(t) for k, t in out.items()}
