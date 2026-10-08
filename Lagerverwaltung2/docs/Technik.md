# Technische Beschreibung

## Aufbau

| Teil | Technik |
|---|---|
| Server | Python 3.12, FastAPI, Uvicorn; läuft als Hintergrundprozess auf einem Windows-PC |
| Datenbank | SQLite (eine Datei `daten/lager.db`, WAL-Modus), Zugriff über SQLAlchemy Core |
| Oberfläche | Server-gerenderte Seiten (Jinja2), HTMX, Alpine.js, Tailwind CSS; alle Dateien lokal, kein Internet nötig |
| Scanner-App | `/m`, installierbare Web-App (Manifest, Service Worker `/m/sw.js`); Scantaste über Tastatureingabe (DataWedge), Kamera-Scan über BarcodeDetector bzw. ZXing (lokal) |
| Offline-Modus | Warteschlange in IndexedDB des Geräts, Artikelkatalog `/m/katalog.json` zwischengespeichert, Übertragung über `/m/sync` mit UUID je Buchung (Tabelle `sync_log` verhindert Doppelbuchungen) |
| HTTPS | Port 8443; eigene kleine CA (`daten/lager_ca.crt`, Download `/zertifikat.crt`; der private Schlüssel `daten/lager_ca_schluessel.pem` wird nie ausgeliefert) stellt das Serverzertifikat aus und erneuert es beim Start, wenn sich IP/PC-Name geändert haben oder es in weniger als 30 Tagen abläuft |
| Etikettendruck | TSPL direkt an HPRT HT100 (Windows-Spooler RAW über winspool.drv oder TCP 9100); Fallback Browserdruck |
| Sicherung | täglich ZIP mit konsistenter SQLite-Kopie (Backup-API) und Anhängen |

Gleichzeitige Buchungen (PC, mehrere Handscanner, API) werden über Schreibtransaktionen mit sofortiger Sperre (`BEGIN IMMEDIATE`) nacheinander ausgeführt; Lesen blockiert nicht. Getestet mit parallelen Entnahmen des letzten Teils (Threads und echte HTTP-Anfragen).

Anmeldung: Die Sitzung liegt signiert im Cookie (30 Tage), wird aber bei jedem Aufruf gegen die Tabelle `users` geprüft – Sperre, Rollenwechsel und Passwortänderung wirken sofort. Größere Daten (Sammelentnahme-Liste, Übernahmebericht) liegen in der Tabelle `settings`, nicht im Cookie (Browsergrenze 4 KB). Weiterleitungen (`weiter`, Referer) sind auf Pfade der eigenen Anwendung beschränkt; Anhänge werden nur als Bild/PDF/Text im Browser angezeigt, alles andere als Download.

## Datenmodell

`artikel`, `lagerplaetze`, `bestand` (Menge je Artikel und Platz), `bewegungen` (jede Buchung mit Zeit, Benutzer, Menge ±, Bestand danach, Empfänger, Kostenstelle, Zweck, Quelle pc/mobil/offline/api/import), `reservierungen`, `bestellungen`, `inventuren`/`inventur_pos`, `lieferanten`, `anhaenge`, `users`, `audit`, `settings`, `sync_log`.

Mengen: Komma oder Punkt als Dezimaltrenner; „nan“, „inf“ und Werte über 1 Milliarde werden abgelehnt.

Buchungsarten: `eingang`, `ausgang`, `umbuchung` (zwei verknüpfte Zeilen), `inventur`, `anlage`, `ausleihe`, `rueckgabe`, `info` (nur Historie aus dem Altsystem).

Alle Bestandsänderungen laufen über `app/services/lager.py` (Klasse `Lager`).

## Übernahme aus Casper

`app/services/casper_import.py` liest den HeidiSQL-Export (nur INSERT-Anweisungen am Zeilenanfang – das `INSERT` im Casper-Trigger `bewegungsdaten_after_insert` wird ignoriert) und übernimmt:

| Casper | Neu |
|---|---|
| stammdaten.Artikelnummer / Bezeichnung | artikel.nummer / bezeichnung |
| Meldebestand / Mindestbestand (Text, 0 = nicht gepflegt) | Zahl oder leer |
| Freifeld1 „Lieferant“ | lieferanten (Schreibvarianten zusammengeführt) |
| Freifeld2 „Gruppe“, Freifeld3 „Typenbezeichnung“ | kategorie, typ |
| Freifeld4 „Austragungsgrund“, Freifeld5 | notiz |
| lagerorte (Leerzeichen bereinigt, Duplikate summiert, leer → OHNE-PLATZ) | lagerplaetze + bestand |
| bewegungsdaten (Eingang, Ausgang, Umbuchung/Umlagerung, Inventur, Neuer Artikel, Artikel bearbeitet/gelöscht) | bewegungen (quelle = import) |
| benutzer | users (gesperrt, ohne Passwort) |

Lagerort-Zeilen zu nicht mehr vorhandenen Artikeln werden nicht übernommen (im Bericht genannt).

## Schnittstelle

Token-Authentifizierung (`Authorization: Bearer <Schlüssel>`, Schlüssel je Benutzer unter *Einstellungen → Schnittstelle*). Endpunkte unter `/api/v1/…`: Artikel (Liste, Detail mit Beständen je Platz), Lagerplätze, Bewegungen seit ID, Buchung anlegen, Reservierung anlegen. Beschreibung maschinenlesbar unter `/api/openapi.json`. Gedacht für die spätere Anbindung der Instandhaltungs-Software (Ersatzteile reservieren/entnehmen je Auftrag).

## Entwicklung

```
pip install -r requirements.txt
cd frontend && npm install && ./build_css.sh
python -m app.main                      # http://localhost:8080, https://localhost:8443
python -m pytest tests                  # LV_CASPER_EXPORT=<datei.sql> testet zusätzlich die Übernahme echter Daten (Sollwerte 821 / 377 / 2702)
```
