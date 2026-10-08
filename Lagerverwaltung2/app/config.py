"""Konfiguration aus config.toml (im Programmordner). Alles Wichtige ist auch in der Oberfläche einstellbar."""
from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(os.environ.get("LV_HOME", Path(__file__).resolve().parent.parent))
CONFIG_PATH = Path(os.environ.get("LV_CONFIG", BASE_DIR / "config.toml"))


@dataclass
class ServerCfg:
    host: str = "0.0.0.0"
    port: int = 8080
    https_port: int = 8443  # für Kamera-Scan am Smartphone (Browser verlangt HTTPS); 0 = aus
    secret_key: str = ""
    firmenname: str = "CAPHENIA"


@dataclass
class DatenCfg:
    datenbank: str = "daten/lager.db"  # SQLite-Datei
    anhaenge: str = "daten/anhaenge"


@dataclass
class LagerCfg:
    negative_bestaende_erlauben: bool = False
    lagerplaetze_automatisch_anlegen: bool = True  # unbekannte Platz-Codes beim Buchen anlegen
    live_abfrage_sekunden: int = 10
    standard_einheit: str = "Stk"


@dataclass
class DruckerCfg:
    modus: str = "windows"  # windows | netzwerk | datei
    name: str = "HPRT HT100"
    host: str = ""
    port: int = 9100
    datei_ordner: str = "druckausgabe"
    standard_format: str = "45x23"
    barcode: str = "128"  # 128 | QR
    versatz_x_mm: float = 0.0
    versatz_y_mm: float = 0.0
    dichte: int = 8
    geschwindigkeit: int = 4
    luecke_mm: float = 2.0


@dataclass
class MailCfg:
    aktiv: bool = False
    server: str = ""
    port: int = 587
    ssl: bool = False
    starttls: bool = True
    benutzer: str = ""
    passwort: str = ""
    absender: str = ""
    empfaenger: str = ""
    uhrzeit: str = "07:30"


@dataclass
class BackupCfg:
    aktiv: bool = True
    ordner: str = "backups"
    uhrzeit: str = "22:00"
    aufbewahren_tage: int = 30


SECTIONS = ("server", "daten", "lager", "drucker", "mail", "backup")


@dataclass
class Config:
    server: ServerCfg = field(default_factory=ServerCfg)
    daten: DatenCfg = field(default_factory=DatenCfg)
    lager: LagerCfg = field(default_factory=LagerCfg)
    drucker: DruckerCfg = field(default_factory=DruckerCfg)
    mail: MailCfg = field(default_factory=MailCfg)
    backup: BackupCfg = field(default_factory=BackupCfg)

    def path(self, p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else BASE_DIR / pp

    @property
    def db_url(self) -> str:
        return "sqlite:///" + str(self.path(self.daten.datenbank)).replace("\\", "/")


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    cfg = Config()
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for section in SECTIONS:
            obj = getattr(cfg, section)
            for k, v in data.get(section, {}).items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
    if os.environ.get("LV_DATENBANK"):
        cfg.daten.datenbank = os.environ["LV_DATENBANK"]
    if not cfg.server.secret_key:
        key_file = BASE_DIR / ".secret_key"
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32))
        cfg.server.secret_key = key_file.read_text().strip()
    return cfg


def _toml_text(v: str) -> str:
    """TOML-String; Steuerzeichen (z. B. Zeilenumbruch aus einem Formularfeld) würden die Datei sonst unlesbar machen."""
    out = []
    for c in v:
        if c in ('"', "\\"):
            out.append("\\" + c)
        elif ord(c) < 32 or ord(c) == 127:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def save_section(section: str, values: dict, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault(section, {}).update(values)
    out = ["# Konfiguration Lagerverwaltung – wird auch über die Einstellungsseite gepflegt", ""]
    for sec, vals in data.items():
        out.append(f"[{sec}]")
        for k, v in vals.items():
            if isinstance(v, bool):
                s = "true" if v else "false"
            elif isinstance(v, (int, float)):
                s = repr(v)
            else:
                s = _toml_text(str(v))
            out.append(f"{k} = {s}")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")
