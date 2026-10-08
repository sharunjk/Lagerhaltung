"""Gemeinsame Web-Helfer: Templates, Login/Rollen, Meldungen, Filter."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .services.lager import fmt_num
from .services.queries import TYP_TEXT

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ROLLEN = {"lesen": 0, "lager": 1, "admin": 2}
ROLLEN_NAMEN = {"admin": "Administrator", "lager": "Lager", "lesen": "Nur lesen"}


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require(request: Request, rolle: str = "lesen") -> dict:
    u = current_user(request)
    if not u:
        raise LoginRequired()
    if ROLLEN.get(u["rolle"], 0) < ROLLEN[rolle]:
        raise Forbidden()
    return u


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
