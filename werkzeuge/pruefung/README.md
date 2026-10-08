# Prüfwerkzeuge (Abschlussprüfung 2.2.1)

Nicht Teil des Auslieferungspakets. Wiederholen der Browser- und Rollenprüfungen aus `Lagerverwaltung2/docs/Pruefbericht.md`.

Voraussetzungen: Python 3.12 mit `requirements-lock.txt` + `pytest httpx`, Node mit Playwright (Chromium).

| Datei | Zweck |
|---|---|
| `demo_start.sh <name> <http-port> <https-port>` | startet die App mit erfundenen Demodaten (`demo_seed.py`) im Hintergrund; `stop_demos.sh` beendet sie |
| `mobil.cjs <url> <ordner>` | Scanner-App 360×720: JS-Fehler, horizontales Scrollen, 44-px-Ziele, Hardware-Scan, Service Worker |
| `offline.cjs <url> <lager.db> <ordner>` | Offline-Szenario (16 Schritte) |
| `pc.cjs <url> <ordner>` | PC-Seiten 1440×900/1280×720, hell/dunkel, Screenshots |
| `druck.cjs <url> <ordner>` | Browserdruck als PDF (Seitengröße, ein Etikett je Seite) |
| `doppel.cjs`, `doppel_pc.cjs`, `korb_browser.cjs` | Doppel-Tipp und Cookie-Grenze der Sammelentnahme im Browser |
| `routen.py <Lagerverwaltung2> <ausgabe.json>` | Rollenmatrix aller Routen (Gast/lesen/lager/admin) |
| `export_soll.py <export.sql> <soll.json>`, `import_check.py <Lagerverwaltung2> <export.sql> <soll.json>` | unabhängige Soll-Werte aus dem Casper-Export und Abgleich der Übernahme (Ausgabe enthält Stichproben – nicht weitergeben) |

Node-Skripte mit `NODE_PATH=<globale node_modules> node …` starten, falls Playwright global installiert ist.
