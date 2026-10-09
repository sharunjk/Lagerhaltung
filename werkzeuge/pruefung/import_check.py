import os, sys, json, random, ast, re, collections, tempfile
sys.path.insert(0, sys.argv[1])
tmp = tempfile.mkdtemp()
os.environ["LV_HOME"] = tmp
from app import db
from app.services import casper_import
from sqlalchemy import text
db.init_engine(f"sqlite:///{tmp}/lager.db")
dump = open(sys.argv[2], encoding="utf-8").read()
with db.schreiben() as con:
    rep = casper_import.uebernehmen(con, dump, "pruefung")
soll = json.load(open(sys.argv[3]))
with db.engine().connect() as con:
    n_art = con.execute(text("select count(*) from artikel")).scalar()
    summe = con.execute(text("select sum(menge) from bestand")).scalar()
    n_bew = con.execute(text("select count(*) from bewegungen")).scalar()
    n_pl = con.execute(text("select count(*) from lagerplaetze")).scalar()
    print(f"Artikel {n_art} (Soll {soll['artikel']}), Bestand {summe} (Soll {soll['summe']}), Bewegungen {n_bew} (Soll {soll['bewegungen']}), Plätze {n_pl}")
    print("Bericht:", {k: v for k, v in rep.__dict__.items() if k != 'hinweise'})
    print("Hinweise:", len(rep.hinweise), "Zeichen:", sum(len(h) for h in rep.hinweise))
    for h in rep.hinweise: print("  -", h[:160])
    # session size estimate
    import base64
    from itsdangerous import TimestampSigner
    data = base64.b64encode(json.dumps({"user": {"id": 1, "username": "admin", "name": "Admin", "rolle": "admin"}, "uebernahme": rep.__dict__, "flash": [{"text": "Übernommen: ...", "art": "ok"}]}).encode())
    print("Session-Cookie ca. Bytes:", len(TimestampSigner("x"*64).sign(data)))
    # Stichproben gegen Export
    rows = collections.defaultdict(list)
    for m in re.finditer(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES\r?\n\t(\(.*\));\r?$", dump, re.M):
        cols = [c.strip(" `") for c in m.group(2).split(",")]
        lit = re.sub(r"\bNULL\b(?=(?:[^']*'[^']*')*[^']*$)", "None", m.group(3))
        rows[m.group(1)].append(dict(zip(cols, ast.literal_eval(lit))))
    random.seed(int(sys.argv[4]) if len(sys.argv) > 4 else 7)
    fehler = 0
    for r in random.sample(rows["stammdaten"], 10) + [r for r in rows["stammdaten"] if re.search("[äöüß]", r["Bezeichnung"] or "")][:3]:
        nr = r["Artikelnummer"].strip()
        a = con.execute(text("select a.*, l.name lief from artikel a left join lieferanten l on l.id=a.lieferant_id where nummer=:n"), {"n": nr}).mappings().first()
        soll_orte = collections.defaultdict(float)
        for lo in rows["lagerorte"]:
            if lo["Artikel"].strip() == nr:
                soll_orte[" ".join((lo["Lagerort"] or "").split()) or "OHNE-PLATZ"] += float(lo["Anzahl"] or 0)
        ist_orte = {c: m for c, m in con.execute(text("select p.code, b.menge from bestand b join lagerplaetze p on p.id=b.lagerplatz_id where b.artikel_id=:i"), {"i": a["id"]})}
        ok = (a["bezeichnung"] == ((r["Bezeichnung"] or "").strip() or nr) and (a["kategorie"] or "") == (r["Freifeld2"] or "").strip()
              and (a["typ"] or "") == (r["Freifeld3"] or "").strip() and {k.lower(): v for k, v in ist_orte.items()} == {k.lower(): v for k, v in soll_orte.items()})
        lief_ok = (r["Freifeld1"] or "").strip().lower().replace(" ", "") [:3] == (a["lief"] or "").lower().replace(" ", "")[:3] if (r["Freifeld1"] or "").strip() not in ("", "-") else a["lief"] is None
        fehler += not (ok and lief_ok)
        print(f"  {nr}: {'OK ' if ok and lief_ok else 'ABW'} | {a['bezeichnung'][:30]!r} | Lief {r['Freifeld1']!r}->{a['lief']!r} | Gruppe {a['kategorie']!r} | Orte {dict(ist_orte)} soll {dict(soll_orte)}")
    print("Stichproben-Abweichungen:", fehler)
