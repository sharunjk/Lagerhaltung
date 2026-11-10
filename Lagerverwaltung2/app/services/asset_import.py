"""Asset-Import für die Instandhaltung: Excel/CSV (auch SharePoint-Listenexport) -> technische Plätze.

Ablauf: Datei lesen -> Spalten zuordnen -> prüfen (Plan) -> Testlauf (Transaktion wird zurückgerollt) -> Übernahme.
Grundsätze: Der Import löscht nie etwas. Schlüssel ist die Tag-Nr. (Code), nie die Zeilennummer. Es werden nur
zugeordnete Spalten geschrieben; leere Zellen überschreiben vorhandene Werte nur, wenn das ausdrücklich gewählt ist.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from ..db import ih_import_zeilen, ih_plaetze

MAX_DATEI = 10 * 1024 * 1024
MAX_ZEILEN = 20000
MAX_SPALTEN = 200


class ImportFehler(ValueError):
    pass


# ------------------------------------------------------------------ Zielfelder
# Schlüssel -> (Anzeige, Typ). Typ: text | datum | zahl | url | krit | mehrfach
FELDER: dict[str, tuple[str, str]] = {
    "code": ("Tag-Nr. / Code (Pflicht)", "text"),
    "bezeichnung": ("Bezeichnung", "text"),
    "kategorie": ("Kategorie", "text"),
    "kuerzel": ("Kürzel", "text"),
    "gruppe": ("Unit / Teilanlage (Ebene darüber)", "text"),
    "eltern_code": ("Übergeordneter Code", "text"),
    "bauteilklasse": ("Bauteilklasse", "text"),
    "sicherheitsgerichtet": ("PLT-Sicherheitseinrichtung (Ja/Nein)", "bool"),
    "hersteller": ("Hersteller", "text"),
    "modell": ("Modell / Typ", "text"),
    "seriennummer": ("Seriennummer", "text"),
    "lieferant": ("Lieferant", "text"),
    "kritikalitaet": ("Kritikalität (A/B/C)", "krit"),
    "status": ("Status", "text"),
    "inbetriebnahme": ("Inbetriebnahme (Datum)", "datum"),
    "anschaffung": ("Anschaffung (Datum)", "datum"),
    "bestellnummer": ("Bestellnummer", "text"),
    "leistungsnummer": ("Leistungsnummer", "text"),
    "kosten": ("Kosten Einkauf (€)", "zahl"),
    "nebenkosten": ("Nebenkosten Einkauf (€)", "zahl"),
    "doku_url": ("Link zur Dokumentation", "url"),
    "notiz": ("Notiz (mehrere Spalten möglich)", "mehrfach"),
    "zusatz": ("Zusatzfeld – unverändert übernehmen", "mehrfach"),
}
DB_FELDER = [f for f in FELDER if f not in ("code", "gruppe", "eltern_code", "zusatz")]
LAENGE = {"code": 120, "kuerzel": 30, "bezeichnung": 300, "doku_url": 1000}

SYNONYME = {
    "code": ["tagnr", "tag", "tagnummer", "kennzeichen", "equipmentnr", "equipmentnummer", "anlagennummer", "akz", "kks", "code",
             "technischerplatz", "assetid", "asset"],
    "bezeichnung": ["bezeichnung", "beschreibung", "description", "name", "title", "titel"],
    "kategorie": ["kategorie", "category", "anlagenklasse"],
    "kuerzel": ["kurzel", "kuerzel", "kurzzeichen"],
    "gruppe": ["unit", "teilanlage", "anlagenteil", "area", "bereich"],
    "eltern_code": ["functionallocation", "ubergeordnet", "uebergeordnet", "parent", "eltern", "oberesobjekt", "ubergeordneterplatz"],
    "bauteilklasse": ["bauteilklasse", "geraeteklasse", "gerateklasse", "equipmentklasse", "assetclass", "klasse"],
    "sicherheitsgerichtet": ["pltsicherheitseinrichtung", "sicherheitsgerichtet", "pltsicherheit", "sicherheitseinrichtung", "safety"],
    "hersteller": ["manufacturer", "hersteller"],
    "modell": ["model", "modell", "typ", "type", "typenbezeichnung"],
    "seriennummer": ["serialnumber", "seriennummer", "serial", "snr", "seriennr"],
    "lieferant": ["lieferant", "supplier", "vendor"],
    "kritikalitaet": ["criticality", "kritikalitat", "kritikalitaet", "abc"],
    "status": ["status"],
    "inbetriebnahme": ["comissioningdate", "commissioningdate", "inbetriebnahme", "inbetriebnahmedatum"],
    "anschaffung": ["datumderanschaffung", "anschaffung", "anschaffungsdatum", "kaufdatum", "purchasedate"],
    "bestellnummer": ["bestellnummer", "ordernumber", "bestellnr"],
    "leistungsnummer": ["leistungsnummer"],
    "kosten": ["kosteneinkauf", "kosten", "preis", "cost", "einkaufspreis"],
    "nebenkosten": ["nebenkosteneinkauf", "nebenkosten"],
    "doku_url": ["urldocumentation", "dokumentation", "doku", "link", "url", "dokulink"],
    "notiz": ["notes", "notiz", "kommentar", "bemerkung", "comment", "anmerkung"],
}


def _norm_kopf(s: str) -> str:
    s = s.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]", "", s)


def vorschlag(spalten: list[str], zeilen: list[list[str]]) -> list[str]:
    """Zuordnung vorschlagen: über den Spaltennamen; unbekannte, nicht leere Spalten -> Zusatzfeld."""
    belegt: set[str] = set()
    out = []
    for i, kopf in enumerate(spalten):
        k = _norm_kopf(kopf)
        ziel = ""
        for feld, namen in SYNONYME.items():
            if k in namen and (feld not in belegt or FELDER[feld][1] == "mehrfach"):
                ziel = feld
                break
        if not ziel and any((z[i] if i < len(z) else "").strip() for z in zeilen):
            ziel = "zusatz"
        if ziel:
            belegt.add(ziel)
        out.append(ziel)
    return out


# ------------------------------------------------------------------ Datei lesen
def _zelle(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        if not math.isfinite(v):
            return ""
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def lesen(dateiname: str, daten: bytes, blatt: str = "") -> tuple[list[str], list[list[str]]]:
    """Spaltenüberschriften und Zeilen (als Text) aus CSV oder Excel. Ohne Blattnamen wird bei Excel das Blatt
    genommen, das eine Spalte für die Tag-Nr. hat und die meisten Zeilen enthält (z. B. „Matrix“)."""
    info = lesen_mit_info(dateiname, daten, blatt)
    return info["spalten"], info["zeilen"]


def lesen_mit_info(dateiname: str, daten: bytes, blatt: str = "") -> dict:
    if not daten:
        raise ImportFehler("Die Datei ist leer.")
    if len(daten) > MAX_DATEI:
        raise ImportFehler("Die Datei ist größer als 10 MB.")
    name = (dateiname or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or daten[:2] == b"PK":
        blaetter = _excel_lesen(daten)
        if blatt:
            if blatt not in blaetter:
                raise ImportFehler(f"Tabellenblatt „{blatt}“ gibt es in der Datei nicht ({', '.join(blaetter)}).")
            gewaehlt = blatt
        else:
            def wertung(n):
                try:
                    sp, zl = _tabelle(blaetter[n])
                except ImportFehler:
                    return (0, 0)
                return (1 if "code" in vorschlag(sp, zl[:50]) else 0, len(zl))
            gewaehlt = max(blaetter, key=wertung)
        spalten, zeilen = _tabelle(blaetter[gewaehlt])
        return {"spalten": spalten, "zeilen": zeilen, "blatt": gewaehlt, "blaetter": list(blaetter)}
    if name.endswith((".csv", ".txt")) or not name:
        spalten, zeilen = _tabelle(_csv_lesen(daten))
        return {"spalten": spalten, "zeilen": zeilen, "blatt": None, "blaetter": []}
    raise ImportFehler("Bitte eine Excel-Datei (.xlsx) oder CSV-Datei (.csv) hochladen.")


def _tabelle(roh: list[list]) -> tuple[list[str], list[list[str]]]:
    roh = [[_zelle(c).strip() for c in z] for z in roh]
    kopf_i = next((i for i, z in enumerate(roh) if sum(1 for c in z if c) >= 2), None)
    if kopf_i is None:
        raise ImportFehler("Keine Spaltenüberschriften gefunden.")
    spalten = roh[kopf_i]
    while spalten and not spalten[-1]:
        spalten.pop()
    if len(spalten) > MAX_SPALTEN:
        raise ImportFehler(f"Zu viele Spalten (höchstens {MAX_SPALTEN}).")
    spalten = [s or f"Spalte {i + 1}" for i, s in enumerate(spalten)]
    zeilen = [(z + [""] * len(spalten))[:len(spalten)] for z in roh[kopf_i + 1:] if any(z)]
    if not zeilen:
        raise ImportFehler("Die Datei enthält keine Datenzeilen.")
    if len(zeilen) > MAX_ZEILEN:
        raise ImportFehler(f"Zu viele Zeilen ({len(zeilen)}, höchstens {MAX_ZEILEN}).")
    return spalten, zeilen


def _csv_lesen(daten: bytes) -> list[list]:
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            text = daten.decode(kodierung)
            break
        except UnicodeDecodeError:
            continue
    if text.startswith("ListSchema="):  # SharePoint-Listenexport: erste Zeile ist eine Schemabeschreibung
        text = text.split("\n", 1)[1] if "\n" in text else ""
    erste = next((z for z in text.splitlines() if z.strip()), "")
    trenner = max(";,\t", key=lambda t: erste.count(t)) if erste else ","
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=trenner))


def _excel_lesen(daten: bytes) -> dict[str, list[list]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(daten), read_only=True, data_only=True)
    except Exception as e:
        raise ImportFehler("Die Excel-Datei lässt sich nicht lesen.") from e
    try:
        return {ws.title: [list(z) for z in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()


# ------------------------------------------------------------------ Werte umwandeln
def code_norm(s: str) -> str:
    return " ".join((s or "").split())


def schluessel(code: str) -> str:
    """Vergleichsschlüssel: ohne Leerzeichen, Groß/Klein egal ('PI  3020 01-02' = 'pi 3020 01-02')."""
    return re.sub(r"\s+", "", code or "").casefold()


def _aehnlich(code: str) -> str:
    """Nur Buchstaben/Ziffern: findet 'E-10101' vs. 'E 10101' vs. 'E10101'."""
    return re.sub(r"[^0-9a-z]", "", (code or "").casefold())


_PLATZHALTER = re.compile(r"\?|(^|[\s-])xx($|[\s-])", re.IGNORECASE)
_TAG_ISA = re.compile(r"^[A-Za-z]{1,5}\s+(\d{4})\b")          # FIC 1040 01-01, VV 3010 05
_TAG_EQUIPMENT = re.compile(r"^[A-Za-z]{1,2}\s*-\s*(\d{4})\d")  # P -10401 A, E -10101, PM -10401 (nicht CAP01-…)


def unit_aus_tag(code: str) -> str | None:
    m = _TAG_ISA.match(code) or _TAG_EQUIPMENT.match(code)
    return m.group(1) if m else None


def zahl(s: str) -> float | None:
    """Deutsch und Englisch: '67.200' = 67200, '2.210,45' = 2210,45, '482,1' = 482,1, '19.5' = 19,5."""
    s = (s or "").replace("€", "").replace(" ", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        if s.count(",") > 1:
            raise ValueError(s)
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    f = float(s)
    if not math.isfinite(f):
        raise ValueError(s)
    return f


def _letzter_sonntag(jahr: int, monat: int) -> date:
    d = date(jahr, monat, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _berlin(dt_utc: datetime) -> datetime:
    """UTC -> deutsche Ortszeit (MEZ/MESZ) ohne Zeitzonen-Datenbank."""
    j = dt_utc.year
    sommer_ab = datetime.combine(_letzter_sonntag(j, 3), datetime.min.time()) + timedelta(hours=1)
    sommer_bis = datetime.combine(_letzter_sonntag(j, 10), datetime.min.time()) + timedelta(hours=1)
    naiv = dt_utc.replace(tzinfo=None)
    return naiv + timedelta(hours=2 if sommer_ab <= naiv < sommer_bis else 1)


def datum(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", s)
    if m:
        t, mo, j = (int(x) for x in m.groups())
        return date(j + 2000 if j < 100 else j, mo, t)
    if s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s):  # Zeitstempel mit Zeitzone (SharePoint: UTC)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return _berlin(dt - dt.utcoffset()).date()
    return datetime.fromisoformat(s).date() if "T" in s or " " in s else date.fromisoformat(s)


def kritikalitaet(s: str) -> str | None:
    s = (s or "").strip().upper()
    if not s:
        return None
    k = {"A": "A", "B": "B", "C": "C", "1": "A", "2": "B", "3": "C", "HOCH": "A", "MITTEL": "B", "NIEDRIG": "C", "GERING": "C"}.get(s)
    if not k:
        raise ValueError(s)
    return k


def ja_nein(s: str) -> bool | None:
    s = (s or "").strip().casefold()
    if not s:
        return None
    if s in ("ja", "j", "yes", "y", "wahr", "true", "x", "1"):
        return True
    if s in ("nein", "n", "no", "falsch", "false", "0", "-"):
        return False
    raise ValueError(s)


# ------------------------------------------------------------------ Optionen und Plan
@dataclass
class Optionen:
    bereiche_bilden: bool = True      # Unit 1040 -> Bereich 1000
    unit_aus_tag: bool = True         # leere Unit aus der Tag-Nr. ableiten (FIC 1040 01-01 -> 1040)
    leere_ueberschreiben: bool = False

    @classmethod
    def aus(cls, d: dict | None) -> "Optionen":
        d = d or {}
        return cls(**{k: bool(d[k]) for k in cls.__dataclass_fields__ if k in d})

    def als_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Zeile:
    nr: int
    code: str = ""
    ergebnis: str = "neu"                 # neu | geaendert | unveraendert | fehler
    meldungen: list = field(default_factory=list)  # [art, text], art: fehler | hinweis
    werte: dict = field(default_factory=dict)
    zusatz: dict = field(default_factory=dict)
    eltern: str | None = None             # Schlüssel des übergeordneten Platzes
    aenderungen: dict = field(default_factory=dict)
    vorhanden_id: int | None = None

    def fehler(self, text):
        self.meldungen.append(["fehler", text])
        self.ergebnis = "fehler"

    def hinweis(self, text):
        self.meldungen.append(["hinweis", text])


@dataclass
class Plan:
    zeilen: list[Zeile]
    gruppen: list[dict]                   # neu anzulegende Ebenen (Bereich, Unit), in Anlegereihenfolge
    zusammenfassung: dict


def zuordnung_pruefen(spalten: list[str], zuordnung: list[str]) -> None:
    if len(zuordnung) != len(spalten):
        raise ImportFehler("Zuordnung passt nicht zur Datei.")
    for z in zuordnung:
        if z and z not in FELDER:
            raise ImportFehler(f"Unbekanntes Feld „{z}“.")
    if zuordnung.count("code") != 1:
        raise ImportFehler("Bitte genau eine Spalte als „Tag-Nr. / Code“ zuordnen.")
    doppelt = [FELDER[f][0] for f in set(zuordnung) if f and FELDER[f][1] != "mehrfach" and zuordnung.count(f) > 1]
    if doppelt:
        raise ImportFehler(f"Diese Felder sind mehreren Spalten zugeordnet: {', '.join(sorted(doppelt))}.")


def _wandeln(feld: str, roh: str):
    typ = FELDER[feld][1]
    if typ == "zahl":
        return zahl(roh)
    if typ == "datum":
        return datum(roh)
    if typ == "krit":
        return kritikalitaet(roh)
    if typ == "bool":
        return ja_nein(roh)
    if typ == "url":
        if not re.match(r"^https?://", roh, re.IGNORECASE):  # nie javascript: o. Ä. als Link speichern
            raise ValueError(roh)
        return roh
    return roh


def planen(con: Connection, spalten: list[str], zuordnung: list[str], optionen: Optionen, zeilen: list[tuple[int, list[str]]]) -> Plan:
    """Was ein Import tun würde – ohne etwas zu schreiben."""
    zuordnung_pruefen(spalten, zuordnung)
    vorhanden = {r["schluessel"]: dict(r) for r in con.execute(select(ih_plaetze)).mappings()}
    aehnlich_db = {}
    for s, r in vorhanden.items():
        aehnlich_db.setdefault(_aehnlich(r["code"]), r["code"])
    ci = zuordnung.index("code")
    erg: list[Zeile] = []
    for nr, werte in zeilen:
        z = Zeile(nr=nr, code=code_norm(werte[ci]))
        erg.append(z)
        if not z.code:
            z.fehler("Tag-Nr. fehlt.")
            continue
        if len(z.code) > LAENGE["code"]:
            z.fehler(f"Tag-Nr. ist länger als {LAENGE['code']} Zeichen.")
            continue
        if _PLATZHALTER.search(z.code):
            z.hinweis("Tag-Nr. sieht nach einem Platzhalter aus (xx oder ?).")
        notizen = []
        for i, feld in enumerate(zuordnung):
            roh = (werte[i] if i < len(werte) else "").strip()
            if not feld or feld == "code":
                continue
            if feld == "zusatz":
                if roh:
                    z.zusatz[spalten[i]] = roh
                continue
            if feld == "notiz":
                if roh:
                    notizen.append(roh)
                continue
            if not roh:
                z.werte.setdefault(feld, None)
                continue
            try:
                wert = _wandeln(feld, roh)
            except (ValueError, TypeError):
                z.hinweis(f"{spalten[i]}: „{roh[:60]}“ ist kein gültiger Wert für {FELDER[feld][0]} – Feld übersprungen.")
                continue
            if isinstance(wert, str) and feld in LAENGE and len(wert) > LAENGE[feld]:
                wert = wert[:LAENGE[feld]]
                z.hinweis(f"{spalten[i]} gekürzt auf {LAENGE[feld]} Zeichen.")
            z.werte[feld] = wert
        if "notiz" in zuordnung:
            z.werte["notiz"] = "\n".join(notizen) or None

    # Doppelte Tag-Nummern in der Datei
    nach_schl: dict[str, list[Zeile]] = {}
    for z in erg:
        if z.code:
            nach_schl.setdefault(schluessel(z.code), []).append(z)
    for gleich in nach_schl.values():
        if len(gleich) > 1:
            nrs = ", ".join(str(g.nr) for g in gleich)
            for g in gleich:
                g.fehler(f"Tag-Nr. kommt mehrfach in der Datei vor (Zeilen {nrs}).")

    # Ähnliche Tag-Nummern (andere Schreibweise)
    aehnlich_datei: dict[str, list[Zeile]] = {}
    for z in erg:
        if z.code:
            aehnlich_datei.setdefault(_aehnlich(z.code), []).append(z)
    for z in erg:
        if not z.code or z.ergebnis == "fehler":
            continue
        a = _aehnlich(z.code)
        andere = {g.code for g in aehnlich_datei.get(a, []) if schluessel(g.code) != schluessel(z.code)}
        if a in aehnlich_db and schluessel(aehnlich_db[a]) != schluessel(z.code):
            andere.add(aehnlich_db[a])
        if andere:
            z.hinweis(f"Ähnliche Tag-Nr. vorhanden: {', '.join(sorted(andere))} – Schreibweise prüfen.")

    # Hierarchie: übergeordneter Code > Unit-Spalte > Unit aus Tag-Nr.
    gruppen: dict[str, dict] = {}
    gueltig = {schluessel(z.code) for z in erg if z.ergebnis != "fehler"}

    def gruppe_fuer(unit: str) -> str:
        unit = code_norm(unit)
        s = schluessel(unit)
        if optionen.bereiche_bilden and re.fullmatch(r"\d{4}", unit) and unit[1:] != "000":
            bereich = unit[0] + "000"
            bs = schluessel(bereich)
            if bs not in vorhanden and bs not in gruppen and bs not in gueltig:
                gruppen[bs] = {"code": bereich, "schluessel": bs, "art": "bereich", "bezeichnung": f"Bereich {bereich}", "eltern": None}
            eltern = bs
        else:
            eltern = None
        if s not in vorhanden and s not in gruppen and s not in gueltig:
            gruppen[s] = {"code": unit, "schluessel": s, "art": "unit", "bezeichnung": f"Unit {unit}", "eltern": eltern}
        return s

    for z in erg:
        if z.ergebnis == "fehler":
            continue
        eltern_code = code_norm(z.werte.pop("eltern_code", None) or "")
        unit = code_norm(z.werte.pop("gruppe", None) or "")
        aus_tag = unit_aus_tag(z.code) if optionen.unit_aus_tag or unit else None
        if unit and aus_tag and unit != aus_tag:
            z.hinweis(f"Unit {unit} passt nicht zur Tag-Nr. (dort {aus_tag}) – Unit aus der Spalte verwendet.")
        if eltern_code:
            es = schluessel(eltern_code)
            if es == schluessel(z.code):
                z.fehler("Übergeordneter Code ist die Anlage selbst.")
                continue
            if es in gueltig or es in vorhanden:
                z.eltern = es
                continue
            z.hinweis(f"Übergeordneter Code {eltern_code} nicht gefunden – stattdessen Unit verwendet.")
        if not unit and optionen.unit_aus_tag:
            unit = aus_tag or ""
        if unit:
            if schluessel(unit) == schluessel(z.code):
                continue
            z.eltern = gruppe_fuer(unit)
        else:
            z.hinweis("Keine Unit – wird auf oberster Ebene angelegt.")

    # Zyklen über "übergeordneter Code" (A unter B unter A)
    eltern_von = {schluessel(z.code): z.eltern for z in erg if z.ergebnis != "fehler"}
    for z in erg:
        if z.ergebnis == "fehler":
            continue
        gesehen, k = set(), schluessel(z.code)
        while k in eltern_von and eltern_von[k]:
            if k in gesehen:
                z.fehler("Zyklus in der Hierarchie (übergeordneter Code verweist im Kreis).")
                break
            gesehen.add(k)
            k = eltern_von[k]

    # Vergleich mit vorhandenen Anlagen
    for z in erg:
        if z.ergebnis == "fehler":
            continue
        alt = vorhanden.get(schluessel(z.code))
        if not alt:
            continue
        z.vorhanden_id = alt["id"]
        aend = {}
        for feld, neu in z.werte.items():
            if neu is None and not optionen.leere_ueberschreiben:
                continue
            a = alt.get(feld)
            if isinstance(a, float) and isinstance(neu, float) and math.isclose(a, neu):
                continue
            if (a if a not in ("",) else None) != neu:
                aend[feld] = [a, neu]
        if alt["code"] != z.code:
            aend["code"] = [alt["code"], z.code]
        alt_zusatz = json.loads(alt["zusatz"] or "{}")
        neu_zusatz = {**alt_zusatz, **z.zusatz}
        if neu_zusatz != alt_zusatz:
            aend["zusatz"] = [{k: alt_zusatz.get(k) for k in z.zusatz}, z.zusatz]
        alt_eltern = next((s for s, r in vorhanden.items() if r["id"] == alt["eltern_id"]), None) if alt["eltern_id"] else None
        if z.eltern and z.eltern != alt_eltern:
            aend["eltern"] = [alt_eltern, z.eltern]
        z.aenderungen = aend
        z.ergebnis = "geaendert" if aend else "unveraendert"

    zus = {k: sum(1 for z in erg if z.ergebnis == k) for k in ("neu", "geaendert", "unveraendert", "fehler")}
    zus["hinweise"] = sum(1 for z in erg if any(m[0] == "hinweis" for m in z.meldungen))
    zus["zeilen"] = len(erg)
    zus["gruppen"] = len(gruppen)
    zus["nicht_in_datei"] = len({k for k, r in vorhanden.items() if r["art"] == "platz"} - {schluessel(z.code) for z in erg if z.code})
    reihenfolge = sorted(gruppen.values(), key=lambda g: 0 if g["art"] == "bereich" else 1)
    return Plan(zeilen=erg, gruppen=reihenfolge, zusammenfassung=zus)


def _jsonfaehig(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def ausfuehren(con: Connection, plan: Plan, lauf_id: int) -> dict:
    """Plan in die Datenbank schreiben (innerhalb der Transaktion des Aufrufers)."""
    jetzt = datetime.now()
    ids = {r[0]: r[1] for r in con.execute(select(ih_plaetze.c.schluessel, ih_plaetze.c.id))}
    for g in plan.gruppen:
        ids[g["schluessel"]] = con.execute(insert(ih_plaetze).values(
            code=g["code"], schluessel=g["schluessel"], art=g["art"], bezeichnung=g["bezeichnung"], eltern_id=ids.get(g["eltern"]),
            aktiv=True, import_lauf_id=lauf_id, erstellt_am=jetzt, geaendert_am=jetzt)).inserted_primary_key[0]
    for z in plan.zeilen:
        s = schluessel(z.code)
        if z.ergebnis == "neu":
            felder = {k: v for k, v in z.werte.items() if k in DB_FELDER}
            ids[s] = con.execute(insert(ih_plaetze).values(
                code=z.code, schluessel=s, art="platz", aktiv=True, import_lauf_id=lauf_id, erstellt_am=jetzt, geaendert_am=jetzt,
                zusatz=json.dumps(z.zusatz, ensure_ascii=False) if z.zusatz else None, **felder)).inserted_primary_key[0]
        elif z.ergebnis == "geaendert":
            werte = {k: v[1] for k, v in z.aenderungen.items() if k in DB_FELDER or k == "code"}
            if "zusatz" in z.aenderungen:
                alt = json.loads(con.execute(select(ih_plaetze.c.zusatz).where(ih_plaetze.c.id == z.vorhanden_id)).scalar() or "{}")
                werte["zusatz"] = json.dumps({**alt, **z.zusatz}, ensure_ascii=False)
            con.execute(update(ih_plaetze).where(ih_plaetze.c.id == z.vorhanden_id).values(
                geaendert_am=jetzt, import_lauf_id=lauf_id, **werte))
    for z in plan.zeilen:  # Ebenen erst jetzt setzen: der übergeordnete Platz kann weiter unten in der Datei stehen
        if z.ergebnis in ("neu", "geaendert") and z.eltern:
            con.execute(update(ih_plaetze).where(ih_plaetze.c.schluessel == schluessel(z.code)).values(eltern_id=ids[z.eltern]))
    zeilen_ergebnis(con, plan, lauf_id)
    return dict(plan.zusammenfassung)


def zeilen_ergebnis(con: Connection, plan: Plan, lauf_id: int) -> None:
    nach_nr = {z.nr: z for z in plan.zeilen}
    for zid, nr in con.execute(select(ih_import_zeilen.c.id, ih_import_zeilen.c.nr).where(ih_import_zeilen.c.lauf_id == lauf_id)).all():
        z = nach_nr.get(nr)
        if z:
            con.execute(update(ih_import_zeilen).where(ih_import_zeilen.c.id == zid).values(
                ergebnis=z.ergebnis, meldungen=json.dumps(z.meldungen, ensure_ascii=False) if z.meldungen else None,
                aenderungen=json.dumps({k: [_jsonfaehig(a), _jsonfaehig(b)] for k, (a, b) in z.aenderungen.items()}, ensure_ascii=False,
                                       default=str) if z.aenderungen else None))


def kennung(zuordnung: list[str], optionen: Optionen, con: Connection, lauf_id: int) -> str:
    """Fingerabdruck aus Zuordnung, Optionen und Datenstand – die Übernahme gilt nur für genau das Geprüfte."""
    stand = con.execute(select(func.count(), func.max(ih_plaetze.c.geaendert_am), func.max(ih_plaetze.c.id))).one()
    return hashlib.sha256(json.dumps([zuordnung, optionen.als_dict(), lauf_id, [str(x) for x in stand]]).encode()).hexdigest()
