"""REST-Schnittstelle (JSON) – z. B. für die spätere Anbindung an die Instandhaltungs-Software.

Authentifizierung: Header ``Authorization: Bearer <API-Schlüssel>`` (Schlüssel unter Einstellungen → API erzeugen).
Dokumentation der Endpunkte: /api/openapi.json
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, insert, select

from .. import db
from ..db import artikel, bewegungen, reservierungen, users
from ..services import queries
from ..services.lager import MAX_MENGE, BuchungsFehler, Lager, audit
from .buchen import buchung_ausfuehren

router = APIRouter(prefix="/api/v1", tags=["Lager"])


def _user(authorization: str | None, x_api_key: str | None) -> dict:
    token = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    if not token:
        raise HTTPException(401, "API-Schlüssel fehlt")
    with db.engine().connect() as con:
        u = con.execute(select(users).where(users.c.api_token == token)).mappings().first()
    if not u or not u["aktiv"]:
        raise HTTPException(401, "API-Schlüssel ungültig")
    return dict(u)


def _artikel_json(a: dict) -> dict:
    return {k: a.get(k) for k in ("nummer", "bezeichnung", "typ", "kategorie", "hersteller", "hersteller_nr", "lieferant", "lieferant_artnr",
                                  "einheit", "preis", "meldebestand", "mindestbestand", "kritisch", "verwendung", "bestand", "reserviert",
                                  "verfuegbar", "status")} | {"lagerplaetze": [{"platz": o, "menge": m} for o, m in a.get("orte", [])]}


@router.get("/artikel")
def artikel_liste(q: str = "", filter: str = "", authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    _user(authorization, x_api_key)
    with db.engine().connect() as con:
        return [_artikel_json(a) for a in queries.artikel_liste(con, q=q, filter_=filter)]


@router.get("/artikel/{nr}")
def artikel_detail(nr: str, authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    _user(authorization, x_api_key)
    with db.engine().connect() as con:
        a = queries.artikel_detail(con, nr)
    if not a:
        raise HTTPException(404, "Artikel nicht gefunden")
    return _artikel_json(a)


@router.get("/lagerplaetze")
def plaetze(authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    _user(authorization, x_api_key)
    with db.engine().connect() as con:
        return [{k: p[k] for k in ("code", "bereich", "beschreibung", "artikel", "aktiv")} for p in queries.lagerplaetze_uebersicht(con)]


@router.get("/bewegungen")
def bewegungen_liste(seit_id: int = 0, limit: int = 500, authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    _user(authorization, x_api_key)
    with db.engine().connect() as con:
        rows = con.execute(select(bewegungen).where(bewegungen.c.id > seit_id).order_by(bewegungen.c.id).limit(max(1, min(limit, 5000)))).mappings().all()
    return [dict(r) for r in rows]


class Buchung(BaseModel):
    typ: str  # eingang | ausgang | umbuchung | inventur | ausleihe
    artikel: str
    menge: float
    lagerplatz: str
    ziel: str = ""
    empfaenger: str = ""
    kostenstelle: str = ""
    zweck: str = ""


@router.post("/buchungen")
def buchen(b: Buchung, request: Request, authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    u = _user(authorization, x_api_key)
    if u["rolle"] == "lesen":
        raise HTTPException(403, "Rolle darf nicht buchen")
    cfg = request.app.state.cfg
    try:
        with db.schreiben() as con:
            L = Lager(con, u["username"], "api", cfg.lager.negative_bestaende_erlauben, cfg.lager.lagerplaetze_automatisch_anlegen)
            msg = buchung_ausfuehren(L, b.typ, b.artikel, str(b.menge), b.lagerplatz, b.ziel, b.empfaenger, b.kostenstelle, b.zweck)
            letzte = con.execute(select(func.max(bewegungen.c.id))).scalar()
    except BuchungsFehler as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True, "meldung": msg, "bewegung_id": letzte}


class Reservierung(BaseModel):
    artikel: str
    menge: float
    fuer: str
    person: str = ""
    bis: date | None = None


@router.post("/reservierungen")
def reservieren(r: Reservierung, authorization: str | None = Header(None), x_api_key: str | None = Header(None)):
    u = _user(authorization, x_api_key)
    if u["rolle"] == "lesen":
        raise HTTPException(403, "Rolle darf nicht reservieren")
    if not (0 < r.menge <= MAX_MENGE):
        raise HTTPException(422, "Die Menge muss größer als 0 sein.")
    if not r.fuer.strip():
        raise HTTPException(422, "Bitte angeben, wofür reserviert wird.")
    with db.schreiben() as con:
        aid = con.execute(select(artikel.c.id).where(and_(artikel.c.nummer == r.artikel.strip(), artikel.c.aktiv == True))).scalar()  # noqa: E712
        if not aid:
            raise HTTPException(404, "Artikel nicht gefunden")
        rid = con.execute(insert(reservierungen).values(artikel_id=aid, menge=r.menge, fuer=r.fuer, person=r.person or None, bis=r.bis,
                                                        status="offen", erstellt_von=u["username"])).inserted_primary_key[0]
        audit(con, u["username"], "Reservierung (API)", r.artikel, r.model_dump())
    return {"ok": True, "id": rid}
