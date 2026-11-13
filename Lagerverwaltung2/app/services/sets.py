"""Sets (ab 2.12.0): ein Lagerartikel, der aus mehreren Artikeln mit eigener Nummer besteht.

* Das Set ist ein normaler Artikel (eigene Nummer, Lagerplatz, Bestand = Anzahl Sets, Etikett, Tag-Nr.).
* Der Inhalt steht in ``artikel_set_inhalt`` (Teil + Menge je Set). Die Teile im Set zählen NICHT zum Bestand der Teile.
* Normal wird das ganze Set entnommen (übliche Entnahme). Wird ein einzelnes Teil herausgenommen, entsteht ein Eintrag in
  ``set_fehlteile``: das Set ist unvollständig, bis das Teil nachgelegt wird oder das unvollständige Set entnommen ist.
  Diese Warnung erscheint am Set, beim Buchen (PC, Handscanner) und in der Erfolgsmeldung der Entnahme.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import artikel, artikel_set_inhalt, bestand, lagerplaetze, set_fehlteile
from .lager import BuchungsFehler, audit, fmt_num, parse_num

ERLEDIGT_TEXT = {"nachgelegt": "Teil wieder ins Set gelegt", "aus_lager": "aus dem Lager nachgelegt (gebucht)",
                 "set_entnommen": "unvollständiges Set entnommen", "kein_bestand": "kein Set mehr auf Lager"}


def _gesamt(con, artikel_id: int) -> float:
    return float(con.execute(select(func.coalesce(func.sum(bestand.c.menge), 0)).where(bestand.c.artikel_id == artikel_id)).scalar())


def inhalt(con: Connection, set_id: int) -> list[dict]:
    """Teile des Sets mit Nummer, Bezeichnung, Einheit, Menge je Set und dem Einzelbestand des Teils (außerhalb von Sets)."""
    rows = [dict(r) for r in con.execute(
        select(artikel_set_inhalt.c.teil_id, artikel_set_inhalt.c.menge, artikel.c.nummer, artikel.c.bezeichnung, artikel.c.einheit, artikel.c.aktiv)
        .select_from(artikel_set_inhalt.join(artikel, artikel.c.id == artikel_set_inhalt.c.teil_id))
        .where(artikel_set_inhalt.c.set_id == set_id).order_by(artikel_set_inhalt.c.reihenfolge, artikel_set_inhalt.c.id)).mappings()]
    for r in rows:
        r["einzelbestand"] = _gesamt(con, r["teil_id"])
    return rows


def in_sets(con: Connection, teil_id: int) -> list[dict]:
    """Sets, die dieses Teil enthalten – mit Anzahl Sets auf Lager und Lagerplätzen (für „Enthalten in …“)."""
    rows = [dict(r) for r in con.execute(
        select(artikel.c.id, artikel.c.nummer, artikel.c.bezeichnung, artikel_set_inhalt.c.menge)
        .select_from(artikel_set_inhalt.join(artikel, artikel.c.id == artikel_set_inhalt.c.set_id))
        .where(artikel_set_inhalt.c.teil_id == teil_id, artikel.c.aktiv).order_by(artikel.c.nummer)).mappings()]
    for r in rows:
        r["orte"] = [(c, float(m)) for c, m in con.execute(
            select(lagerplaetze.c.code, bestand.c.menge).select_from(bestand.join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id))
            .where(bestand.c.artikel_id == r["id"], bestand.c.menge > 0).order_by(lagerplaetze.c.code))]
        r["sets"] = sum(m for _, m in r["orte"])
    return rows


def offene_fehlteile(con: Connection, set_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(select(set_fehlteile).where(set_fehlteile.c.set_id == set_id, set_fehlteile.c.erledigt_am.is_(None))
                                         .order_by(set_fehlteile.c.entnommen_am, set_fehlteile.c.id)).mappings()]


def erledigte_fehlteile(con: Connection, set_id: int, n: int = 10) -> list[dict]:
    return [dict(r) for r in con.execute(select(set_fehlteile).where(set_fehlteile.c.set_id == set_id, set_fehlteile.c.erledigt_am.is_not(None))
                                         .order_by(set_fehlteile.c.erledigt_am.desc()).limit(n)).mappings()]


def warnung(fehl: list[dict]) -> str:
    """„Set unvollständig – es fehlt: 1 × 4711 Pulsationsdämpfer, 2 × 4712 Dichtung“"""
    if not fehl:
        return ""
    teile = ", ".join(f"{fmt_num(f['menge'])} × {f['teil_nr']} {f['teil_bezeichnung'] or ''}".strip() for f in fehl)
    return f"Achtung: Set unvollständig – es fehlt: {teile}."


def inhalt_speichern(con: Connection, set_id: int, eintraege: list[tuple[str, str]], benutzer: str, set_nr: str) -> None:
    """Inhalt genau auf diese Liste setzen: [(Artikelnummer oder „Nummer – Bezeichnung“, Menge), …]."""
    ziel: dict[int, float] = {}
    reihen: dict[int, int] = {}
    for i, (nr, menge) in enumerate(eintraege):
        nr = (nr or "").split(" – ")[0].strip()
        if not nr:
            continue
        a = con.execute(select(artikel.c.id, artikel.c.nummer, artikel.c.ist_set, artikel.c.aktiv).where(artikel.c.nummer == nr)).mappings().first()
        if not a:
            raise BuchungsFehler(f"Set-Inhalt: Artikel {nr} gibt es nicht. Bitte zuerst als Artikel anlegen.")
        if a["id"] == set_id:
            raise BuchungsFehler("Ein Set kann sich nicht selbst enthalten.")
        if a["ist_set"]:
            raise BuchungsFehler(f"Set-Inhalt: {nr} ist selbst ein Set. Sets können keine Sets enthalten.")
        m = parse_num(menge) if str(menge or "").strip() else 1.0
        if m is None or m <= 0:
            raise BuchungsFehler(f"Set-Inhalt: Menge „{menge}“ bei {nr} ist ungültig.")
        ziel[a["id"]] = ziel.get(a["id"], 0) + m
        reihen.setdefault(a["id"], i)
    alt = {r.teil_id: float(r.menge) for r in con.execute(select(artikel_set_inhalt.c.teil_id, artikel_set_inhalt.c.menge)
                                                             .where(artikel_set_inhalt.c.set_id == set_id))}
    con.execute(artikel_set_inhalt.delete().where(artikel_set_inhalt.c.set_id == set_id))
    for tid, m in ziel.items():
        con.execute(insert(artikel_set_inhalt).values(set_id=set_id, teil_id=tid, menge=m, reihenfolge=reihen[tid]))
    if alt != ziel:
        namen = dict(con.execute(select(artikel.c.id, artikel.c.nummer).where(artikel.c.id.in_(list(ziel) or [0]))).all())
        audit(con, benutzer, "Set-Inhalt geändert", set_nr, {"inhalt": [f"{fmt_num(m)} × {namen[t]}" for t, m in ziel.items()]})


def teil_entnehmen(con: Connection, set_artikel: dict, teil_nr: str, menge, platz: str, benutzer: str,
                   empfaenger: str = "", zweck: str = "") -> str:
    """Ein einzelnes Teil aus einem Set nehmen. Bestand des Sets bleibt, das Set gilt als unvollständig."""
    sid = set_artikel["id"]
    teil_nr = (teil_nr or "").split(" – ")[0].strip()
    t = con.execute(select(artikel_set_inhalt.c.menge, artikel.c.id, artikel.c.nummer, artikel.c.bezeichnung)
                    .select_from(artikel_set_inhalt.join(artikel, artikel.c.id == artikel_set_inhalt.c.teil_id))
                    .where(artikel_set_inhalt.c.set_id == sid, artikel.c.nummer == teil_nr)).mappings().first()
    if not t:
        raise BuchungsFehler(f"{teil_nr or 'Das Teil'} gehört nicht zum Set {set_artikel['nummer']}.")
    m = parse_num(menge)
    if m is None or m <= 0:
        raise BuchungsFehler("Die Menge muss größer als 0 sein.")
    sets = _gesamt(con, sid)
    if sets <= 0:
        raise BuchungsFehler(f"Vom Set {set_artikel['nummer']} ist kein Bestand vorhanden.")
    platz = " ".join((platz or "").split())
    if platz:
        am_platz = con.execute(select(bestand.c.menge).select_from(bestand.join(lagerplaetze, lagerplaetze.c.id == bestand.c.lagerplatz_id))
                               .where(bestand.c.artikel_id == sid, func.lower(lagerplaetze.c.code) == platz.lower())).scalar()
        if not am_platz or am_platz <= 0:
            raise BuchungsFehler(f"Auf {platz} liegt kein Set {set_artikel['nummer']}.")
    schon = float(con.execute(select(func.coalesce(func.sum(set_fehlteile.c.menge), 0)).where(
        set_fehlteile.c.set_id == sid, set_fehlteile.c.teil_id == t["id"], set_fehlteile.c.erledigt_am.is_(None))).scalar())
    moeglich = float(t["menge"]) * sets - schon
    if m > moeglich + 1e-9:
        raise BuchungsFehler(f"In den {fmt_num(sets)} Set(s) sind noch {fmt_num(max(moeglich, 0))} × {t['nummer']} – nicht {fmt_num(m)}.")
    jetzt = datetime.now().replace(microsecond=0)
    con.execute(insert(set_fehlteile).values(set_id=sid, teil_id=t["id"], teil_nr=t["nummer"], teil_bezeichnung=t["bezeichnung"], menge=m,
                                             lagerplatz=platz or None, empfaenger=(empfaenger or "").strip() or None,
                                             zweck=(zweck or "").strip() or None, entnommen_am=jetzt, entnommen_von=benutzer))
    audit(con, benutzer, "Teil aus Set entnommen", set_artikel["nummer"], {"teil": t["nummer"], "menge": m, "lagerplatz": platz or None,
                                                                         "empfaenger": empfaenger or None, "zweck": zweck or None})
    return (f"{fmt_num(m)} × {t['nummer']} aus Set {set_artikel['nummer']} entnommen. "
            f"Das Set ist jetzt unvollständig, bis das Teil nachgelegt wird.")


def fehlteil_erledigen(con: Connection, fid: int, art: str, benutzer: str, lager=None, platz: str = "") -> str:
    """Fehlteil erledigt: wieder hineingelegt (``nachgelegt``) oder aus dem Lagerbestand nachgelegt (``aus_lager``, bucht eine Entnahme)."""
    f = con.execute(select(set_fehlteile).where(set_fehlteile.c.id == fid)).mappings().first()
    if not f or f["erledigt_am"]:
        raise BuchungsFehler("Dieser Eintrag ist schon erledigt.")
    if art not in ERLEDIGT_TEXT:
        raise BuchungsFehler("Unbekannte Aktion.")
    set_nr = con.execute(select(artikel.c.nummer).where(artikel.c.id == f["set_id"])).scalar()
    text = ""
    if art == "aus_lager":
        if lager is None:
            raise BuchungsFehler("Buchung nicht möglich.")
        if not f["teil_id"]:
            raise BuchungsFehler("Das Teil gibt es nicht mehr als Artikel.")
        e = lager.ausgang(f["teil_id"], platz, f["menge"], zweck=f"In Set {set_nr} nachgelegt")
        text = f" Entnahme gebucht: {fmt_num(f['menge'])} × {f['teil_nr']} von {e.platz}."
    con.execute(update(set_fehlteile).where(set_fehlteile.c.id == fid).values(
        erledigt_am=datetime.now().replace(microsecond=0), erledigt_von=benutzer, erledigt_art=art))
    audit(con, benutzer, "Set-Fehlteil erledigt", set_nr, {"teil": f["teil_nr"], "menge": f["menge"], "wie": ERLEDIGT_TEXT[art]})
    return f"{f['teil_nr']} im Set {set_nr}: {ERLEDIGT_TEXT[art]}.{text}"


def nach_entnahme(con: Connection, set_id: int, benutzer: str, erledigt_ids: list[int] | None = None) -> str:
    """Nach einer Entnahme des Sets: markierte Fehlteile (dieses unvollständige Set wurde entnommen) schließen;
    ist kein Set mehr auf Lager, sind alle offenen Fehlteile gegenstandslos. Gibt die verbleibende Warnung zurück."""
    jetzt = datetime.now().replace(microsecond=0)
    offen = offene_fehlteile(con, set_id)
    for ids, art in (([f["id"] for f in offen if f["id"] in set(erledigt_ids or [])], "set_entnommen"),
                     ([f["id"] for f in offen] if _gesamt(con, set_id) <= 0 else [], "kein_bestand")):
        if ids:
            con.execute(update(set_fehlteile).where(and_(set_fehlteile.c.id.in_(ids), set_fehlteile.c.erledigt_am.is_(None)))
                        .values(erledigt_am=jetzt, erledigt_von=benutzer, erledigt_art=art))
    return warnung(offene_fehlteile(con, set_id))
