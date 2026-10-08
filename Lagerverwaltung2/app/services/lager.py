"""Buchungslogik. Alle Bestandsänderungen laufen hier durch – vom PC, vom Handscanner und über die API."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import artikel, audit as audit_t, bestand, bewegungen, lagerplaetze, reservierungen


class BuchungsFehler(ValueError):
    pass


MAX_MENGE = 1_000_000_000  # Schutz gegen Tippfehler/Fehlscans (z. B. Barcode statt Menge gescannt)


def fmt_num(v) -> str:
    if v is None or v == "":
        return ""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def parse_num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    # "nan", "inf", "1e999" sind für Python gültige Zahlen, aber keine Mengen
    return f if math.isfinite(f) else None


def audit(con: Connection, user: str, aktion: str, objekt: str, details: dict | None = None) -> None:
    con.execute(insert(audit_t).values(benutzer=user, aktion=aktion, objekt=objekt, zeit=datetime.now(),
                                       details=json.dumps(details, ensure_ascii=False, default=str) if details else None))


@dataclass
class Ergebnis:
    id: int
    artikel_nr: str
    platz: str
    menge: float
    bestand_nachher: float


class Lager:
    """Eine Instanz pro Transaktion: ``with db.schreiben() as con: Lager(con, "Sharun").ausgang(...)``"""

    def __init__(self, con: Connection, benutzer: str, quelle: str = "pc", negative_erlaubt: bool = False,
                 plaetze_anlegen: bool = True):
        self.con = con
        self.benutzer = benutzer
        self.quelle = quelle
        self.negative_erlaubt = negative_erlaubt
        self.plaetze_anlegen = plaetze_anlegen
        self.zeit = datetime.now().replace(microsecond=0)
        self.hinweis: str | None = None  # z. B. "offline erfasst 08.10. 08:41"
        self.ids: list[int] = []  # IDs der Bewegungen dieser Transaktion

    # ------------------------------------------------------------------ Nachschlagen
    def artikel(self, nr_oder_id) -> dict:
        q = select(artikel)
        q = q.where(artikel.c.id == nr_oder_id) if isinstance(nr_oder_id, int) else q.where(artikel.c.nummer == str(nr_oder_id).strip())
        a = self.con.execute(q).mappings().first()
        if not a:
            raise BuchungsFehler(f"Artikel {nr_oder_id} gibt es nicht.")
        if not a["aktiv"]:
            raise BuchungsFehler(f"Artikel {a['nummer']} ist archiviert.")
        return dict(a)

    def platz(self, code: str, anlegen: bool | None = None) -> dict:
        code = " ".join((code or "").split())
        if not code:
            raise BuchungsFehler("Bitte einen Lagerplatz angeben.")
        if len(code) > 60:
            raise BuchungsFehler("Lagerplatz-Code ist zu lang (max. 60 Zeichen).")
        p = self.con.execute(select(lagerplaetze).where(func.lower(lagerplaetze.c.code) == code.lower())).mappings().first()
        if p:
            return dict(p)
        if not (self.plaetze_anlegen if anlegen is None else anlegen):
            raise BuchungsFehler(f"Lagerplatz {code} gibt es nicht. Bitte zuerst unter Lagerplätze anlegen.")
        bereich = code.split("-")[0] if "-" in code else None
        pid = self.con.execute(insert(lagerplaetze).values(code=code, bereich=bereich, aktiv=True)).inserted_primary_key[0]
        return {"id": pid, "code": code, "bereich": bereich, "beschreibung": None, "aktiv": True}

    def menge_am_platz(self, artikel_id: int, platz_id: int) -> float | None:
        v = self.con.execute(select(bestand.c.menge).where(and_(bestand.c.artikel_id == artikel_id, bestand.c.lagerplatz_id == platz_id))).first()
        return None if v is None else float(v[0])

    def gesamt(self, artikel_id: int) -> float:
        return float(self.con.execute(select(func.coalesce(func.sum(bestand.c.menge), 0)).where(bestand.c.artikel_id == artikel_id)).scalar())

    def reserviert(self, artikel_id: int) -> float:
        return float(self.con.execute(select(func.coalesce(func.sum(reservierungen.c.menge), 0)).where(and_(
            reservierungen.c.artikel_id == artikel_id, reservierungen.c.status == "offen"))).scalar())

    # ------------------------------------------------------------------ Kern
    def _setzen(self, artikel_id: int, platz_id: int, neu: float, alt: float | None) -> None:
        if alt is None:
            self.con.execute(insert(bestand).values(artikel_id=artikel_id, lagerplatz_id=platz_id, menge=neu))
        else:
            self.con.execute(update(bestand).where(and_(bestand.c.artikel_id == artikel_id, bestand.c.lagerplatz_id == platz_id)).values(menge=neu))

    def _bewegung(self, a: dict, p: dict | None, typ: str, menge: float, nachher: float | None, **ext) -> Ergebnis:
        werte = dict(zeit=self.zeit, artikel_id=a["id"], artikel_nr=a["nummer"], lagerplatz_id=p["id"] if p else None,
                     lagerplatz=p["code"] if p else None, typ=typ, menge=menge, bestand_nachher=nachher,
                     benutzer=self.benutzer, quelle=self.quelle)
        werte.update({k: (v.strip() if isinstance(v, str) else v) or None for k, v in ext.items()})
        if self.hinweis:
            werte["text"] = f"{werte['text']}; {self.hinweis}" if werte.get("text") else self.hinweis
        bid = self.con.execute(insert(bewegungen).values(**werte)).inserted_primary_key[0]
        self.ids.append(bid)
        return Ergebnis(bid, a["nummer"], p["code"] if p else "", menge, nachher if nachher is not None else 0)

    @staticmethod
    def _menge(m) -> float:
        m = parse_num(m)
        if m is None or m <= 0:
            raise BuchungsFehler("Die Menge muss größer als 0 sein.")
        if m > MAX_MENGE:
            raise BuchungsFehler(f"Die Menge {fmt_num(m)} ist unplausibel groß (wurde ein Barcode ins Mengenfeld gescannt?).")
        return m

    def _abbuchen(self, a: dict, p: dict, menge: float) -> tuple[float, float]:
        alt = self.menge_am_platz(a["id"], p["id"])
        neu = (alt or 0) - menge
        if neu < -1e-9 and not self.negative_erlaubt:
            raise BuchungsFehler(f"Am Platz {p['code']} liegen nur {fmt_num(alt or 0)} {a['einheit']} von {a['nummer']}.")
        self._setzen(a["id"], p["id"], neu, alt)
        return alt or 0, neu

    def _zubuchen(self, a: dict, p: dict, menge: float) -> float:
        alt = self.menge_am_platz(a["id"], p["id"])
        neu = (alt or 0) + menge
        self._setzen(a["id"], p["id"], neu, alt)
        return neu

    # ------------------------------------------------------------------ Buchungen
    def eingang(self, nr, platz: str, menge, **ext) -> Ergebnis:
        a, p, m = self.artikel(nr), self.platz(platz), self._menge(menge)
        return self._bewegung(a, p, "eingang", m, self._zubuchen(a, p, m), **ext)

    def ausgang(self, nr, platz: str, menge, reservierung_id: int | None = None, **ext) -> Ergebnis:
        a, p, m = self.artikel(nr), self.platz(platz, anlegen=False), self._menge(menge)
        _, neu = self._abbuchen(a, p, m)
        if reservierung_id:
            self.con.execute(update(reservierungen).where(reservierungen.c.id == reservierung_id).values(status="entnommen"))
        return self._bewegung(a, p, "ausgang", -m, neu, **ext)

    def umbuchung(self, nr, von: str, nach: str, menge) -> tuple[Ergebnis, Ergebnis]:
        a, pv, m = self.artikel(nr), self.platz(von, anlegen=False), self._menge(menge)
        pn = self.platz(nach)
        if pv["id"] == pn["id"]:
            raise BuchungsFehler("Quell- und Zielplatz sind identisch.")
        _, neu_v = self._abbuchen(a, pv, m)
        neu_n = self._zubuchen(a, pn, m)
        e1 = self._bewegung(a, pv, "umbuchung", -m, neu_v, text=f"nach {pn['code']}")
        e2 = self._bewegung(a, pn, "umbuchung", m, neu_n, text=f"von {pv['code']}", bezug_id=e1.id)
        self.con.execute(update(bewegungen).where(bewegungen.c.id == e1.id).values(bezug_id=e2.id))
        return e1, e2

    def inventur(self, nr, platz: str, gezaehlt, **ext) -> Ergebnis | None:
        a, p = self.artikel(nr), self.platz(platz)
        ist = parse_num(gezaehlt)
        if ist is None or ist < 0:
            raise BuchungsFehler("Bitte den gezählten Bestand (0 oder mehr) eingeben.")
        if ist > MAX_MENGE:
            raise BuchungsFehler(f"Der gezählte Bestand {fmt_num(ist)} ist unplausibel groß.")
        alt = self.menge_am_platz(a["id"], p["id"])
        self._setzen(a["id"], p["id"], ist, alt)
        return self._bewegung(a, p, "inventur", ist - (alt or 0), ist, text=f"gezählt {fmt_num(ist)} (vorher {fmt_num(alt or 0)})", **ext)

    def ausleihe(self, nr, platz: str, menge, empfaenger: str, rueckgabe_bis: date | None = None, **ext) -> Ergebnis:
        if not (empfaenger or "").strip():
            raise BuchungsFehler("Bitte angeben, wer den Artikel ausleiht.")
        a, p, m = self.artikel(nr), self.platz(platz, anlegen=False), self._menge(menge)
        _, neu = self._abbuchen(a, p, m)
        return self._bewegung(a, p, "ausleihe", -m, neu, empfaenger=empfaenger, rueckgabe_bis=rueckgabe_bis, **ext)

    def rueckgabe(self, ausleihe_id: int, menge=None, platz: str | None = None) -> Ergebnis:
        aus = self.con.execute(select(bewegungen).where(and_(bewegungen.c.id == ausleihe_id, bewegungen.c.typ == "ausleihe"))).mappings().first()
        if not aus:
            raise BuchungsFehler("Ausleihe nicht gefunden.")
        zurueck = float(self.con.execute(select(func.coalesce(func.sum(bewegungen.c.menge), 0)).where(and_(
            bewegungen.c.typ == "rueckgabe", bewegungen.c.bezug_id == ausleihe_id))).scalar())
        offen = -float(aus["menge"]) - zurueck
        m = offen if menge in (None, "") else self._menge(menge)
        if m <= 0 or m > offen + 1e-9:
            raise BuchungsFehler(f"Es sind nur noch {fmt_num(offen)} offen.")
        a = self.artikel(aus["artikel_id"])
        p = self.platz(platz or aus["lagerplatz"])
        return self._bewegung(a, p, "rueckgabe", m, self._zubuchen(a, p, m), empfaenger=aus["empfaenger"], bezug_id=ausleihe_id)

    def storno(self, bewegung_id: int) -> Ergebnis:
        b = self.con.execute(select(bewegungen).where(bewegungen.c.id == bewegung_id)).mappings().first()
        if not b:
            raise BuchungsFehler("Buchung nicht gefunden.")
        if b["storniert_durch"]:
            raise BuchungsFehler("Diese Buchung wurde bereits storniert.")
        if b["storno_von"]:
            raise BuchungsFehler("Eine Stornobuchung kann nicht storniert werden.")
        if b["typ"] not in ("eingang", "ausgang") or not b["lagerplatz"] or not b["menge"] or not b["artikel_id"]:
            raise BuchungsFehler("Nur Eingänge und Entnahmen mit Lagerplatz können storniert werden. Sonst bitte Gegenbuchung oder Zählung.")
        a = self.artikel(b["artikel_id"])
        p = self.platz(b["lagerplatz"])
        m = float(b["menge"])
        if m > 0:
            _, neu = self._abbuchen(a, p, m)
            e = self._bewegung(a, p, "ausgang", -m, neu, storno_von=bewegung_id, text=f"Storno zu #{bewegung_id}")
        else:
            e = self._bewegung(a, p, "eingang", -m, self._zubuchen(a, p, -m), storno_von=bewegung_id, text=f"Storno zu #{bewegung_id}")
        self.con.execute(update(bewegungen).where(bewegungen.c.id == bewegung_id).values(storniert_durch=e.id))
        return e

    # ------------------------------------------------------------------ Artikel
    def artikel_anlegen(self, daten: dict, platz: str = "", anfangsbestand=0) -> dict:
        nr = (daten.get("nummer") or "").strip()
        if not nr:
            raise BuchungsFehler("Bitte eine Artikelnummer angeben.")
        if not (daten.get("bezeichnung") or "").strip():
            raise BuchungsFehler("Bitte eine Bezeichnung angeben.")
        if self.con.execute(select(artikel.c.id).where(artikel.c.nummer == nr)).first():
            raise BuchungsFehler(f"Artikelnummer {nr} ist bereits vergeben.")
        werte = {k: v for k, v in daten.items() if k in artikel.c and k not in ("id", "nummer", "erstellt_am", "geaendert_am")}
        werte.setdefault("einheit", "Stk")
        aid = self.con.execute(insert(artikel).values(nummer=nr, aktiv=True, erstellt_am=self.zeit, geaendert_am=self.zeit, **werte)).inserted_primary_key[0]
        a = self.artikel(aid)
        if str(anfangsbestand).strip() not in ("", "0") and parse_num(anfangsbestand) is None:
            raise BuchungsFehler(f"Anfangsbestand „{anfangsbestand}“ ist keine gültige Zahl.")
        m = parse_num(anfangsbestand) or 0
        if m < 0:
            raise BuchungsFehler("Anfangsbestand darf nicht negativ sein.")
        if m > MAX_MENGE:
            raise BuchungsFehler(f"Anfangsbestand {fmt_num(m)} ist unplausibel groß.")
        if platz and platz.strip():
            p = self.platz(platz)
            self._setzen(aid, p["id"], m, None)
            self._bewegung(a, p, "anlage", m, m, text="Artikel angelegt")
        elif m:
            raise BuchungsFehler("Für einen Anfangsbestand wird ein Lagerplatz benötigt.")
        else:
            self._bewegung(a, None, "anlage", 0, None, text="Artikel angelegt")
        audit(self.con, self.benutzer, "Artikel angelegt", nr, werte)
        return a

    def artikel_aendern(self, aid: int, daten: dict) -> None:
        alt = self.con.execute(select(artikel).where(artikel.c.id == aid)).mappings().first()
        if not alt:
            raise BuchungsFehler("Artikel nicht gefunden.")
        werte = {k: v for k, v in daten.items() if k in artikel.c and k not in ("id", "erstellt_am")}
        if "nummer" in werte:
            werte["nummer"] = (werte["nummer"] or "").strip()
            if not werte["nummer"]:
                raise BuchungsFehler("Bitte eine Artikelnummer angeben.")
            if werte["nummer"] != alt["nummer"] and self.con.execute(select(artikel.c.id).where(artikel.c.nummer == werte["nummer"])).first():
                raise BuchungsFehler(f"Artikelnummer {werte['nummer']} ist bereits vergeben.")
        geaendert = {k: v for k, v in werte.items() if alt[k] != v}
        if not geaendert:
            return
        self.con.execute(update(artikel).where(artikel.c.id == aid).values(geaendert_am=self.zeit, **geaendert))
        audit(self.con, self.benutzer, "Artikel geändert", alt["nummer"], {k: [alt[k], v] for k, v in geaendert.items()})

    def artikel_archivieren(self, aid: int, archiv: bool = True) -> None:
        a = self.con.execute(select(artikel).where(artikel.c.id == aid)).mappings().first()
        if not a:
            raise BuchungsFehler("Artikel nicht gefunden.")
        if archiv and self.gesamt(aid) > 0:
            raise BuchungsFehler("Artikel hat noch Bestand. Erst ausbuchen oder auf 0 zählen, dann archivieren.")
        self.con.execute(update(artikel).where(artikel.c.id == aid).values(aktiv=not archiv, geaendert_am=self.zeit))
        audit(self.con, self.benutzer, "Artikel archiviert" if archiv else "Artikel reaktiviert", a["nummer"])
