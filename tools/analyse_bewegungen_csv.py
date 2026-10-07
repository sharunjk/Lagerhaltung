"""Phase-0-Analyse des Casper-Exports SelektionBewegungsdaten.CSV.

Liest den Export (Latin-1, ';'-getrennt, ohne Kopfzeile, neueste Zeile zuerst)
und gibt die Kennzahlen aus, auf denen docs/legacy-analyse.md beruht.
Schreibt nichts, greift auf keine Datenbank zu.

Aufruf:  python tools/analyse_bewegungen_csv.py casper/Lagerverwaltung/Lagerverwaltung/SelektionBewegungsdaten.CSV
"""
import collections
import csv
import datetime
import re
import sys

BUCHUNGEN = ("Eingang", "Ausgang", "Umbuchung", "Umlagerung", "Inventur")
LAGERORT_SCHEMA = re.compile(r"^[A-Z]\d-(R\d-\d|F\d)$")


def art(aktion: str) -> str:
    return re.sub(r" \(.*\)$", "", aktion)


def zeitpunkt(r):
    return datetime.datetime.strptime(f"{r[5]} {r[6]}", "%d.%m.%Y %H:%M:%S")


def main(pfad: str) -> None:
    with open(pfad, encoding="latin-1", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    print(f"Zeilen: {len(rows)}, Spaltenanzahl: {collections.Counter(len(r) for r in rows)}")
    print(f"Zeitraum: {min(map(zeitpunkt, rows))} bis {max(map(zeitpunkt, rows))}")
    print(f"Benutzer: {dict(collections.Counter(r[4] for r in rows))}")

    print("\nAktionen (Anzahl, davon negativ, davon 0):")
    for k, n in collections.Counter(art(r[3]) for r in rows).most_common():
        q = [r[2] for r in rows if art(r[3]) == k]
        print(f"  {k:20} {n:5}  neg={sum(x.startswith('-') for x in q):4}  null={q.count('0'):4}")

    # Bestand rekonstruieren (chronologisch = Datei rückwärts, da neueste zuerst)
    bestand = collections.defaultdict(float)
    vergleich = collections.Counter()
    for r in reversed(rows):
        k, q = art(r[3]), float(r[2].replace(",", "."))
        if k in BUCHUNGEN:
            bestand[r[0]] += q
        elif k == "Neuer Artikel":
            bestand[r[0]] = q
        elif k in ("Artikel bearbeitet", "Artikel gelöscht"):
            vergleich[(k, abs(bestand[r[0]] - q) < 1e-9)] += 1
            bestand[r[0]] = q
    print("\nMenge bei Stammdaten-Aktionen == aus Deltas rekonstruierter Gesamtbestand?")
    for (k, gleich), n in sorted(vergleich.items()):
        print(f"  {k:20} {'gleich' if gleich else 'abweichend':10} {n}")

    print("\nUmbuchung/Umlagerung: Zeilen je (Artikel, Zeitstempel):")
    gruppen = collections.defaultdict(int)
    for r in rows:
        if art(r[3]) in ("Umbuchung", "Umlagerung"):
            gruppen[(art(r[3]), r[0], r[5], r[6])] += 1
    print(f"  {dict(collections.Counter((k[0], n) for k, n in gruppen.items()))}")

    print("\nReihenfolge-Sprünge (Zeile ist älter als die nachfolgende, d. h. später eingefügt):")
    for a, b in zip(rows, rows[1:]):
        if zeitpunkt(a) < zeitpunkt(b):
            print(f"  {a[0]} {a[3]!r} {a[5]} {a[6]}  vor  {b[0]} {b[3]!r} {b[5]} {b[6]}")

    orte = collections.Counter()
    for r in rows:
        if m := re.match(r"Umbuchung \((.*)\)$", r[3]):
            orte[m.group(1)] += 1
        if m := re.match(r"Umlagerung \((.*) -> (.*)\)$", r[3]):
            orte[m.group(1)] += 1
            orte[m.group(2)] += 1
    gut = {o: n for o, n in orte.items() if LAGERORT_SCHEMA.match(o)}
    schlecht = {o: n for o, n in orte.items() if not LAGERORT_SCHEMA.match(o)}
    print(f"\nLagerorte in Aktionstexten: {len(orte)} verschieden, {len(gut)} schemakonform")
    print(f"  Bereiche: {dict(collections.Counter(o.split('-')[0] for o in gut))}")
    print(f"  Abweichend: {schlecht}")

    neu = collections.Counter(r[0] for r in rows if r[3] == "Neuer Artikel")
    geloescht = collections.Counter(r[0] for r in rows if r[3] == "Artikel gelöscht")
    print(f"\nArtikelnummern: {len({r[0] for r in rows})} verschieden; "
          f"mehrfach 'Neuer Artikel': {sum(n > 1 for n in neu.values())}; "
          f"mit 'Artikel gelöscht': {len(geloescht)} (mehrfach: {sum(n > 1 for n in geloescht.values())})")
    print(f"  Nicht 5-stellig: {sorted({r[0] for r in rows if len(r[0]) != 5})}")


if __name__ == "__main__":
    main(sys.argv[1])
