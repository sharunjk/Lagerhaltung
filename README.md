# Lagerverwaltung CAPHENIA

Neubau der PC-Oberfläche der Lagerverwaltung als Ersatz für die Casper-Lagerverwaltung (Kalipso / MIS Communicator). Die neue Software arbeitet auf derselben MySQL-Datenbank `daten`, damit das Handheld mit der originalen Casper-App unverändert weiterläuft.

## Stand

| Phase | Inhalt | Status |
|---|---|---|
| 0 – Analyse | Auswertung von Schema, Historie, Konfiguration, Etikettenlayouts | **abgeschlossen, wartet auf Antworten und Dump** |
| 1 – Parität (MVP) | Funktionen des Altsystems, Etikettendruck, Login, Tests, Windows-Paket, Handheld-Testplan | offen |
| 2 – Verbesserungen | Scan/Schnellbuchung, Lagerplätze, erweiterte Artikeldaten, Nachbestellung, Inventur, Auswertungen | offen |
| 3 – Inbetriebnahme | Installations-, Benutzer- und Admin-Handbuch | offen |

## Dokumente

- [`docs/legacy-analyse.md`](docs/legacy-analyse.md) ([PDF](docs/pdf/legacy-analyse.pdf)) – Ergebnisse der Analyse des Altsystems
- [`docs/offene-fragen.md`](docs/offene-fragen.md) ([PDF](docs/pdf/offene-fragen.pdf)) – Fragen, die vor Phase 1 beantwortet werden müssen

## Werkzeuge

- `tools/analyse_bewegungen_csv.py` – reproduziert die Kennzahlen aus dem Bewegungs-Export:
  `python tools/analyse_bewegungen_csv.py casper/Lagerverwaltung/Lagerverwaltung/SelektionBewegungsdaten.CSV`
- `tools/legacy_dump_checks.sql` – reine `SELECT`-Prüfabfragen für den Datenbank-Dump (nur in der Entwicklungs-DB ausführen)
- `tools/docs_to_pdf.sh` – erzeugt die PDF-Fassungen der Dokumente in `docs/pdf/`

## Altsystem-Dateien

Unter `casper/` liegen die nicht-sensiblen Dateien des Altsystems (Schema ohne Daten, Konfigurationen, Etikettenlayouts). Echtdaten (CSV-Exporte, Datenbank-Dumps) und das Druckerhandbuch sind per `.gitignore` ausgeschlossen und werden nur lokal abgelegt.
