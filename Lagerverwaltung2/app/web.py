"""Gemeinsame Web-Helfer: Templates, Login/Rollen, Meldungen, Filter."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .services.lager import fmt_num
from .services.queries import TYP_TEXT

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ROLLEN = {"lesen": 0, "lager": 1, "admin": 2}
MIN_PASSWORT = 10  # Mindestlänge für neue Passwörter


def ist_lokal(request: Request) -> bool:
    """Anfrage kommt vom Lager-PC selbst (Browser auf diesem PC)."""
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


class Anmeldesperre:
    """Begrenzt Fehlversuche bei der Anmeldung (Schutz gegen Durchprobieren von Passwörtern im Firmennetz).

    Je Gerät (IP) und Benutzername höchstens ``JE_KONTO`` Fehlversuche, je Gerät insgesamt höchstens ``JE_GERAET``
    innerhalb von ``FENSTER`` Sekunden. Danach ist die Anmeldung bis zum Ablauf des Fensters gesperrt.
    Der Zustand liegt nur im Speicher – ein Neustart hebt Sperren auf.
    """
    JE_KONTO = 5
    JE_GERAET = 20
    FENSTER = 15 * 60

    def __init__(self):
        import threading
        from collections import defaultdict, deque
        self._fehl: dict[tuple, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _schluessel(self, ip: str, name: str):
        return (("konto", ip, name.strip().lower()), self.JE_KONTO), (("geraet", ip), self.JE_GERAET)

    def _aufraeumen(self, jetzt: float) -> None:
        for k in [k for k, q in self._fehl.items() if not q or q[-1] <= jetzt - self.FENSTER]:
            del self._fehl[k]

    def sperre_sekunden(self, ip: str, name: str) -> int:
        """0 = Anmeldung erlaubt, sonst verbleibende Sperrzeit in Sekunden."""
        import time
        jetzt = time.monotonic()
        with self._lock:
            rest = 0
            for k, grenze in self._schluessel(ip, name):
                q = self._fehl.get(k)
                while q and q[0] <= jetzt - self.FENSTER:
                    q.popleft()
                if q and len(q) >= grenze:
                    rest = max(rest, int(q[0] + self.FENSTER - jetzt) + 1)
            return rest

    def fehlschlag(self, ip: str, name: str) -> None:
        import time
        jetzt = time.monotonic()
        with self._lock:
            self._aufraeumen(jetzt)
            for k, _ in self._schluessel(ip, name):
                self._fehl[k].append(jetzt)

    def erfolg(self, ip: str, name: str) -> None:
        with self._lock:
            self._fehl.pop(self._schluessel(ip, name)[0][0], None)

ROLLEN_NAMEN = {"admin": "Administrator", "lager": "Lager", "lesen": "Nur lesen"}


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def pw_kennung(pw_hash: str | None) -> str:
    """Kurzer Fingerabdruck des Passwort-Hashes: ändert sich das Passwort, werden alte Sitzungen ungültig."""
    return hashlib.sha256((pw_hash or "").encode()).hexdigest()[:16]


def current_user(request: Request) -> dict | None:
    """Angemeldeter Benutzer – bei jedem Aufruf gegen die Datenbank geprüft.

    Die Sitzung liegt im Cookie (30 Tage). Ohne diese Prüfung würden deaktivierte Benutzer, entzogene Rollen
    und geänderte Passwörter erst nach dem Abmelden wirksam.
    """
    u = request.session.get("user")
    if not u:
        return None
    if "_geprueft" in request.scope:
        return request.scope["_geprueft"]
    from sqlalchemy import select

    from . import db
    from .db import users
    with db.engine().connect() as con:
        row = con.execute(select(users).where(users.c.id == u.get("id"))).mappings().first()
    if not row or not row["aktiv"] or not row["pw_hash"] or (u.get("pw") and u["pw"] != pw_kennung(row["pw_hash"])):
        request.session.pop("user", None)
        request.scope["_geprueft"] = None
        return None
    frisch = {"id": row["id"], "username": row["username"], "name": row["anzeigename"] or row["username"], "rolle": row["rolle"],
              "pw": pw_kennung(row["pw_hash"])}
    if frisch != u:
        request.session["user"] = frisch
    request.scope["_geprueft"] = frisch
    return frisch


def require(request: Request, rolle: str = "lesen") -> dict:
    u = current_user(request)
    if not u:
        raise LoginRequired()
    if ROLLEN.get(u["rolle"], 0) < ROLLEN[rolle]:
        raise Forbidden()
    return u


def sicheres_ziel(ziel: str | None, standard: str = "/") -> str:
    """Nur relative Ziele innerhalb der Lagerverwaltung zulassen (keine offene Weiterleitung über ``weiter``/Referer)."""
    ziel = (ziel or "").strip()
    if not ziel.startswith("/") or ziel.startswith("//") or "\\" in ziel or any(ord(c) < 32 for c in ziel):
        return standard
    teile = urlsplit(ziel)
    if teile.scheme or teile.netloc:
        return standard
    return ziel


def zurueck(request: Request, standard: str) -> str:
    """Rücksprung zur vorherigen Seite derselben Lagerverwaltung (Referer), sonst ``standard``."""
    ref = request.headers.get("referer") or ""
    teile = urlsplit(ref)
    if teile.netloc and teile.netloc != request.headers.get("host"):
        return standard
    return sicheres_ziel(teile.path + (f"?{teile.query}" if teile.query else ""), standard) if ref else standard


def flash(request: Request, text: str, art: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"text": text, "art": art})


def render(request: Request, name: str, **ctx):
    ctx.setdefault("user", current_user(request))
    ctx["flashes"] = request.session.pop("flash", [])
    ctx["request"] = request
    ctx["pfad"] = request.url.path
    ctx["cfg"] = request.app.state.cfg
    return templates.TemplateResponse(request, name, ctx)


def _num(v):
    if v is None or v == "":
        return "–"
    try:
        return fmt_num(v)
    except Exception:
        return str(v)


def _eur(v):
    if v is None or v == "":
        return "–"
    return f"{float(v):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _datum(v, mit_zeit=True):
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return v
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y %H:%M") if mit_zeit else v.strftime("%d.%m.%Y")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return "–"


_PLATZ = re.compile(r"^([A-Z]\d+-(R\d+-\d+|F\d+)|[A-ZÄÖÜ][a-zäöüß]+)$")
templates.env.tests["match_platz"] = lambda v: bool(_PLATZ.match(v or ""))
templates.env.filters.update(num=_num, eur=_eur, datum=_datum, typ_text=lambda t: TYP_TEXT.get(t, t or ""),
                             urlq=lambda s: quote(str(s or ""), safe=""))
def _qr(text: str) -> str:
    from .services.labels import qr_svg
    return qr_svg(text, 0, 0, 40)


templates.env.globals.update(qr=_qr, ROLLEN=ROLLEN, ROLLEN_NAMEN=ROLLEN_NAMEN, now=datetime.now, TYP_TEXT=TYP_TEXT)
