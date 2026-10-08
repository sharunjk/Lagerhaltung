"""Einmalige Datenübernahme aus der Casper-Lagerverwaltung.

Quelle: SQL-Export der MySQL-Datenbank ``daten`` aus HeidiSQL (Datei *.sql).
Es wird nur gelesen – die Casper-Datenbank selbst wird nie angefasst.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Connection

from ..db import (
    anhaenge, artikel, audit, bestand, bestellungen, bewegungen, inventur_pos, inventuren, lagerplaetze, lieferanten,
    reservierungen, users,
)
from .lager import parse_num

OHNE_PLATZ = "OHNE-PLATZ"


# ------------------------------------------------------------------ SQL-Dump lesen
def _werte_lesen(s: str, i: int) -> tuple[list, int]:
    """Liest ein Tupel ``( ... )`` ab Position i (zeigt auf '('). Gibt Werte und Position nach ')' zurück."""
    assert s[i] == "("
    i += 1
    werte = []
    n = len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n,":
            i += 1
            continue
        if c == ")":
            return werte, i + 1
        if c == "'":
            i += 1
            buf = []
            while i < n:
                c = s[i]
                if c == "\\" and i + 1 < n:
                    nx = s[i + 1]
                    buf.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}.get(nx, nx))
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and s[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            werte.append("".join(buf))
            continue
        m = re.compile(r"[^,)\s]+").match(s, i)
        tok = m.group(0)
        i = m.end()
        if tok.upper() == "NULL":
            werte.append(None)
        else:
            try:
                werte.append(int(tok))
            except ValueError:
                try:
                    werte.append(float(tok))
                except ValueError:
                    werte.append(tok)
    raise ValueError("Unerwartetes Dateiende im SQL-Export")


def dump_lesen(text: str) -> dict[str, list[dict]]:
    """Alle INSERT-Zeilen eines MySQL/HeidiSQL-Exports als {tabelle: [zeile, ...]}."""
    tabellen: dict[str, list[dict]] = defaultdict(list)
    pat = re.compile(r"INSERT INTO `?(\w+)`?\s*\(([^)]*)\)\s*VALUES\s*", re.I)
    pos = 0
    while True:
        m = pat.search(text, pos)
        if not m:
            break
        tab = m.group(1).lower()
        cols = [c.strip().strip("`") for c in m.group(2).split(",")]
        i = m.end()
        while True:
            while text[i] in " \t\r\n":
                i += 1
            werte, i = _werte_lesen(text, i)
            tabellen[tab].append(dict(zip(cols, werte)))
            while text[i] in " \t\r\n":
                i += 1
            if text[i] == ",":
                i += 1
                continue
            break
        pos = i
    return tabellen


# ------------------------------------------------------------------ Übernahme
@dataclass
class Bericht:
    artikel: int = 0
    lagerplaetze: int = 0
    bestandszeilen: int = 0
    gesamtbestand: float = 0
    bewegungen: int = 0
    lieferanten: int = 0
    benutzer: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


def _zeit(datum: str | None, zeit: str | None) -> datetime:
    try:
        return datetime.strptime(f"{(datum or '').strip()} {(zeit or '00:00:00').strip()}", "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return datetime(2000, 1, 1)


def _lieferant_key(name: str) -> str:
    return re.sub(r"[\s.\-_,]", "", name.lower())


def _typ(txt: str) -> str:
    for k, v in (("Eingang", "eingang"), ("Ausgang", "ausgang"), ("Umbuchung", "umbuchung"), ("Umlagerung", "umbuchung"),
                 ("Inventur", "inventur"), ("Neuer Artikel", "anlage")):
        if txt.startswith(k):
            return v
    return "info"


def _klammer(txt: str) -> str | None:
    """'Umbuchung (C2-R2-4)' -> 'C2-R2-4', 'Inventur (1 -> 2)' -> '1 -> 2'"""
    m = re.match(r"^[^(]*\((.*)\)\s*$", txt)
    inhalt = (m.group(1) if m else txt).strip()
    return f"Altsystem: {inhalt}" if inhalt else None


def hat_daten(con: Connection) -> bool:
    return bool(con.execute(select(func.count()).select_from(artikel)).scalar())


def alles_loeschen(con: Connection) -> None:
    for t in (inventur_pos, inventuren, reservierungen, bestellungen, anhaenge, bewegungen, bestand, artikel, lagerplaetze, lieferanten):
        con.execute(delete(t))


def uebernehmen(con: Connection, dump_text: str, benutzer: str = "Import") -> Bericht:
    daten = dump_lesen(dump_text)
    for pflicht in ("stammdaten", "lagerorte"):
        if pflicht not in daten:
            raise ValueError(f"Im Export fehlt die Tabelle „{pflicht}“. Bitte die komplette Datenbank „daten“ mit Daten exportieren.")
    rep = Bericht()

    # Lieferanten aus Freifeld1 (Schreibvarianten zusammenführen, häufigste Schreibweise gewinnt)
    namen = Counter((r.get("Freifeld1") or "").strip() for r in daten["stammdaten"])
    gruppen: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for n, c in namen.items():
        if n and n.lower() not in ("freifeld1", "-"):
            gruppen[_lieferant_key(n)].append((n, c))
    lief_id: dict[str, int] = {}
    for key, varianten in gruppen.items():
        name = max(varianten, key=lambda x: x[1])[0]
        lid = con.execute(insert(lieferanten).values(name=name)).inserted_primary_key[0]
        lief_id[key] = lid
        if len(varianten) > 1:
            rep.hinweise.append(f"Lieferant „{name}“ zusammengeführt aus: {', '.join(v for v, _ in varianten)}")
    rep.lieferanten = len(lief_id)

    # Artikel
    art_id: dict[str, int] = {}
    for r in daten["stammdaten"]:
        nr = str(r.get("Artikelnummer") or "").strip()
        if not nr or nr in art_id:
            continue
        notiz = []
        if (r.get("Freifeld4") or "").strip():
            notiz.append(f"Austragungsgrund: {r['Freifeld4'].strip()}")
        if (r.get("Freifeld5") or "").strip() and r["Freifeld5"].strip() != "Freifeld5":
            notiz.append(r["Freifeld5"].strip())
        melde, mindest = parse_num(r.get("Meldebestand")), parse_num(r.get("Mindestbestand"))
        f1 = (r.get("Freifeld1") or "").strip()
        aid = con.execute(insert(artikel).values(
            nummer=nr, bezeichnung=(r.get("Bezeichnung") or "").strip() or nr,
            kategorie=(r.get("Freifeld2") or "").strip() or None, typ=(r.get("Freifeld3") or "").strip() or None,
            lieferant_id=lief_id.get(_lieferant_key(f1)) if f1 else None,
            meldebestand=melde if melde else None, mindestbestand=mindest if mindest else None,
            notiz="\n".join(notiz) or None, einheit="Stk", aktiv=True, kritisch=False,
            erstellt_am=datetime.now(), geaendert_am=datetime.now())).inserted_primary_key[0]
        art_id[nr] = aid
    rep.artikel = len(art_id)

    # Lagerplätze und Bestände
    platz_id: dict[str, int] = {}

    def platz(code: str) -> int:
        code = " ".join((code or "").split()) or OHNE_PLATZ
        k = code.lower()
        if k not in platz_id:
            bereich = code.split("-")[0] if "-" in code and len(code) <= 12 else None
            platz_id[k] = con.execute(insert(lagerplaetze).values(
                code=code, bereich=bereich, aktiv=True,
                beschreibung="Bestand ohne Lagerplatz aus dem Altsystem" if code == OHNE_PLATZ else None)).inserted_primary_key[0]
        return platz_id[k]

    summen: dict[tuple[int, int], float] = defaultdict(float)
    verwaist = 0
    for r in daten["lagerorte"]:
        nr = str(r.get("Artikel") or "").strip()
        if nr not in art_id:
            verwaist += 1
            continue
        summen[(art_id[nr], platz(r.get("Lagerort")))] += float(r.get("Anzahl") or 0)
    for (aid, pid), m in summen.items():
        con.execute(insert(bestand).values(artikel_id=aid, lagerplatz_id=pid, menge=m))
        rep.gesamtbestand += m
        if m < 0:
            rep.hinweise.append(f"Negativer Bestand übernommen: Artikel-ID {aid}, Menge {m}")
    rep.lagerplaetze = len(platz_id)
    rep.bestandszeilen = len(summen)
    if verwaist:
        rep.hinweise.append(f"{verwaist} Lagerort-Zeile(n) gehörten zu nicht mehr vorhandenen Artikeln und wurden nicht übernommen.")
    if OHNE_PLATZ.lower() in platz_id:
        rep.hinweise.append(f"Bestand ohne Lagerplatzangabe liegt jetzt auf dem Platz {OHNE_PLATZ}. Bitte per Umbuchung einlagern.")
    codes = {r[0] for r in con.execute(select(lagerplaetze.c.code))}
    frei = sorted(c for c in codes if not re.fullmatch(r"[A-Za-z]\d+-([Rr]\d+-\d+|[Ff]\d+)", c) and c != OHNE_PLATZ)
    if frei:
        rep.hinweise.append("Lagerplätze außerhalb des Schemas (unter Lagerplätze prüfen oder zusammenführen): " + ", ".join(frei))

    # Bewegungshistorie
    zeilen = sorted(daten.get("bewegungsdaten", []), key=lambda r: r.get("Bewegungsdaten_ID") or r.get("ID") or 0)
    batch = []
    for r in zeilen:
        txt = (r.get("EingangAusgang") or "").strip()
        typ = _typ(txt)
        nr = str(r.get("Artikelnummer") or "").strip()
        code = " ".join((r.get("Lagerort") or "").split())
        menge = float(r.get("ISTBestand") or 0)
        batch.append(dict(
            zeit=_zeit(r.get("Datum"), r.get("Zeit")), artikel_id=art_id.get(nr), artikel_nr=nr,
            lagerplatz_id=platz_id.get(code.lower()) if code else None, lagerplatz=code or None, typ=typ,
            menge=0 if typ == "info" else menge, benutzer=r.get("Benutzer"), quelle="import",
            text=(f"{txt} (Bestand {menge:g})" if typ == "info" else (_klammer(txt) if typ in ("umbuchung", "inventur") else None)),
        ))
    if batch:
        con.execute(insert(bewegungen), batch)
    rep.bewegungen = len(batch)

    # Benutzer (ohne Passwort, inaktiv – Admin vergibt neue Passwörter)
    vorhanden = {r[0].lower() for r in con.execute(select(users.c.username))}
    for r in daten.get("benutzer", []):
        n = (r.get("benutzer") or "").strip()
        if n and n.lower() not in vorhanden:
            con.execute(insert(users).values(username=n, anzeigename=n, pw_hash=None, rolle="lager", aktiv=False))
            vorhanden.add(n.lower())
            rep.benutzer.append(n)

    con.execute(insert(audit).values(zeit=datetime.now(), benutzer=benutzer, aktion="Datenübernahme Casper", objekt="",
                                     details=f"{rep.artikel} Artikel, {rep.bestandszeilen} Bestandszeilen, {rep.bewegungen} Bewegungen"))
    return rep
