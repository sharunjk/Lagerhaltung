"""Etiketten für den HPRT HT100 (TSPL-Emulation, 203 dpi) + SVG-Vorschau.

Layouts nachgebaut aus den Casper-Vorlagen 45x23.txt / 60x20.txt:
  45x23: Barcode x=6 y=2 b=33 h=11 mm, Textzeile 1 bei y=14, Zeile 2 bei y=18 (Arial 8 pt, zentriert)
  60x20: Barcode x=7 y=2 b=46 h=8 mm,  Textzeile 1 bei y=11, Zeile 2 bei y=15 (Arial 10 pt, zentriert)
"""
from __future__ import annotations

import ctypes
import socket
import sys
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

DOTS_PER_MM = 8  # 203 dpi


@dataclass(frozen=True)
class Layout:
    name: str
    breite: float
    hoehe: float
    bc_x: float
    bc_y: float
    bc_b: float
    bc_h: float
    zeile1_y: float
    zeile2_y: float
    tspl_font: str  # interner Font: "2" = 12x20 dots, "3" = 16x24 dots
    font_b: int  # Zeichenbreite in Dots
    font_h: int
    css_pt: float


LAYOUTS = {
    "45x23": Layout("45x23", 45, 23, 6, 2, 33, 11, 14, 18, "2", 12, 20, 8),
    "60x20": Layout("60x20", 60, 20, 7, 2, 46, 8, 11, 15, "3", 16, 24, 10),
}

# ------------------------------------------------------------------ Code 128 (Zeichensatz B)
_C128 = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]


def code128_modules(data: str) -> list[int]:
    """Liefert Balken-/Lückenbreiten (Module) für Code 128B."""
    data = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in data)
    codes = [104] + [ord(c) - 32 for c in data]
    chk = (codes[0] + sum(i * c for i, c in enumerate(codes[1:], 1))) % 103
    codes += [chk, 106]
    return [int(w) for c in codes for w in _C128[c]]


def code128_svg(data: str, x: float, y: float, w: float, h: float) -> str:
    mods = code128_modules(data)
    total = sum(mods)
    unit = w / total
    out, pos = [], x
    for i, m in enumerate(mods):
        if i % 2 == 0:
            out.append(f'<rect x="{pos:.3f}" y="{y}" width="{m * unit:.3f}" height="{h}"/>')
        pos += m * unit
    return "".join(out)


def qr_svg(data: str, x: float, y: float, size: float) -> str:
    try:
        import segno
    except ImportError:  # pragma: no cover
        return f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="none" stroke="#000" stroke-width="0.2"/>'
    qr = segno.make(data, error="m", micro=False)
    matrix = list(qr.matrix)
    n = len(matrix)
    u = size / n
    rects = [f'<rect x="{x + c * u:.3f}" y="{y + r * u:.3f}" width="{u:.3f}" height="{u:.3f}"/>'
             for r, row in enumerate(matrix) for c, v in enumerate(row) if v]
    return "".join(rects)


def _kuerzen(text: str, max_zeichen: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= max_zeichen else text[: max_zeichen - 1] + "…"


def etikett_svg(code: str, zeile1: str, zeile2: str, layout: str = "45x23", barcode: str = "128", scale: float = 1.0) -> str:
    L = LAYOUTS[layout]
    if barcode.upper() == "QR":
        size = min(L.bc_h, L.bc_b)
        bc = qr_svg(code, L.bc_x + (L.bc_b - size) / 2, L.bc_y, size)
    else:
        bc = code128_svg(code, L.bc_x, L.bc_y, L.bc_b, L.bc_h)
    max_z = int(L.breite * DOTS_PER_MM // L.font_b)
    fs = L.css_pt * 0.3528  # pt -> mm
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {L.breite} {L.hoehe}" '
        f'width="{L.breite * scale}mm" height="{L.hoehe * scale}mm" class="etikett">'
        f'<rect width="{L.breite}" height="{L.hoehe}" fill="#fff"/>'
        f'<g fill="#000">{bc}</g>'
        f'<g font-family="Arial, Helvetica, sans-serif" font-size="{fs:.2f}" text-anchor="middle" fill="#000">'
        f'<text x="{L.breite / 2}" y="{L.zeile1_y + fs * 0.8:.2f}">{escape(_kuerzen(zeile1, max_z))}</text>'
        f'<text x="{L.breite / 2}" y="{L.zeile2_y + fs * 0.8:.2f}">{escape(_kuerzen(zeile2, max_z))}</text>'
        f"</g></svg>"
    )


# ------------------------------------------------------------------ TSPL
def _tspl_str(s: str) -> str:
    return s.replace('"', "'").replace("\\", "/")


def etikett_tspl(code: str, zeile1: str, zeile2: str, layout: str = "45x23", barcode: str = "128",
                 anzahl: int = 1, versatz_x_mm: float = 0, versatz_y_mm: float = 0, dichte: int = 8,
                 geschwindigkeit: int = 4, luecke_mm: float = 2.0) -> bytes:
    L = LAYOUTS[layout]
    d = DOTS_PER_MM
    breite_dots = int(L.breite * d)
    ox, oy = int(versatz_x_mm * d), int(versatz_y_mm * d)
    cmds = [
        f"SIZE {L.breite} mm,{L.hoehe} mm",
        f"GAP {luecke_mm} mm,0 mm",
        f"SPEED {geschwindigkeit}",
        f"DENSITY {dichte}",
        "DIRECTION 1,0",
        "REFERENCE 0,0",
        "CODEPAGE 1252",
        "CLS",
    ]
    if barcode.upper() == "QR":
        size_dots = int(min(L.bc_h, L.bc_b) * d)
        n_mod = 25 if len(code) <= 20 else 29  # QR Version 2/3
        cell = max(1, min(10, size_dots // n_mod))
        x = int(L.bc_x * d + (L.bc_b * d - cell * n_mod) / 2)
        cmds.append(f'QRCODE {x + ox},{int(L.bc_y * d) + oy},M,{cell},A,0,"{_tspl_str(code)}"')
    else:
        modules = sum(code128_modules(code))
        narrow = max(1, min(3, int(L.bc_b * d // modules)))
        bc_w = modules * narrow
        x = int(L.bc_x * d + (L.bc_b * d - bc_w) / 2)
        cmds.append(f'BARCODE {x + ox},{int(L.bc_y * d) + oy},"128",{int(L.bc_h * d)},0,0,{narrow},{narrow},"{_tspl_str(code)}"')
    max_z = breite_dots // L.font_b
    for txt, y in ((zeile1, L.zeile1_y), (zeile2, L.zeile2_y)):
        t = _kuerzen(txt, max_z).replace("…", ".")
        x = max(0, (breite_dots - len(t) * L.font_b) // 2)
        cmds.append(f'TEXT {x + ox},{int(y * d) + oy},"{L.tspl_font}",0,1,1,"{_tspl_str(t)}"')
    cmds.append(f"PRINT {max(1, int(anzahl))},1")
    return ("\r\n".join(cmds) + "\r\n").encode("cp1252", errors="replace")


# ------------------------------------------------------------------ Ausgabe an den Drucker
class DruckFehler(RuntimeError):
    pass


def windows_drucker() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                             capture_output=True, text=True, timeout=15)
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def _raw_windows(druckername: str, daten: bytes) -> None:
    """RAW-Druck über den Windows-Spooler (winspool.drv), ohne zusätzliche Bibliotheken."""
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv")

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    h = wintypes.HANDLE()
    if not winspool.OpenPrinterW(druckername, ctypes.byref(h), None):
        raise DruckFehler(f"Drucker '{druckername}' wurde nicht gefunden.")
    try:
        doc = DOC_INFO_1("Lagerverwaltung Etikett", None, "RAW")
        if not winspool.StartDocPrinterW(h, 1, ctypes.byref(doc)):
            raise DruckFehler("Druckauftrag konnte nicht gestartet werden.")
        try:
            winspool.StartPagePrinter(h)
            written = wintypes.DWORD()
            buf = ctypes.create_string_buffer(daten)
            if not winspool.WritePrinter(h, buf, len(daten), ctypes.byref(written)):
                raise DruckFehler("Daten konnten nicht an den Drucker gesendet werden.")
            winspool.EndPagePrinter(h)
        finally:
            winspool.EndDocPrinter(h)
    finally:
        winspool.ClosePrinter(h)


def senden(cfg, daten: bytes, base_path) -> str:
    """Sendet TSPL-Daten gemäß Konfiguration. Gibt eine Statusmeldung zurück."""
    modus = cfg.modus
    if modus == "windows":
        if sys.platform != "win32":
            raise DruckFehler("Windows-Druck ist nur auf dem Windows-PC möglich. Für Tests 'datei' einstellen.")
        _raw_windows(cfg.name, daten)
        return f"An Drucker „{cfg.name}“ gesendet."
    if modus == "netzwerk":
        if not cfg.host:
            raise DruckFehler("Keine Drucker-IP eingestellt.")
        try:
            with socket.create_connection((cfg.host, int(cfg.port)), timeout=5) as s:
                s.sendall(daten)
        except OSError as e:
            raise DruckFehler(f"Drucker {cfg.host}:{cfg.port} nicht erreichbar ({e}).") from e
        return f"An {cfg.host}:{cfg.port} gesendet."
    ordner = Path(base_path(cfg.datei_ordner))
    ordner.mkdir(parents=True, exist_ok=True)
    f = ordner / f"etikett_{datetime.now():%Y%m%d_%H%M%S_%f}.prn"
    f.write_bytes(daten)
    return f"Druckdatei gespeichert: {f.name}"
