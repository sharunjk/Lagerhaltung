"""EX-Handys im Schichtbuch (ab 2.13.0): Rufnummer, SIM-PIN/PUK, Übergabe bei Schichtwechsel.

PIN und PUK liegen verschlüsselt in der Datenbank (Fernet; Schlüssel aus dem Sitzungsschlüssel des Programms abgeleitet).
Angezeigt werden sie nur nach erneuter Eingabe des eigenen Passworts – falls jemand vergessen hat, sich abzumelden.
Jede Anzeige steht im Protokoll.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import sb_handy_uebergaben, sb_handys, sb_schichten


def _f(geheim: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("ex-handy-pin|" + (geheim or "")).encode()).digest()))


def verschluesseln(geheim: str, wert: str) -> str | None:
    wert = (wert or "").strip()
    return _f(geheim).encrypt(wert.encode()).decode() if wert else None


def entschluesseln(geheim: str, wert: str | None) -> str | None:
    if not wert:
        return None
    try:
        return _f(geheim).decrypt(wert.encode()).decode()
    except (InvalidToken, ValueError):
        return None  # z. B. Sitzungsschlüssel geändert: PIN neu eintragen


def liste(con: Connection, alle: bool = False) -> list[dict]:
    q = select(sb_handys).order_by(sb_handys.c.reihenfolge, sb_handys.c.id)
    if not alle:
        q = q.where(sb_handys.c.aktiv)
    out = []
    for r in con.execute(q).mappings():
        h = dict(r)
        h["hat_pin"], h["hat_puk"] = bool(h.pop("pin")), bool(h.pop("puk"))
        h["letzte"] = con.execute(select(sb_handy_uebergaben).where(sb_handy_uebergaben.c.handy_id == h["id"])
                                  .order_by(sb_handy_uebergaben.c.zeit.desc(), sb_handy_uebergaben.c.id.desc()).limit(1)).mappings().first()
        out.append(h)
    return out


def speichern(con: Connection, hid: int | None, name: str, nummer: str, pin: str | None, puk: str | None, bemerkung: str, aktiv: bool,
              geheim: str, benutzer: str) -> int:
    """PIN/PUK: None = unverändert lassen, "" = löschen, sonst neu setzen."""
    name = " ".join((name or "").split())[:100]
    if not name:
        raise ValueError("Bitte einen Namen angeben, z. B. „EX-Handy 1“.")
    for lab, w in (("PIN", pin), ("PUK", puk)):
        if w and not w.strip().isdigit():
            raise ValueError(f"Die {lab} darf nur Ziffern enthalten.")
    werte = {"name": name, "nummer": " ".join((nummer or "").split())[:60] or None, "bemerkung": (bemerkung or "").strip()[:300] or None,
             "aktiv": aktiv, "geaendert_am": datetime.now().replace(microsecond=0), "geaendert_von": benutzer}
    if pin is not None:
        werte["pin"] = verschluesseln(geheim, pin)
    if puk is not None:
        werte["puk"] = verschluesseln(geheim, puk)
    if hid:
        con.execute(update(sb_handys).where(sb_handys.c.id == hid).values(**werte))
        return hid
    rf = (con.execute(select(func.max(sb_handys.c.reihenfolge))).scalar() or 0) + 1
    return con.execute(insert(sb_handys).values(reihenfolge=rf, **werte)).inserted_primary_key[0]


def geheimnis(con: Connection, hid: int, feld: str, geheim: str) -> str | None:
    if feld not in ("pin", "puk"):
        raise ValueError("Unbekanntes Feld.")
    wert = con.execute(select(getattr(sb_handys.c, feld)).where(sb_handys.c.id == hid)).scalar()
    return entschluesseln(geheim, wert)


def uebergabe_speichern(con: Connection, hid: int, sid: int | None, von: str, an: str, benutzer: str, zeit: datetime | None = None) -> None:
    an = " ".join((an or "").split())[:200]
    if not an:
        raise ValueError("Bitte angeben, an wen das EX-Handy übergeben wurde.")
    if not con.execute(select(sb_handys.c.id).where(sb_handys.c.id == hid)).scalar():
        raise ValueError("Dieses EX-Handy gibt es nicht.")
    con.execute(insert(sb_handy_uebergaben).values(handy_id=hid, schicht_id=sid, zeit=zeit or datetime.now().replace(microsecond=0),
                                                   von=(von or "")[:200] or None, an=an, benutzer=benutzer))


def der_schichten(con: Connection, ids: list[int]) -> dict[int, list[dict]]:
    """Übergaben je Schicht (für „Vorherige Schichten“)."""
    if not ids:
        return {}
    out: dict[int, list] = {}
    for r in con.execute(select(sb_handy_uebergaben, sb_handys.c.name).select_from(
            sb_handy_uebergaben.join(sb_handys, sb_handys.c.id == sb_handy_uebergaben.c.handy_id))
            .where(sb_handy_uebergaben.c.schicht_id.in_(ids)).order_by(sb_handy_uebergaben.c.id)).mappings():
        out.setdefault(r["schicht_id"], []).append(dict(r))
    return out


def verlauf(con: Connection, hid: int, n: int = 30) -> list[dict]:
    from ..db import sb_teams, sb_zeiten
    from .schichtbuch import bezeichnung
    rows = []
    for r in con.execute(select(sb_handy_uebergaben, sb_schichten.c.datum, sb_zeiten.c.name.label("zname"), sb_zeiten.c.beginn,
                                sb_zeiten.c.ende, sb_teams.c.name.label("team"))
                         .select_from(sb_handy_uebergaben.outerjoin(sb_schichten, sb_schichten.c.id == sb_handy_uebergaben.c.schicht_id)
                                      .outerjoin(sb_zeiten, sb_zeiten.c.id == sb_schichten.c.zeit_id)
                                      .outerjoin(sb_teams, sb_teams.c.id == sb_schichten.c.team_id))
                         .where(sb_handy_uebergaben.c.handy_id == hid).order_by(sb_handy_uebergaben.c.zeit.desc()).limit(n)).mappings():
        d = dict(r)
        d["schicht"] = bezeichnung(d["datum"], {"name": d["zname"], "beginn": d["beginn"], "ende": d["ende"]}) if d["datum"] else ""
        rows.append(d)
    return rows
