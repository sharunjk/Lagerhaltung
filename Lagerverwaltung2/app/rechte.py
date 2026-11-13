"""Rollen und Rechte je Modul (ab 2.5.0).

Lager: weiter die Rolle in ``users.rolle`` (keine < lesen < lager < admin, siehe web.ROLLEN).
Instandhaltung (CMMS, Kürzel ``ih``): Rolle in ``benutzer_rollen``; was sie darf, steht hier als Liste von Rechten.
Jede Seite und jede Aktion prüft ihr Recht auf dem Server (``web.require_recht``) – ausgeblendete Knöpfe sind nur Komfort.
Lager-Administratoren sind Systemadministratoren und haben auch alle Rechte im CMMS.
"""
from __future__ import annotations

IH_ROLLEN = {
    "lesen": "Nur lesen",
    "operator": "Operator / Anlagenfahrer",
    "techniker": "Techniker",
    "schichtfuehrer": "Schichtführer / Betriebsleiter",
    "ingenieur": "Instandhaltungsingenieur / Planer",
    "manager": "Instandhaltungsmanager",
}

_PFLEGE = {"ingenieur", "manager"}
RECHTE: dict[str, set[str]] = {
    "ih.ansehen": set(IH_ROLLEN),                      # Anlagen, Dokumentation, Wartungsplan, Aufträge ansehen
    "ih.anlagen.pflegen": _PFLEGE,                     # Anlagen anlegen, ändern, archivieren
    "ih.import": _PFLEGE,                              # Asset-Liste importieren
    "ih.wartung.planen": _PFLEGE,                      # Instandhaltungsplan übernehmen, Kampagnen ändern, Aufträge anlegen/stornieren
    "ih.auftrag.freigeben": _PFLEGE,                   # Wartungsauftrag freigeben
    "ih.auftrag.ausfuehren": {"techniker", "schichtfuehrer", "ingenieur", "manager"},  # Protokolle erfassen, Nachweise hochladen
    "ih.auftrag.abschliessen": _PFLEGE,                # technisch erledigte Aufträge prüfen und abschließen (Vier-Augen-Prinzip)
    "ih.schichtbuch.ansehen": set(IH_ROLLEN),          # Schichtbuch, Übergaben und Meldungen lesen
    "ih.schichtbuch.schreiben": {"operator", "techniker", "schichtfuehrer", "ingenieur", "manager"},  # Meldungen, Schicht beginnen/übergeben
    "ih.schichtbuch.einrichten": {"schichtfuehrer", "manager"},  # Teams, Schichtzeiten, Ereignistypen, Zuordnung der Benutzer
    "ih.montage.ansehen": set(IH_ROLLEN),              # Stutzenübersicht und Montageprotokolle ansehen, drucken
    "ih.montage.erfassen": {"operator", "techniker", "schichtfuehrer", "ingenieur", "manager"},  # Protokolle anlegen, ausfüllen, abschließen
    "ih.montage.korrigieren": _PFLEGE,                 # abgeschlossene Protokolle nachträglich ändern (mit Grund, wird protokolliert)
    "ih.montage.stutzen": {"schichtfuehrer", "ingenieur", "manager"},  # Stutzenübersicht pflegen und importieren
}


def ih_aktiv(cfg) -> bool:
    return bool(getattr(getattr(cfg, "cmms", None), "aktiv", False))


def hat_recht(user: dict | None, recht: str, cfg) -> bool:
    if not user or not ih_aktiv(cfg) or recht not in RECHTE:
        return False
    if user.get("rolle") == "admin":
        return True
    return user.get("ih") in RECHTE[recht]


def bereiche(user: dict | None, cfg) -> list[str]:
    """Bereiche, die der Benutzer öffnen darf: 'lager' und/oder 'ih'."""
    if not user:
        return []
    b = [] if user.get("rolle") == "keine" else ["lager"]
    if hat_recht(user, "ih.ansehen", cfg):
        b.append("ih")
    return b
