"""Aufgaben (To-do-Liste) im Schichtbuch (ab 2.13.0).

Allgemeine Aufgaben, die nicht an eine Schicht gebunden sind: z. B. „Filter am Kompressor bestellen“, „Ordnung Werkstatt“.
Eine Aufgabe kann einem Team zugeteilt werden (sonst: alle Teams) – sie erscheint dann im Schichtbuch-Dashboard dieses Teams.
Fälligkeit, Priorität, Anlage (Tag-Nr.), Kommentare und Verlauf; wiederkehrende Aufgaben legen sich nach dem Erledigen neu an.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import case, insert, or_, select, update
from sqlalchemy.engine import Connection

from ..db import sb_aufgaben, sb_aufgaben_verlauf, sb_teams

STATUS = {"offen": "Offen", "in_arbeit": "In Arbeit", "erledigt": "Erledigt"}
PRIO = {"hoch": "Hoch", "mittel": "Mittel", "niedrig": "Niedrig"}


class AufgabenFehler(ValueError):
    pass


def _select():
    return (select(sb_aufgaben, sb_teams.c.name.label("team"), sb_teams.c.farbe.label("team_farbe"))
            .select_from(sb_aufgaben.outerjoin(sb_teams, sb_teams.c.id == sb_aufgaben.c.team_id)))


def _mit(r, heute: date) -> dict:
    a = dict(r)
    a["ueberfaellig"] = bool(a["faellig"] and a["status"] != "erledigt" and a["faellig"] < heute)
    a["heute_faellig"] = bool(a["faellig"] and a["status"] != "erledigt" and a["faellig"] == heute)
    return a


def _sortierung():
    return (case((sb_aufgaben.c.status == "erledigt", 1), else_=0), sb_aufgaben.c.faellig.is_(None), sb_aufgaben.c.faellig,
            case((sb_aufgaben.c.prioritaet == "hoch", 0), (sb_aufgaben.c.prioritaet == "mittel", 1), else_=2), sb_aufgaben.c.id)


def liste(con: Connection, status: str = "offen", team: str = "", q: str = "", nur: str = "", limit: int = 500) -> list[dict]:
    heute = date.today()
    qy = _select()
    if status == "offen":
        qy = qy.where(sb_aufgaben.c.status != "erledigt")
    elif status in STATUS:
        qy = qy.where(sb_aufgaben.c.status == status)
    if team == "alle":
        qy = qy.where(sb_aufgaben.c.team_id.is_(None))
    elif team.isdigit():
        qy = qy.where(sb_aufgaben.c.team_id == int(team))
    if nur == "ueberfaellig":
        qy = qy.where(sb_aufgaben.c.faellig < heute, sb_aufgaben.c.status != "erledigt")
    out = []
    q = q.strip().casefold()
    for r in con.execute(qy.order_by(*_sortierung())).mappings():
        if q and q not in " ".join(str(r[k] or "") for k in ("titel", "beschreibung", "asset", "erstellt_von")).casefold():
            continue
        out.append(_mit(r, heute))
        if len(out) >= limit:
            break
    return out


def fuer_team(con: Connection, team_id: int | None, n: int = 12) -> list[dict]:
    """Offene Aufgaben für das Dashboard: dem Team zugeteilt oder für alle Teams."""
    heute = date.today()
    qy = _select().where(sb_aufgaben.c.status != "erledigt")
    qy = qy.where(or_(sb_aufgaben.c.team_id == team_id, sb_aufgaben.c.team_id.is_(None))) if team_id else qy
    return [_mit(r, heute) for r in con.execute(qy.order_by(*_sortierung()).limit(n)).mappings()]


def anzahl_offen(con: Connection, team_id: int | None) -> int:
    from sqlalchemy import func
    qy = select(func.count()).select_from(sb_aufgaben).where(sb_aufgaben.c.status != "erledigt")
    if team_id:
        qy = qy.where(or_(sb_aufgaben.c.team_id == team_id, sb_aufgaben.c.team_id.is_(None)))
    return con.execute(qy).scalar()


def holen(con: Connection, aid: int) -> dict | None:
    r = con.execute(_select().where(sb_aufgaben.c.id == aid)).mappings().first()
    if not r:
        return None
    a = _mit(r, date.today())
    a["verlauf"] = [dict(v) for v in con.execute(select(sb_aufgaben_verlauf).where(sb_aufgaben_verlauf.c.aufgabe_id == aid)
                                                 .order_by(sb_aufgaben_verlauf.c.zeit, sb_aufgaben_verlauf.c.id)).mappings()]
    return a


def _verlauf(con, aid: int, benutzer: str, art: str, text: str | None = None) -> None:
    con.execute(insert(sb_aufgaben_verlauf).values(aufgabe_id=aid, zeit=datetime.now().replace(microsecond=0), benutzer=benutzer, art=art, text=text))


def werte(con: Connection, f) -> dict:
    """Formular -> Werte (prüft Titel, Datum, Team, Wiederholung)."""
    from .schichtbuch import asset_aufloesen
    titel = " ".join((f.get("titel") or "").split())[:200]
    if not titel:
        raise AufgabenFehler("Bitte einen Titel angeben.")
    faellig = None
    if f.get("faellig"):
        try:
            faellig = date.fromisoformat(f.get("faellig"))
        except ValueError as e:
            raise AufgabenFehler("Fällig am: bitte ein gültiges Datum.") from e
    tid = f.get("team_id") or ""
    team_id = int(tid) if str(tid).isdigit() and con.execute(select(sb_teams.c.id).where(sb_teams.c.id == int(tid))).scalar() else None
    wdh = (f.get("wiederholen_tage") or "").strip()
    if wdh and (not wdh.isdigit() or not 1 <= int(wdh) <= 365):
        raise AufgabenFehler("Wiederholen: bitte eine Zahl von 1 bis 365 Tagen.")
    if wdh and not faellig:
        raise AufgabenFehler("Für eine wiederkehrende Aufgabe bitte ein Fälligkeitsdatum angeben.")
    platz_id, asset, _ = asset_aufloesen(con, f.get("asset") or "")
    prio = f.get("prioritaet") if f.get("prioritaet") in PRIO else "mittel"
    return {"titel": titel, "beschreibung": (f.get("beschreibung") or "").strip()[:4000] or None, "prioritaet": prio, "faellig": faellig,
            "team_id": team_id, "platz_id": platz_id, "asset": asset, "wiederholen_tage": int(wdh) if wdh else None}


def anlegen(con: Connection, w: dict, benutzer: str) -> int:
    jetzt = datetime.now().replace(microsecond=0)
    aid = con.execute(insert(sb_aufgaben).values(status="offen", erstellt_am=jetzt, erstellt_von=benutzer, **w)).inserted_primary_key[0]
    _verlauf(con, aid, benutzer, "angelegt")
    return aid


def aendern(con: Connection, aid: int, w: dict, benutzer: str) -> None:
    alt = holen(con, aid)
    if not alt:
        raise AufgabenFehler("Aufgabe nicht gefunden.")
    geaendert = [k for k in w if alt.get(k) != w[k]]
    if not geaendert:
        return
    con.execute(update(sb_aufgaben).where(sb_aufgaben.c.id == aid).values(geaendert_am=datetime.now().replace(microsecond=0), geaendert_von=benutzer, **w))
    if "team_id" in geaendert:
        name = con.execute(select(sb_teams.c.name).where(sb_teams.c.id == w["team_id"])).scalar() if w["team_id"] else "alle Teams"
        _verlauf(con, aid, benutzer, "zugeteilt", f"an {name}")
    rest = [k for k in geaendert if k != "team_id"]
    if rest:
        _verlauf(con, aid, benutzer, "geaendert", ", ".join({"titel": "Titel", "beschreibung": "Beschreibung", "prioritaet": "Priorität",
                                                               "faellig": "Fälligkeit", "platz_id": "Anlage", "asset": "Anlage",
                                                               "wiederholen_tage": "Wiederholung"}.get(k, k) for k in rest))


def status_setzen(con: Connection, aid: int, status: str, benutzer: str, text: str = "") -> int | None:
    """Status ändern; beim Erledigen einer wiederkehrenden Aufgabe die nächste anlegen. Gibt deren ID zurück."""
    a = holen(con, aid)
    if not a:
        raise AufgabenFehler("Aufgabe nicht gefunden.")
    if status not in STATUS:
        raise AufgabenFehler("Unbekannter Status.")
    text = (text or "").strip()[:2000]
    jetzt = datetime.now().replace(microsecond=0)
    if status == a["status"]:
        if text:
            _verlauf(con, aid, benutzer, "kommentar", text)
        return None
    werte = {"status": status, "geaendert_am": jetzt, "geaendert_von": benutzer}
    if status == "erledigt":
        werte.update(erledigt_am=jetzt, erledigt_von=benutzer, erledigt_text=text or None)
    elif a["status"] == "erledigt":
        werte.update(erledigt_am=None, erledigt_von=None, erledigt_text=None)
    con.execute(update(sb_aufgaben).where(sb_aufgaben.c.id == aid).values(**werte))
    _verlauf(con, aid, benutzer, "status", f"{STATUS[status]}" + (f": {text}" if text else ""))
    if status == "erledigt" and a["wiederholen_tage"]:
        n = timedelta(days=a["wiederholen_tage"])
        naechste = (a["faellig"] or date.today()) + n  # im Rhythmus bleiben …
        if naechste <= date.today():                      # … außer der Termin läge schon in der Vergangenheit
            naechste = date.today() + n
        neu = {k: a[k] for k in ("titel", "beschreibung", "prioritaet", "team_id", "platz_id", "asset", "wiederholen_tage")}
        neu["faellig"] = naechste
        nid = anlegen(con, neu, benutzer)
        _verlauf(con, nid, benutzer, "kommentar", f"Wiederkehrend – nach Erledigen von Aufgabe Nr. {aid} angelegt.")
        return nid
    return None


def kommentar(con: Connection, aid: int, benutzer: str, text: str) -> None:
    text = (text or "").strip()[:2000]
    if not text:
        raise AufgabenFehler("Bitte einen Kommentar eingeben.")
    if not con.execute(select(sb_aufgaben.c.id).where(sb_aufgaben.c.id == aid)).scalar():
        raise AufgabenFehler("Aufgabe nicht gefunden.")
    _verlauf(con, aid, benutzer, "kommentar", text)
