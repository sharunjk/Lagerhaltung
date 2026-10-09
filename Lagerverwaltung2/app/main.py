"""Lagerverwaltung – eigenständige Webanwendung (FastAPI + SQLite)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .config import load_config
from .services.betrieb import Zeitplaner
from .web import Anmeldesperre, Forbidden, LoginRequired, render

VERSION = "2.3.1"
log = logging.getLogger("lagerverwaltung")


class SitzungJeProtokoll:
    """Sitzungs-Cookie über HTTPS nur verschlüsselt (``Secure``), über HTTP (nur localhost) ohne – sonst ginge die
    Anmeldung im Browser am Lager-PC (http://localhost:8080) nicht."""

    def __init__(self, app, **kw):
        self.http = SessionMiddleware(app, https_only=False, **kw)
        self.https = SessionMiddleware(app, https_only=True, **kw)

    async def __call__(self, scope, receive, send):
        await (self.https if scope.get("scheme") in ("https", "wss") else self.http)(scope, receive, send)


def static_version() -> str:
    """Versionskennung für CSS/JS-Adressen (``?v=…``) und den Cache der Scanner-App: Versionsnummer plus Prüfsumme der
    Dateien. Ändert sich eine Datei, holen Browser und Service Worker sie neu – auch bei gleicher Versionsnummer."""
    import hashlib
    h = hashlib.sha256()
    st = Path(__file__).parent / "static"
    for f in ("app.css", "js/scan.js", "js/offline.js"):
        try:
            h.update((st / f).read_bytes())
        except OSError:
            pass
    return f"{VERSION}-{h.hexdigest()[:8]}"


def server_plan(cfg, https_bereit: bool) -> list[dict]:
    """Welche Server auf welcher Adresse lauschen. HTTP nur auf 127.0.0.1, wenn HTTPS läuft und ``http_nur_lokal`` gesetzt ist."""
    https = bool(int(cfg.server.https_port or 0)) and https_bereit
    http_host = "127.0.0.1" if (https and cfg.server.http_nur_lokal) else cfg.server.host
    plan = [{"host": http_host, "port": int(cfg.server.port), "ssl": False}]
    if https:
        plan.append({"host": cfg.server.host, "port": int(cfg.server.https_port), "ssl": True})
    return plan


def create_app(cfg=None, start_scheduler: bool = True) -> FastAPI:
    cfg = cfg or load_config()
    db.init_engine(cfg.db_url)
    cfg.path(cfg.daten.anhaenge).mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        planer = None
        if start_scheduler:
            planer = Zeitplaner(db.engine(), lambda: app.state.cfg)
            planer.start()
        yield
        if planer:
            planer.stop_event.set()

    app = FastAPI(title="Lagerverwaltung", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.cfg = cfg
    app.state.version = VERSION
    app.state.static_v = static_version()
    app.state.anmeldesperre = Anmeldesperre()

    @app.middleware("http")
    async def same_origin_check(request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE") and not request.url.path.startswith("/api/"):
            src = request.headers.get("origin") or request.headers.get("referer")
            if src and urlparse(src).netloc != request.headers.get("host"):
                return PlainTextResponse("Anfrage von fremder Seite abgelehnt.", status_code=403)
        return await call_next(request)

    app.add_middleware(SitzungJeProtokoll, secret_key=cfg.server.secret_key, session_cookie="lager_session",
                       max_age=60 * 60 * 24 * 30, same_site="lax")

    @app.exception_handler(LoginRequired)
    async def _login(request: Request, exc):
        if request.headers.get("hx-request"):
            return HTMLResponse("", headers={"HX-Redirect": "/login"})
        ziel = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        anmelden = "/m/login" if request.url.path.startswith("/m/") or request.url.path == "/m" else "/login"
        return RedirectResponse(f"{anmelden}?weiter={quote(ziel, safe='')}", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc):
        antwort = render(request, "fehler.html", titel="Keine Berechtigung",
                         text="Für diese Aktion fehlt Ihrer Rolle die Berechtigung. Bitte wenden Sie sich an einen Administrator.")
        antwort.status_code = 403
        return antwort

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    from .routes import admin, api, artikel, buchen, core, lager, mobil
    for r in (core.router, artikel.router, buchen.router, lager.router, admin.router, mobil.router, api.router):
        app.include_router(r)
    return app


def run() -> None:
    import asyncio
    import sys

    import uvicorn
    from logging.handlers import RotatingFileHandler

    from .config import BASE_DIR
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # Start ohne Konsole (pythonw.exe / Autostart)
        sys.stdout = sys.stderr = open(BASE_DIR / "logs" / "konsole.log", "a", encoding="utf-8", buffering=1)
    datei = RotatingFileHandler(BASE_DIR / "logs" / "lagerverwaltung.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stderr), datei])
    cfg = load_config()
    app = create_app(cfg)
    cert = key = None
    if int(cfg.server.https_port or 0):
        try:
            from .services.zertifikat import sicherstellen
            cert, key = sicherstellen(cfg.path("daten"))
        except Exception:  # pragma: no cover
            log.exception("HTTPS konnte nicht gestartet werden – Handscanner und andere PCs erreichen die Lagerverwaltung nicht")
    configs = []
    for s in server_plan(cfg, cert is not None):
        extra = dict(ssl_certfile=str(cert), ssl_keyfile=str(key), lifespan="off") if s["ssl"] else {}
        configs.append(uvicorn.Config(app, host=s["host"], port=s["port"], log_level="warning", **extra))
        log.info("Lagerverwaltung %s: %s://%s:%s", VERSION, "https" if s["ssl"] else "http", s["host"], s["port"])
    if cfg.server.http_nur_lokal and cert is None and cfg.server.host not in ("127.0.0.1", "localhost"):
        log.warning("HTTPS ist aus – HTTP ist deshalb im Netz erreichbar und unverschlüsselt (Passwörter im Klartext).")

    async def main():
        await asyncio.gather(*(uvicorn.Server(c).serve() for c in configs))

    asyncio.run(main())


if __name__ == "__main__":
    run()
