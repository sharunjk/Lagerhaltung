"""Schaufenster-Daten für Newsletter-Bilder: erfundene, realistische Ersatzteile (keine Echtdaten, keine Personennamen).

Aufruf: LV_HOME=<ordner> python showcase_seed.py <Programmordner>
"""
import os
import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, sys.argv[1])
home = os.environ["LV_HOME"]
from sqlalchemy import insert  # noqa: E402

from app import db  # noqa: E402
from app.db import bestellungen, lagerplaetze, lieferanten, reservierungen, users  # noqa: E402
from app.services.betrieb import hash_pw  # noqa: E402
from app.services.lager import Lager  # noqa: E402

random.seed(7)
db.init_engine(f"sqlite:///{home}/daten/lager.db")
PW = "Demo-Passwort-1"

with db.schreiben() as con:
    for u, name, rolle in (("admin", "Lager-Team", "admin"), ("werkstatt", "Werkstatt", "lager"), ("einkauf", "Einkauf", "lesen")):
        con.execute(insert(users).values(username=u, anzeigename=name, pw_hash=hash_pw(PW), rolle=rolle, aktiv=True))
    lf = {n: con.execute(insert(lieferanten).values(name=n)).inserted_primary_key[0]
          for n in ("Armaturen Nord GmbH", "Messtechnik Süd KG", "Antriebstechnik West", "Normteile Direkt")}

    def L(user="admin", tage=0, stunde=None):
        lg = Lager(con, user)
        t = datetime.now() - timedelta(days=tage)
        if stunde is not None:
            t = t.replace(hour=stunde, minute=random.randint(0, 59), second=0, microsecond=0)
        lg.zeit = t.replace(microsecond=0)
        return lg

    # (Nr, Bezeichnung, Gruppe, Lieferant, Platz, Anfangsbestand, Melde, Mindest, Preis, kritisch)
    teile = [
        ("10001", "Kugelhahn DN25 PN40, Edelstahl", "Armaturen", "Armaturen Nord GmbH", "C1-R1-1", 6, 2, 1, 89.0, False),
        ("10002", "Druckmessumformer 0–16 bar, 4–20 mA", "Messtechnik", "Messtechnik Süd KG", "C1-R1-2", 3, 3, 1, 245.0, True),
        ("10003", "Thermoelement Typ K, 300 mm", "Messtechnik", "Messtechnik Süd KG", "C1-R1-3", 5, 2, 1, 64.0, False),
        ("10004", "Magnetventil 24 V DC, 1/2\"", "Armaturen", "Armaturen Nord GmbH", "C1-R1-4", 4, 2, 1, 132.0, True),
        ("10005", "Sicherheitsventil 1/2\", 16 bar", "Armaturen", "Armaturen Nord GmbH", "C1-R2-1", 2, 1, 1, 178.0, True),
        ("10006", "Gleitringdichtung 35 mm", "Dichtungen", "Antriebstechnik West", "C1-R2-2", 4, 2, 1, 96.0, False),
        ("10007", "Rillenkugellager 6205-2RS", "Antrieb", "Antriebstechnik West", "C1-R3-1", 12, 6, 3, 14.5, False),
        ("10008", "Keilriemen SPZ 1250", "Antrieb", "Antriebstechnik West", "C1-R3-2", 4, 4, 2, 18.9, False),
        ("10009", "Hydraulik-Filterelement 10 µm", "Filter", "Antriebstechnik West", "C1-R3-3", 6, 3, 2, 42.0, False),
        ("10010", "Näherungsschalter M12, PNP", "Elektro", "Messtechnik Süd KG", "C1-R4-1", 8, 4, 2, 37.5, False),
        ("10011", "Schütz 24 V DC, 3 kW", "Elektro", "Messtechnik Süd KG", "C1-R4-2", 3, 2, 1, 58.0, False),
        ("10012", "Feinsicherung 10 A träge (10 Stk)", "Elektro", "Normteile Direkt", "C1-R4-3", 9, 3, 1, 6.9, False),
        ("10013", "Druckluftschlauch PU 8 × 6 mm, 25 m", "Pneumatik", "Normteile Direkt", "C1-F1", 3, 1, None, 39.0, False),
        ("10014", "Schmierfett Hochtemperatur 400 g", "Verbrauchsmaterial", "Normteile Direkt", "C2-R1-1", 10, 4, 2, 11.2, False),
        ("10015", "Kabelbinder 200 × 4,8 mm (100 Stk)", "Verbrauchsmaterial", "Normteile Direkt", "C2-R1-2", 14, 5, 2, 4.5, False),
        ("10016", "Kabelverschraubung M20, Messing", "Elektro", "Normteile Direkt", "C2-R1-3", 25, 10, 5, 3.8, False),
        ("10017", "Flanschdichtung DN50, PTFE", "Dichtungen", "Armaturen Nord GmbH", "C2-R2-1", 18, 10, 5, 7.4, False),
        ("10018", "Kupplungselement ROTEX 28", "Antrieb", "Antriebstechnik West", "C2-R2-2", 2, 2, 1, 21.0, False),
        ("10019", "Rückschlagventil DN15", "Armaturen", "Armaturen Nord GmbH", "C2-R2-3", 3, 1, None, 54.0, False),
        ("10020", "Pneumatikzylinder Ø32, Hub 100", "Pneumatik", "Normteile Direkt", "C2-R3-1", 2, 1, None, 118.0, False),
        ("10021", "Steckverbinder M12, 4-polig", "Elektro", "Messtechnik Süd KG", "C2-R3-2", 16, 6, 3, 8.6, False),
        ("10022", "Wartungseinheit G1/4", "Pneumatik", "Normteile Direkt", "C2-F1", 1, None, None, 96.0, False),
    ]
    for nr, bez, grp, lieferant, platz, m, melde, mindest, preis, krit in teile:
        L(tage=60).artikel_anlegen({"nummer": nr, "bezeichnung": bez, "kategorie": grp, "lieferant_id": lf[lieferant], "meldebestand": melde,
                                    "mindestbestand": mindest, "einheit": "Stk", "preis": preis, "kritisch": krit}, platz, m)

    # Leere Plätze (gestrichelt), damit die Regale vollständig sind
    for code in ("C1-R2-4", "C1-R4-4", "C2-R3-3", "C2-R3-4", "C2-R2-4"):
        L(tage=60).platz(code, anlegen=True)

    # Sichtlagerboxen in C1-R2-3
    L(tage=40).platz("C1-R2-3", anlegen=True)
    boxen = [("Zylinderschrauben M6 × 16", "20001", "Zylinderschraube DIN 912 M6 × 16 (100 Stk)", 6),
             ("Zylinderschrauben M8 × 20", "20002", "Zylinderschraube DIN 912 M8 × 20 (100 Stk)", 1),
             ("Sechskantmuttern M8", "20003", "Sechskantmutter DIN 934 M8 (100 Stk)", 5),
             ("Unterlegscheiben M8", "20004", "Unterlegscheibe DIN 125 M8 (100 Stk)", 7),
             ("O-Ringe NBR 20 × 2", "20005", "O-Ring NBR 70 20 × 2 (50 Stk)", 4),
             ("Sicherungsringe 20 mm", "20006", "Sicherungsring DIN 471 Ø20 (50 Stk)", 3),
             ("Splinte 3,2 × 32", "20007", "Splint DIN 94 3,2 × 32 (100 Stk)", 2),
             ("Gewindestifte M5", None, None, 0)]
    for i, (inhalt, nr, bez, menge) in enumerate(boxen, start=1):
        code = f"C1-R2-3-B{i}"
        con.execute(insert(lagerplaetze).values(code=code, bereich="C1", beschreibung=inhalt, aktiv=True))
        if nr:
            L(tage=40).artikel_anlegen({"nummer": nr, "bezeichnung": bez, "kategorie": "Normteile", "lieferant_id": lf["Normteile Direkt"],
                                        "meldebestand": 2 if nr == "20002" else 1, "einheit": "Pck", "preis": 9.5}, code, menge)

    # Buchungen der letzten Wochen (Werkstatt entnimmt, Lager bucht ein)
    entnahmen = [("10007", "C1-R3-1"), ("10017", "C2-R2-1"), ("10015", "C2-R1-2"), ("10010", "C1-R4-1"), ("10016", "C2-R1-3"),
                 ("10014", "C2-R1-1"), ("20001", "C1-R2-3-B1"), ("20003", "C1-R2-3-B3"), ("10021", "C2-R3-2"), ("10012", "C1-R4-3")]
    for tag in range(29, 0, -1):
        for _ in range(random.randint(1, 4)):
            nr, platz = random.choice(entnahmen)
            try:
                L("werkstatt", tag, random.randint(7, 15)).ausgang(nr, platz, 1, empfaenger="Werkstatt", kostenstelle="4711",
                                                                 zweck=random.choice(["Wartung Verdichter", "Störung Linie 2", "Revision Pumpe P3", ""]))
            except Exception:
                pass
        if tag % 6 == 0:
            for nr, platz in random.sample(entnahmen, 3):
                L("admin", tag, 10).eingang(nr, platz, random.randint(5, 10))
    # Bestand gezielt unter Melde-/Mindestbestand bringen (weinrote Plätze)
    L("werkstatt", 2, 9).ausgang("10002", "C1-R1-2", 2, empfaenger="Werkstatt", zweck="Austausch Druckmessung Kessel 2")
    L("werkstatt", 1, 13).ausgang("10008", "C1-R3-2", 2, empfaenger="Werkstatt", zweck="Störung Lüfter Halle 1")
    L("werkstatt", 1, 14).ausgang("10009", "C1-R3-3", 4, empfaenger="Werkstatt", zweck="Ölwechsel Presse")
    # heute
    L("werkstatt", 0, 8).ausgang("10007", "C1-R3-1", 2, empfaenger="Werkstatt", zweck="Lagertausch Förderband")
    L("admin", 0, 9).eingang("10017", "C2-R2-1", 20)
    L("werkstatt", 0, 10).ausgang("20004", "C1-R2-3-B4", 1, empfaenger="Werkstatt")
    L("werkstatt", 0, 10).umbuchung("10019", "C2-R2-3", "C2-R2-4", 1)
    L("admin", 0, 11).ausleihe("10022", "C2-F1", 1, "Instandhaltung Halle 2", date.today() + timedelta(days=5))
    con.execute(insert(reservierungen).values(artikel_id=5, menge=1, fuer="Revision Kessel 1", person="Werkstatt", status="offen", erstellt_von="admin"))
    con.execute(insert(bestellungen).values(artikel_id=2, menge=3, geliefert=0, lieferant_id=lf["Messtechnik Süd KG"], status="bestellt", erstellt_von="einkauf"))
print("Schaufenster-Daten angelegt in", home)
