# Prüfwerkzeuge (Abschlussprüfung 2.2.1)

Nicht Teil des Auslieferungspakets. Wiederholen der Browser- und Rollenprüfungen aus `Lagerverwaltung2/docs/Pruefbericht.md`.

Voraussetzungen: Python 3.12 mit `requirements-lock.txt` + `pytest httpx`, Node mit Playwright (Chromium).

| Datei | Zweck |
|---|---|
| `demo_start.sh <name> <http-port> <https-port>` | startet die App mit erfundenen Demodaten (`demo_seed.py`) im Hintergrund; `stop_demos.sh` beendet sie |
| `mobil.cjs <url> <ordner>` | Scanner-App 360×720: JS-Fehler, horizontales Scrollen, 44-px-Ziele, Hardware-Scan, Service Worker |
| `offline.cjs <url> <lager.db> <ordner>` | Offline-Szenario (16 Schritte) |
| `notfall_app.cjs <url> <ordner> [pdf-ordner]` | 2.9.0 mit Demodaten: Schicht wieder öffnen, Nachtrag, Papierformulare (auch als PDF für `docs/`), Instandhaltungs-App am Handy, Programmname |
| `umzug.cjs alt <url> <ausgabe> <zielordner>` / `umzug.cjs neu <url> <ausgabe>` | 2.10.0: Umzugspaket über die Einstellungen erstellen, „nur lesen“ prüfen; nach Entpacken und Start im neuen Ordner: Daten, Einstellungen, Buchen |
| `montage.cjs <url> <ordner> <demo-vorlage.xlsx>` | 2.12.0: Set (anlegen, Teil entnehmen, Warnung PC/Scanner), Stutzen-Import, Montageprotokoll als Operator (Vorbelegung, Skizze anklicken, #↓, Abschluss), Druck als PDF, Excel, Handy. Demo-Vorlage: `vorlage_xlsx()` aus `tests/test_2120.py` |
| `last.py <url> <lager.db> [sekunden] [real]` | Lasttest mit 10 Benutzern gegen einen laufenden Demo-Server (`[cmms] aktiv = true`); prüft Bestand = Buchungen, keine Minusbestände, Antwortzeiten |
| `schichtbuch.cjs <url> <ordner>` | 2.8.0 mit Demodaten: Schichtbuch von Einrichten bis Übergabe, Export, Handy-Breite |
| `ersatzteile.cjs <url> <ordner>` | 2.7.0 mit Demodaten: Ersatzteil ↔ Tag-Nr., eigene Kampagne, Auftrag mit Entnahme, Handy-Breite |
| `pc.cjs <url> <ordner>` | PC-Seiten 1440×900/1280×720, hell/dunkel, Screenshots |
| `druck.cjs <url> <ordner>` | Browserdruck als PDF (Seitengröße, ein Etikett je Seite) |
| `doppel.cjs`, `doppel_pc.cjs`, `korb_browser.cjs` | Doppel-Tipp und Cookie-Grenze der Sammelentnahme im Browser |
| `routen.py <Lagerverwaltung2> <ausgabe.json>` | Rollenmatrix aller Routen (Gast/lesen/lager/admin) |
| `export_soll.py <export.sql> <soll.json>`, `import_check.py <Lagerverwaltung2> <export.sql> <soll.json>` | unabhängige Soll-Werte aus dem Casper-Export und Abgleich der Übernahme (Ausgabe enthält Stichproben – nicht weitergeben) |

Node-Skripte mit `NODE_PATH=<globale node_modules> node …` starten, falls Playwright global installiert ist.
