"""Persönliche Einstellungen (ab 2.13.0): Startseite nach dem Anmelden und tätigkeitsbezogene Vorgaben je Benutzer.

Gespeichert in ``settings`` unter ``benutzer:<id>:<name>``. Standard-Startseiten je Rolle (z. B. Operator → Schichtbuch)
legen Instandhaltungsmanager und Administratoren fest (``startseite_rolle:<modul>:<rolle>``); eine eigene Wahl geht vor.
"""
from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.engine import Connection

from ..db import settings
from ..rechte import IH_ROLLEN, hat_recht
from .betrieb import get_setting, set_setting

# (Schlüssel, Pfad, Bezeichnung, Bedingung(user, cfg))
STARTSEITEN = [
    ("lager", "/", "Lager – Übersicht", lambda u, c: u.get("rolle") != "keine"),
    ("buchen", "/buchen", "Lager – Buchen", lambda u, c: u.get("rolle") in ("lager", "admin")),
    ("artikel", "/artikel", "Lager – Artikel", lambda u, c: u.get("rolle") != "keine"),
    ("scanner", "/m", "Scanner-Ansicht (Lager)", lambda u, c: u.get("rolle") != "keine"),
    ("ih", "/ih", "Instandhaltung – Übersicht", lambda u, c: hat_recht(u, "ih.ansehen", c)),
    ("schichtbuch", "/ih/schichtbuch", "Schichtbuch", lambda u, c: hat_recht(u, "ih.schichtbuch.ansehen", c)),
    ("aufgaben", "/ih/schichtbuch/aufgaben", "Schichtbuch – Aufgaben", lambda u, c: hat_recht(u, "ih.schichtbuch.ansehen", c)),
    ("schicht_neu", "/ih/schichtbuch/neu", "Schichtbuch – Neue Meldung", lambda u, c: hat_recht(u, "ih.schichtbuch.schreiben", c)),
    ("auftraege", "/ih/auftraege", "Wartungsaufträge", lambda u, c: hat_recht(u, "ih.ansehen", c)),
    ("wartung", "/ih/wartung", "Wartungsplan", lambda u, c: hat_recht(u, "ih.ansehen", c)),
    ("montage", "/ih/montage/protokolle", "Montageprotokolle", lambda u, c: hat_recht(u, "ih.montage.ansehen", c)),
    ("montage_neu", "/ih/montage/protokolle/neu", "Neues Montageprotokoll", lambda u, c: hat_recht(u, "ih.montage.erfassen", c)),
    ("ih_app", "/ih/m", "Instandhaltungs-App (Handy)", lambda u, c: hat_recht(u, "ih.ansehen", c)),
]
PFAD = {k: p for k, p, _, _ in STARTSEITEN}
BUCHUNGSARTEN = {"ausgang": "Entnahme", "eingang": "Eingang", "umbuchung": "Umbuchen", "inventur": "Zählen"}
LAGER_ROLLEN = {"lesen": "Lager: nur lesen", "lager": "Lager: buchen"}


def startseiten(user: dict, cfg) -> list[tuple[str, str]]:
    """Startseiten, die dieser Benutzer öffnen darf."""
    return [(k, lab) for k, _, lab, darf in STARTSEITEN if darf(user, cfg)]


def lesen(con: Connection, uid: int, name: str, standard: str | None = None) -> str | None:
    return get_setting(con, f"benutzer:{uid}:{name}", standard)


def schreiben(con: Connection, uid: int, name: str, wert: str | None) -> None:
    schluessel = f"benutzer:{uid}:{name}"
    if wert in (None, ""):
        con.execute(delete(settings).where(settings.c.schluessel == schluessel))
    else:
        set_setting(con, schluessel, str(wert))


def alle(con: Connection, uid: int) -> dict:
    return {n: lesen(con, uid, n) for n in ("startseite", "monteur_vorbelegen", "buchungsart")}


def rollen_standard(con: Connection) -> dict:
    """{"ih:operator": "schichtbuch", "lager:lager": "buchen", …}"""
    aus = {}
    for r in list(IH_ROLLEN):
        if w := get_setting(con, f"startseite_rolle:ih:{r}"):
            aus[f"ih:{r}"] = w
    for r in LAGER_ROLLEN:
        if w := get_setting(con, f"startseite_rolle:lager:{r}"):
            aus[f"lager:{r}"] = w
    return aus


def rollen_standard_setzen(con: Connection, werte: dict) -> None:
    for schluessel, wert in werte.items():
        modul, rolle = schluessel.split(":", 1)
        if (modul == "ih" and rolle not in IH_ROLLEN) or (modul == "lager" and rolle not in LAGER_ROLLEN):
            continue
        k = f"startseite_rolle:{modul}:{rolle}"
        if wert in PFAD:
            set_setting(con, k, wert)
        else:
            con.execute(delete(settings).where(settings.c.schluessel == k))


def startpfad(con: Connection, user: dict, cfg) -> str | None:
    """Gewählte Startseite (eigene Wahl, sonst Vorgabe der Rolle) – nur wenn der Benutzer sie öffnen darf."""
    erlaubt = {k for k, _ in startseiten(user, cfg)}
    kandidaten = [lesen(con, user["id"], "startseite")]
    if user.get("ih"):
        kandidaten.append(get_setting(con, f"startseite_rolle:ih:{user['ih']}"))
    if user.get("rolle") in LAGER_ROLLEN:
        kandidaten.append(get_setting(con, f"startseite_rolle:lager:{user['rolle']}"))
    for k in kandidaten:
        if k and k in erlaubt:
            return PFAD[k]
    return None


def darf_verwalten(user: dict | None, cfg) -> bool:
    """Admin oder Instandhaltungsmanager: volle Einstellungen bzw. Vorgaben für alle."""
    return bool(user) and (user.get("rolle") == "admin" or (user.get("ih") == "manager" and hat_recht(user, "ih.ansehen", cfg)))
