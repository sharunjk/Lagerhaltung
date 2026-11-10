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
    "ih.ansehen": set(IH_ROLLEN),                      # Anlagen, Dokumentation, Historie ansehen
    "ih.anlagen.pflegen": _PFLEGE,                     # Anlagen anlegen und ändern
    "ih.import": _PFLEGE,                              # Asset-Liste importieren
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
