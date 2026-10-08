"""Unabhängige Soll-Werte aus dem HeidiSQL-Export (zeilenweise, ast.literal_eval statt des App-Parsers)."""
import ast, re, sys, collections, json
txt = open(sys.argv[1], encoding="utf-8").read()
rows = collections.defaultdict(list)
for m in re.finditer(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES\r?\n\t(\(.*\));\r?$", txt, re.M):
    cols = [c.strip(" `") for c in m.group(2).split(",")]
    lit = re.sub(r"\bNULL\b(?=(?:[^']*'[^']*')*[^']*$)", "None", m.group(3))
    rows[m.group(1)].append(dict(zip(cols, ast.literal_eval(lit))))
print({k: len(v) for k, v in rows.items()})
st = {r["Artikelnummer"].strip() for r in rows["stammdaten"]}
print("stammdaten distinct", len(st))
lo = rows["lagerorte"]
summe = sum(float(r["Anzahl"] or 0) for r in lo if str(r["Artikel"]).strip() in st)
print("Summe Bestand (Artikel in stammdaten):", summe, " gesamt:", sum(float(r["Anzahl"] or 0) for r in lo))
print("lagerorte zu fehlenden Artikeln:", sum(1 for r in lo if str(r["Artikel"]).strip() not in st))
leer = [r for r in lo if not (r["Lagerort"] or "").strip()]
print("leere Lagerorte:", len(leer), "Bestand:", sum(float(r["Anzahl"] or 0) for r in leer if r["Artikel"].strip() in st))
ws = sorted({r["Lagerort"] for r in lo if r["Lagerort"] and r["Lagerort"] != " ".join(r["Lagerort"].split())})
print("Lagerorte mit Rand-/Mehrfach-Leerzeichen:", len(ws))
d = collections.Counter((r["Artikel"].strip(), " ".join((r["Lagerort"] or "").split()).lower()) for r in lo)
print("doppelte (Artikel, Ort) Zeilen:", sum(1 for v in d.values() if v > 1))
print("negativ:", sum(1 for r in lo if float(r["Anzahl"] or 0) < 0))
md = collections.Counter((r["Meldebestand"], r["Mindestbestand"]) for r in rows["stammdaten"])
print("Melde/Mindest '0':", sum(1 for r in rows["stammdaten"] if r["Meldebestand"] == "0" or r["Mindestbestand"] == "0"),
      "nicht-numerisch:", sum(1 for r in rows["stammdaten"] for k in ("Meldebestand","Mindestbestand") if r[k] not in (None, "") and not re.fullmatch(r"-?\d+([.,]\d+)?", str(r[k]).strip())))
print("Umlaute in Bezeichnung:", sum(1 for r in rows["stammdaten"] if re.search("[äöüÄÖÜß]", r["Bezeichnung"] or "")),
      "Apostroph:", sum(1 for r in rows["stammdaten"] if "'" in (r["Bezeichnung"] or "") + (r["Freifeld3"] or "")))
plaetze = {" ".join((r["Lagerort"] or "").split()).lower() or "ohne-platz" for r in lo if r["Artikel"].strip() in st}
print("Plätze (case-insensitiv, nur aktive Artikel):", len(plaetze), " alle:", len({" ".join((r["Lagerort"] or "").split()).lower() or "ohne-platz" for r in lo}))
json.dump({"artikel": len(st), "summe": summe, "bewegungen": len(rows["bewegungsdaten"]), "lagerorte": len(lo)}, open(sys.argv[2], "w"))
