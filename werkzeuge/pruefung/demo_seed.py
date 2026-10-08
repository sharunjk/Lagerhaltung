"""Legt in LV_HOME eine Demo-Datenbank mit erfundenen Daten an (keine Echtdaten) – für Oberflächen- und Browsertests."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, sys.argv[1])
home = os.environ["LV_HOME"]
from sqlalchemy import insert  # noqa: E402

from app import db  # noqa: E402
from app.db import bestellungen, inventuren, lieferanten, reservierungen, users  # noqa: E402
from app.services.betrieb import hash_pw  # noqa: E402
from app.services.lager import Lager  # noqa: E402

db.init_engine(f"sqlite:///{home}/daten/lager.db")
with db.schreiben() as con:
    for r in ("admin", "lager", "lesen"):
        con.execute(insert(users).values(username=r, anzeigename=r.capitalize() + " Demo", pw_hash=hash_pw("Demo-Passwort-1"), rolle=r, aktiv=True,
                                         api_token=f"tok_{r}"))
    l1 = con.execute(insert(lieferanten).values(name="Muster Armaturen GmbH", email="einkauf@example.org")).inserted_primary_key[0]
    l2 = con.execute(insert(lieferanten).values(name="Prüftechnik Süd")).inserted_primary_key[0]
    L = Lager(con, "admin")
    teile = [
        ("10001", "Kugelhahn DN15 PN40", "Kugelhahn", l1, "C1-R1-1", 4, 2, 1),
        ("10002", "Druckmessumformer 0–10 bar", "Druckmessung", l2, "C1-R1-2", 1, 2, 1),
        ("10003", "Dichtung Flansch DN50 (PTFE)", "Dichtung", l1, "C1-R2-1", 25, 10, 5),
        ("10004", "Thermoelement Typ K, 300 mm", "Temperaturmessung", l2, "C2-R3-4", 0, 1, 1),
        ("10005", "Schmierfett „Hochtemperatur“ 400 g", "Verbrauchsmaterial", None, "B0-R1-2", 6, 3, None),
        ("10006", "Magnetventil 24 V DC, Messing", "Magnetventil", l1, "C2-F1", 2, None, None),
        ("10007", "Sicherheitsventil 1/2\" 16 bar", "Sicherheitsventil", l1, "C2-R8-1", 1, 1, 1),
        ("10008", "Kabelbinder 200 × 4,8 mm, schwarz (100 Stk)", "Verbrauchsmaterial", None, "B0-R2-0", 12, 5, 2),
    ]
    for nr, bez, kat, lid, platz, m, melde, mindest in teile:
        L.artikel_anlegen({"nummer": nr, "bezeichnung": bez, "kategorie": kat, "lieferant_id": lid, "meldebestand": melde,
                           "mindestbestand": mindest, "einheit": "Stk", "preis": 12.5, "kritisch": nr in ("10002", "10007")}, platz, m)
    for i in range(9, 40):
        L.artikel_anlegen({"nummer": str(10000 + i), "bezeichnung": f"Ersatzteil Muster {i}", "kategorie": "Sonstiges"}, f"C2-R{i % 9 + 1}-{i % 5}", i % 4)
    L.ausgang("10003", "C1-R2-1", 3, empfaenger="Werkstatt", kostenstelle="4711", zweck="Wartung Verdichter")
    L.eingang("10003", "C1-R2-1", 10)
    L.umbuchung("10001", "C1-R1-1", "C1-R1-3", 1)
    L.inventur("10006", "C2-F1", 3)
    L.ausleihe("10008", "B0-R2-0", 2, "Max Muster", date.today() + timedelta(days=7))
    con.execute(insert(reservierungen).values(artikel_id=1, menge=1, fuer="Revision Anlage 3", person="Werkstatt", status="offen", erstellt_von="admin"))
    con.execute(insert(bestellungen).values(artikel_id=2, menge=3, geliefert=0, lieferant_id=l2, status="bestellt", erstellt_von="admin"))
    con.execute(insert(inventuren).values(name="Inventur Demo C1", bereich="C1", status="offen", erstellt_von="admin"))
print("Demo-Daten angelegt in", home)
