"""Lagerverwaltung – eigenständige Webanwendung (FastAPI + SQLite)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .config import load_config
from .services.betrieb import Zeitplaner
from .web import Forbidden, LoginRequired, render

VERSION = "2.2.0"
log = logging.getLogger("lagerverwaltung")


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

    @app.middleware("http")
    async def same_origin_check(request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE") and not request.url.path.startswith("/api/"):
            src = request.headers.get("origin") or request.headers.get("referer")
            if src and urlparse(src).netloc != request.headers.get("host"):
                return PlainTextResponse("Anfrage von fremder Seite abgelehnt.", status_code=403)
        return await call_next(request)

    app.add_middleware(SessionMiddleware, secret_key=cfg.server.secret_key, session_cookie="lager_session",
                       max_age=60 * 60 * 24 * 30, same_site="lax")

    @app.exception_handler(LoginRequired)
    async def _login(request: Request, exc):
        if request.headers.get("hx-request"):
            return HTMLResponse("", headers={"HX-Redirect": "/login"})
        return RedirectResponse(f"/login?weiter={request.url.path}", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc):
        return render(request, "fehler.html", titel="Keine Berechtigung",
                      text="Für diese Aktion fehlt Ihrer Rolle die Berechtigung. Bitte wenden Sie sich an einen Administrator.")

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
    configs = [uvicorn.Config(app, host=cfg.server.host, port=int(cfg.server.port), log_level="warning")]
    if int(cfg.server.https_port or 0):
        try:
            from .services.zertifikat import sicherstellen
            cert, key = sicherstellen(cfg.path("daten"))
            configs.append(uvicorn.Config(app, host=cfg.server.host, port=int(cfg.server.https_port), log_level="warning",
                                          ssl_certfile=str(cert), ssl_keyfile=str(key), lifespan="off"))
        except Exception:  # pragma: no cover
            log.exception("HTTPS konnte nicht gestartet werden – Kamera-Scan am Handy nicht verfügbar")
    log.info("Lagerverwaltung %s: http://%s:%s%s", VERSION, cfg.server.host, cfg.server.port,
             f" und https://…:{cfg.server.https_port} (Handy/Kamera)" if len(configs) > 1 else "")

    async def main():
        await asyncio.gather(*(uvicorn.Server(c).serve() for c in configs))

    asyncio.run(main())


if __name__ == "__main__":
    run()
