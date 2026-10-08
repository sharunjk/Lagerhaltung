"""Lesende Abfragen für Listen, Übersicht und Auswertungen."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.engine import Connection

from ..db import (
    anhaenge, artikel, bestand, bestellungen, bewegungen, lagerplaetze, lieferanten, reservierungen,
)

TYP_TEXT = {"eingang": "Eingang", "ausgang": "Entnahme", "umbuchung": "Umbuchung", "inventur": "Inventur",
            "anlage": "Neuer Artikel", "ausleihe": "Ausleihe", "rueckgabe": "Rückgabe", "info": "Info"}
BESTANDSWIRKSAM = ("eingang", "ausgang", "umbuchung", "inventur", "anlage", "ausleihe", "rueckgabe")


def status_von(bestand_: float, melde, mindest) -> str:
    if bestand_ < 0:
        return "kritisch"
    if mindest and mindest > 0 and bestand_ <= mindest:
        return "kritisch"
    if melde and melde > 0 and bestand_ <= melde:
        return "melden"
    return "ok"


def _natkey(s: str):
    s = s or ""
    return (0, int(s), "") if s.isdigit() else (1, 0, s.lower())


def orte_je_artikel(con: Connection) -> dict[int, list[tuple[str, float]]]:
    out: dict[int, list] = defaultdict(list)
    for aid, code, m in con.execute(select(bestand.c.artikel_id, lagerplaetze.c.code, bestand.c.menge)
                                    .select_from(bestand.join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id))
                                    .order_by(bestand.c.menge.desc(), lagerplaetze.c.code)):
        out[aid].append((code, float(m or 0)))
    return out


def reserviert_je_artikel(con: Connection) -> dict[int, float]:
    return {a: float(m) for a, m in con.execute(select(reservierungen.c.artikel_id, func.sum(reservierungen.c.menge))
                                                .where(reservierungen.c.status == "offen").group_by(reservierungen.c.artikel_id))}


def artikel_liste(con: Connection, q: str = "", filter_: str = "", kategorie: str = "", platz: str = "", sort: str = "nr",
                  archiv: bool = False) -> list[dict]:
    a = artikel
    stmt = select(a, lieferanten.c.name.label("lieferant")).select_from(a.outerjoin(lieferanten, lieferanten.c.id == a.c.lieferant_id))
    stmt = stmt.where(a.c.aktiv == (not archiv))
    if q:
        like = f"%{q.strip()}%"
        platz_match = select(bestand.c.artikel_id).join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id).where(lagerplaetze.c.code.ilike(like))
        stmt = stmt.where(or_(a.c.nummer.ilike(like), a.c.bezeichnung.ilike(like), a.c.typ.ilike(like), a.c.kategorie.ilike(like),
                              a.c.hersteller.ilike(like), a.c.hersteller_nr.ilike(like), a.c.lieferant_artnr.ilike(like),
                              a.c.verwendung.ilike(like), a.c.notiz.ilike(like), lieferanten.c.name.ilike(like), a.c.id.in_(platz_match)))
    if kategorie:
        stmt = stmt.where(a.c.kategorie == kategorie)
    if platz:
        stmt = stmt.where(a.c.id.in_(select(bestand.c.artikel_id).join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id)
                                     .where(lagerplaetze.c.code == platz)))
    rows = [dict(r) for r in con.execute(stmt).mappings()]
    orte = orte_je_artikel(con)
    res = reserviert_je_artikel(con)
    for r in rows:
        o = orte.get(r["id"], [])
        r["orte"] = [x for x in o if x[1] != 0] or o[:1]
        r["bestand"] = sum(m for _, m in o)
        r["reserviert"] = res.get(r["id"], 0.0)
        r["verfuegbar"] = r["bestand"] - r["reserviert"]
        r["status"] = status_von(r["bestand"], r["meldebestand"], r["mindestbestand"])
    if filter_ == "melden":
        rows = [r for r in rows if r["status"] in ("melden", "kritisch")]
    elif filter_ == "kritisch":
        rows = [r for r in rows if r["status"] == "kritisch"]
    elif filter_ == "leer":
        rows = [r for r in rows if r["bestand"] <= 0]
    elif filter_ == "ersatzteil":
        rows = [r for r in rows if r["kritisch"]]
    elif filter_ == "reserviert":
        rows = [r for r in rows if r["reserviert"] > 0]
    keyf = {"nr": lambda r: _natkey(r["nummer"]), "bez": lambda r: (r["bezeichnung"] or "").lower(),
            "bestand": lambda r: r["bestand"], "kat": lambda r: (r["kategorie"] or "").lower(),
            "status": lambda r: {"kritisch": 0, "melden": 1, "ok": 2}[r["status"]]}.get(sort.lstrip("-"), lambda r: _natkey(r["nummer"]))
    rows.sort(key=keyf, reverse=sort.startswith("-"))
    return rows


def artikel_detail(con: Connection, nr: str) -> dict | None:
    r = con.execute(select(artikel, lieferanten.c.name.label("lieferant"))
                    .select_from(artikel.outerjoin(lieferanten, lieferanten.c.id == artikel.c.lieferant_id))
                    .where(artikel.c.nummer == nr)).mappings().first()
    if not r:
        return None
    d = dict(r)
    d["orte"] = [(c, float(m or 0)) for c, m in con.execute(
        select(lagerplaetze.c.code, bestand.c.menge).select_from(bestand.join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id))
        .where(bestand.c.artikel_id == d["id"]).order_by(bestand.c.menge.desc(), lagerplaetze.c.code))]
    d["bestand"] = sum(m for _, m in d["orte"])
    d["reservierungen"] = [dict(x) for x in con.execute(select(reservierungen).where(and_(
        reservierungen.c.artikel_id == d["id"], reservierungen.c.status == "offen")).order_by(reservierungen.c.bis)).mappings()]
    d["reserviert"] = sum(float(x["menge"]) for x in d["reservierungen"])
    d["verfuegbar"] = d["bestand"] - d["reserviert"]
    d["ausleihen"] = [x for x in offene_ausleihen(con) if x["artikel_id"] == d["id"]]
    d["status"] = status_von(d["bestand"], d["meldebestand"], d["mindestbestand"])
    d["anhaenge"] = [dict(x) for x in con.execute(select(anhaenge).where(anhaenge.c.artikel_id == d["id"]).order_by(anhaenge.c.id.desc())).mappings()]
    d["bild"] = next((x for x in d["anhaenge"] if x["ist_bild"]), None)
    d["bestellungen"] = [dict(x) for x in con.execute(select(bestellungen).where(and_(
        bestellungen.c.artikel_id == d["id"], bestellungen.c.status.in_(["offen", "bestellt", "teilgeliefert"])))).mappings()]
    return d


def bewegungen_liste(con: Connection, artikel_id: int | None = None, typ: str = "", benutzer: str = "", platz: str = "",
                     von: date | None = None, bis: date | None = None, q: str = "", limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
    b = bewegungen
    conds = []
    if artikel_id:
        conds.append(b.c.artikel_id == artikel_id)
    if typ:
        conds.append(b.c.typ == typ)
    if benutzer:
        conds.append(b.c.benutzer == benutzer)
    if platz:
        conds.append(b.c.lagerplatz == platz)
    if von:
        conds.append(b.c.zeit >= datetime.combine(von, datetime.min.time()))
    if bis:
        conds.append(b.c.zeit < datetime.combine(bis + timedelta(days=1), datetime.min.time()))
    if q:
        like = f"%{q}%"
        conds.append(or_(b.c.artikel_nr.ilike(like), artikel.c.bezeichnung.ilike(like), b.c.empfaenger.ilike(like),
                         b.c.kostenstelle.ilike(like), b.c.zweck.ilike(like), b.c.text.ilike(like)))
    base = b.outerjoin(artikel, artikel.c.id == b.c.artikel_id)
    total = con.execute(select(func.count()).select_from(base).where(*conds)).scalar()
    rows = con.execute(select(b, artikel.c.bezeichnung, artikel.c.einheit).select_from(base).where(*conds)
                       .order_by(b.c.id.desc()).limit(limit).offset(offset)).mappings().all()
    return [dict(r) for r in rows], total


def letzte_id(con: Connection) -> int:
    return con.execute(select(func.max(bewegungen.c.id))).scalar() or 0


def dashboard(con: Connection) -> dict:
    arts = artikel_liste(con)
    heute = date.today()
    b = bewegungen
    t0 = datetime.combine(heute, datetime.min.time())
    wirksam = b.c.typ.in_(["eingang", "ausgang", "umbuchung", "inventur", "ausleihe", "rueckgabe"])
    heute_n = con.execute(select(func.count()).where(and_(b.c.zeit >= t0, wirksam))).scalar()
    woche_n = con.execute(select(func.count()).where(and_(b.c.zeit >= t0 - timedelta(days=6), wirksam))).scalar()
    top = con.execute(select(b.c.artikel_nr, artikel.c.bezeichnung, func.sum(-b.c.menge).label("menge"))
                      .select_from(b.outerjoin(artikel, artikel.c.id == b.c.artikel_id))
                      .where(and_(b.c.typ == "ausgang", b.c.storniert_durch.is_(None), b.c.zeit >= t0 - timedelta(days=90)))
                      .group_by(b.c.artikel_nr, artikel.c.bezeichnung).order_by(func.sum(-b.c.menge).desc()).limit(8)).mappings().all()
    tag = func.date(b.c.zeit)
    akt = {str(d): (e, a) for d, e, a in con.execute(
        select(tag, func.sum(case((b.c.typ == "eingang", 1), else_=0)), func.sum(case((b.c.typ == "ausgang", 1), else_=0)))
        .where(b.c.zeit >= t0 - timedelta(days=29)).group_by(tag))}
    verlauf = [((heute - timedelta(days=29 - i)), *akt.get(str(heute - timedelta(days=29 - i)), (0, 0))) for i in range(30)]
    return dict(
        anzahl=len(arts), melden=[x for x in arts if x["status"] == "melden"], kritisch=[x for x in arts if x["status"] == "kritisch"],
        heute=heute_n, woche=woche_n, top=[dict(t) for t in top], verlauf=verlauf,
        offene_bestellungen=con.execute(select(func.count()).where(bestellungen.c.status.in_(["offen", "bestellt", "teilgeliefert"]))).scalar(),
        ausleihen=offene_ausleihen(con),
        reservierungen=con.execute(select(func.count()).where(reservierungen.c.status == "offen")).scalar(),
        plaetze=con.execute(select(func.count()).select_from(lagerplaetze).where(lagerplaetze.c.aktiv == True)).scalar(),  # noqa: E712
        lagerwert=sum(x["bestand"] * x["preis"] for x in arts if x["preis"] and x["bestand"] > 0),
    )


def offene_ausleihen(con: Connection) -> list[dict]:
    b = bewegungen
    zur = select(b.c.bezug_id, func.sum(b.c.menge).label("zurueck")).where(b.c.typ == "rueckgabe").group_by(b.c.bezug_id).subquery()
    rows = con.execute(select(b, artikel.c.bezeichnung, artikel.c.einheit, func.coalesce(zur.c.zurueck, 0).label("zurueck"))
                       .select_from(b.outerjoin(zur, zur.c.bezug_id == b.c.id).outerjoin(artikel, artikel.c.id == b.c.artikel_id))
                       .where(b.c.typ == "ausleihe").order_by(b.c.zeit)).mappings().all()
    out = []
    for r in rows:
        offen = -float(r["menge"]) - float(r["zurueck"])
        if offen > 1e-9:
            d = dict(r)
            d["offen"] = offen
            d["ueberfaellig"] = bool(r["rueckgabe_bis"] and r["rueckgabe_bis"] < date.today())
            out.append(d)
    return out


def lagerplaetze_uebersicht(con: Connection) -> list[dict]:
    stats = {pid: (n, s) for pid, n, s in con.execute(
        select(bestand.c.lagerplatz_id, func.count(), func.sum(bestand.c.menge)).where(bestand.c.menge != 0).group_by(bestand.c.lagerplatz_id))}
    out = []
    for p in con.execute(select(lagerplaetze).order_by(lagerplaetze.c.code)).mappings():
        n, s = stats.get(p["id"], (0, 0))
        out.append({**dict(p), "artikel": n, "menge": float(s or 0)})
    return out


def platz_inhalt(con: Connection, code: str) -> tuple[dict | None, list[dict]]:
    p = con.execute(select(lagerplaetze).where(lagerplaetze.c.code == code)).mappings().first()
    if not p:
        return None, []
    rows = con.execute(select(artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, bestand.c.menge)
                       .select_from(bestand.join(artikel, artikel.c.id == bestand.c.artikel_id))
                       .where(bestand.c.lagerplatz_id == p["id"]).order_by(bestand.c.menge == 0, artikel.c.nummer)).mappings().all()
    return dict(p), [dict(r) for r in rows]


def vorschlaege(con: Connection) -> dict:
    def distinct(col, where=None):
        q = select(col).distinct().where(col.isnot(None), col != "")
        if where is not None:
            q = q.where(where)
        return sorted({r[0] for r in con.execute(q)}, key=str.lower)
    return dict(
        plaetze=[r[0] for r in con.execute(select(lagerplaetze.c.code).where(lagerplaetze.c.aktiv == True).order_by(lagerplaetze.c.code))],  # noqa: E712
        kategorien=distinct(artikel.c.kategorie),
        empfaenger=distinct(bewegungen.c.empfaenger)[:300],
        kostenstellen=distinct(bewegungen.c.kostenstelle)[:300],
        einheiten=sorted({"Stk", "m", "kg", "l", "Pck", "Satz", *distinct(artikel.c.einheit)}),
    )


def benutzernamen(con: Connection) -> list[str]:
    return [r[0] for r in con.execute(select(bewegungen.c.benutzer).distinct().order_by(bewegungen.c.benutzer)) if r[0]]


def naechste_nummer(con: Connection) -> str:
    nums = [int(r[0]) for r in con.execute(select(artikel.c.nummer)) if (r[0] or "").isdigit() and len(r[0]) <= 6]
    nums += [int(r[0]) for r in con.execute(select(bewegungen.c.artikel_nr).distinct()) if (r[0] or "").isdigit() and len(r[0]) <= 6]
    return str(max(nums) + 1) if nums else "10001"


def verbrauch(con: Connection, von: date, bis: date) -> list[dict]:
    b = bewegungen
    t0, t1 = datetime.combine(von, datetime.min.time()), datetime.combine(bis + timedelta(days=1), datetime.min.time())
    rows = con.execute(
        select(b.c.artikel_nr, artikel.c.bezeichnung, artikel.c.preis, artikel.c.einheit,
               func.sum(case((b.c.typ == "ausgang", -b.c.menge), else_=0)).label("ausgang"),
               func.sum(case((b.c.typ == "eingang", b.c.menge), else_=0)).label("eingang"), func.count().label("buchungen"))
        .select_from(b.outerjoin(artikel, artikel.c.id == b.c.artikel_id))
        .where(and_(b.c.typ.in_(["eingang", "ausgang"]), b.c.zeit >= t0, b.c.zeit < t1))
        .group_by(b.c.artikel_nr, artikel.c.bezeichnung, artikel.c.preis, artikel.c.einheit)
        .order_by(func.sum(case((b.c.typ == "ausgang", -b.c.menge), else_=0)).desc())).mappings().all()
    return [dict(r) for r in rows]


def verbrauch_kostenstelle(con: Connection, von: date, bis: date) -> list[dict]:
    b = bewegungen
    t0, t1 = datetime.combine(von, datetime.min.time()), datetime.combine(bis + timedelta(days=1), datetime.min.time())
    k = func.coalesce(b.c.kostenstelle, "")
    rows = con.execute(select(k.label("kostenstelle"), func.sum(-b.c.menge).label("menge"), func.count().label("buchungen"),
                              func.sum(-b.c.menge * func.coalesce(artikel.c.preis, 0)).label("wert"))
                       .select_from(b.outerjoin(artikel, artikel.c.id == b.c.artikel_id))
                       .where(and_(b.c.typ == "ausgang", b.c.zeit >= t0, b.c.zeit < t1)).group_by(k)
                       .order_by(func.sum(-b.c.menge).desc())).mappings().all()
    return [dict(r) for r in rows]


def ladenhueter(con: Connection, monate: int) -> list[dict]:
    b = bewegungen
    letzte = {a: d for a, d in con.execute(select(b.c.artikel_id, func.max(b.c.zeit)).where(
        b.c.typ.in_(["eingang", "ausgang", "anlage", "ausleihe"])).group_by(b.c.artikel_id))}
    grenze = datetime.now() - timedelta(days=30 * monate)
    out = []
    for a in artikel_liste(con):
        if a["bestand"] <= 0:
            continue
        d = letzte.get(a["id"])
        if isinstance(d, str):
            d = datetime.fromisoformat(d)
        if d is None or d < grenze:
            a["letzte_bewegung"] = d
            out.append(a)
    out.sort(key=lambda r: r["letzte_bewegung"] or datetime.min)
    return out


def bestandsverlauf(con: Connection, artikel_id: int, akt: float) -> list[tuple[str, float]]:
    rows = con.execute(select(bewegungen.c.zeit, bewegungen.c.menge, bewegungen.c.typ).where(and_(
        bewegungen.c.artikel_id == artikel_id, bewegungen.c.typ.in_(["eingang", "ausgang", "inventur", "anlage", "ausleihe", "rueckgabe"])))
        .order_by(bewegungen.c.id.desc()).limit(120)).all()
    punkte = [(datetime.now().strftime("%d.%m.%Y"), akt)]
    for zeit, menge, typ in rows:
        punkte.append((zeit.strftime("%d.%m.%Y"), akt))
        akt -= float(menge or 0)
        if typ == "anlage":
            break
    punkte.reverse()
    return punkte
