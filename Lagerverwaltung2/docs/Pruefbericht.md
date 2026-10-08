# Prüfbericht Lagerverwaltung 2.2 → 2.2.1

- **Gegenstand:** `Lagerverwaltung_v2.2.zip` (Version 2.2.0), Abschlussprüfung vor dem Produktivstart
- **Ergebnis:** korrigierte Version **2.2.1** (`Lagerverwaltung_v2.2.1.zip`)
- **Prüfdatum:** 08.10.2026
- **Prüfumgebung:** Linux, Python 3.12.3, Pakete in exakt den Versionen aus `lib/` (Linux-Builds gleicher Versionen), Chromium 141 (Playwright 1.56.1), ruff 0.16.8, pyflakes. Kein Windows, kein HT100, kein TC21 verfügbar – diese Teile per Code-Review (Abschnitt 7) und als Vor-Ort-Checkliste (Abschnitt 12).
- **Daten:** `daten_export.sql` nur lokal in einer Wegwerf-Umgebung verwendet; in diesem Bericht stehen nur Summen und Anzahlen, keine Inhalte. Screenshots und Browsertests liefen mit erfundenen Demodaten.

## Freigabe

**Version 2.2.0: nicht freigeben.** Vier Fehler führen im normalen Betrieb unbemerkt zu falschen Beständen oder verlorenen Buchungen (K1–K4).

**Version 2.2.1: Freigabe JA – unter der Bedingung, dass die Vor-Ort-Checkliste in Abschnitt 12 auf dem Lager-PC und dem TC21 bestanden wird.** Alle gefundenen Fehler sind behoben und durch Tests abgesichert. Alle 60 Tests sind grün, auch mit dem echten Export. Offen sind nur Punkte, die sich ohne Windows-PC, Drucker und Handheld nicht prüfen lassen, sowie drei Empfehlungen ohne Fehlercharakter (Abschnitt 11).

## Übersicht

| Nr. | Prüfbereich | Status | kritisch | mittel | gering |
|---|---|---|---:|---:|---:|
| 1 | Lauffähigkeit und Paket | behoben | – | – | 3 |
| 2 | Datenübernahme aus Casper | bestanden (1 geringer Befund behoben) | – | – | 1 |
| 3 | Buchungslogik | behoben | 2 (K3, K4) | 3 | 4 |
| 4 | Scanner-App `/m` und Offline-Modus | behoben | 2 (K1, K2) | 1 | 2 |
| 5 | Sicherheit | behoben | – | 4 | 5 |
| 6 | Etikettendruck | behoben | – | – | 3 |
| 7 | Betrieb unter Windows (Code-Review) | behoben, Test vor Ort offen | – | 1 | 4 |
| 8 | Datensicherung und Wiederherstellung | behoben | – | 1 | 2 |
| 9 | Dokumentation | behoben | – | (D1) | 4 |
| 10 | Oberfläche | bestanden (1 geringer Befund behoben) | – | – | 1 |
| | **Summe** | | **4** | **10** | **29** |

Schweregrade: **kritisch** = führt im normalen Betrieb unbemerkt zu falschen Beständen oder Datenverlust; **mittel** = Sicherheitslücke, falsche Auswertung oder Fehler mit spürbarer Folge, der aber erkannt wird; **gering** = Robustheit, Komfort, Randfälle.

## Die kritischen Befunde

### K1 – Sammelentnahme verliert Positionen

Ab etwa 20–28 Positionen (je nach Länge der Bezeichnungen) verwirft der Browser das Sitzungs-Cookie. Neue Positionen verschwinden kommentarlos, die Meldung fehlt. Bei Doppel-Tipp auf „Buchen“ kann die Liste außerdem zweimal gebucht werden.

- **Ursache:** Die Liste lag im signierten Sitzungs-Cookie (`mobil.py:291–325`). Browser nehmen höchstens 4 KB an. Gelesen wurde die Liste vor der Schreibsperre.
- **Behebung:** Die Liste liegt jetzt in der Tabelle `settings` je Benutzer. Sie wird innerhalb der Schreibtransaktion gelesen und geleert, ein zweites Absenden findet eine leere Liste.
- **Beleg:** Chromium mit v2.2.0: „nach 29 Positionen: Liste zeigt 28“. Test `test_sammelentnahme_nicht_im_cookie_und_nicht_doppelt`: v2.2.0 hat 10.979 Byte Cookie bei 40 Positionen, v2.2.1 bleibt unter 3.000 und bucht genau 40.

### K2 – Offline-Modus mit Handscanner unbrauchbar

Nach dem Artikel-Scan wird der Lagerplatz vorbelegt. Der anschließende Platz-Scan wird angehängt (`C1-R2-1C1-R2-1`), jede so erfasste Offline-Buchung scheitert. Bei „Zählen“ würde ein Fantasie-Platz angelegt. „Erneut senden“ in der Warteschlange war defekt (`could not be cloned`).

- **Ursache:** Vorbelegung ohne Markierung des Textes (`m/offline.html:68`). „Erneut senden“ schrieb einen Alpine-Proxy in IndexedDB (`m/offline.html:46`).
- **Behebung:** Vorbelegter Platz wird markiert, ein Scan ersetzt ihn (auch in allen anderen Platzfeldern). In IndexedDB wird eine Kopie gespeichert.
- **Beleg:** Browser-Szenario (Abschnitt 4): v2.2.0 hat 10 von 16 Schritten FAIL, v2.2.1 alle 16 OK.

### K3 – Inventur-Abschluss überschreibt Buchungen

Wird zwischen Zählung und Abschluss am Platz gebucht, setzt der Abschluss den Bestand auf den alten Zählwert. Die Buchung geht im Bestand verloren.

- **Ursache:** `lager.py:379` setzt den Platz auf `ist`, ohne Bewegungen nach `gezaehlt_am` zu berücksichtigen.
- **Behebung:** Neuer Bestand = gezählt ± Summe der bestandswirksamen Bewegungen an diesem Platz seit dem Zählzeitpunkt. Das wird im Buchungstext vermerkt.
- **Beleg:** `test_inventur_abschluss_behaelt_buchungen_nach_der_zaehlung`: v2.2.0 ergibt 8, korrekt ist 5.

### K4 – Doppel-Tipp bucht doppelt

In der Scanner-App prüft das Formular vor dem Absenden die Verbindung (bis 2,5 s). Ein zweiter Tipp in dieser Zeit sendet ein zweites Mal.

- **Ursache:** Kein Schutz gegen erneutes Absenden in `offline.js:126–135`.
- **Behebung:** Formular wird während der Prüfung gesperrt. Zusätzlich gibt es einen allgemeinen Schutz gegen doppeltes Absenden für alle POST-Formulare (PC und Handheld).
- **Beleg:** Chromium mit verzögertem WLAN: v2.2.0 bucht **2** Entnahmen, v2.2.1 bucht **1**.

## 1. Lauffähigkeit und Paket – behoben

| Prüfung | Ergebnis | Beleg |
|---|---|---|
| `pip install -r requirements-lock.txt`, `python -m pytest tests` mit `LV_CASPER_EXPORT` | v2.2.0: 9/9 grün. v2.2.1: **60/60 grün** (9 alte + 51 neue) | `LV_CASPER_EXPORT=daten_export.sql python -m pytest tests` → `60 passed` |
| ruff/pyflakes | keine undefinierten Namen. 7 ungenutzte Importe, 1 überschriebene Schleifenvariable, 2 `zip` ohne `strict` – bereinigt | `ruff check --select F,E9,B,PLW` → `All checks passed!`, pyflakes ohne Meldung |
| Schattierungen | `artikel` wird in 4 Routen als Parameter verwendet (`buchen.py:56/68`, `mobil.py:109/305`), im Rumpf aber nie als Tabelle – kein Fehler. Die Parameter `id`, `filter`, `format` sind Formularnamen und harmlos | AST-Prüfung „Parameter verdeckt Tabelle und wird als Tabelle benutzt“: 0 Treffer |
| Start mit leerem Datenordner | legt `daten/lager.db`, `daten/anhaenge`, CA, HTTPS-Zertifikat, `logs/` und `.secret_key` selbst an. HTTP 303→Einrichtung, HTTPS 200 | `test_start_mit_leerem_datenordner`, Start aus entpacktem ZIP |
| `lib/` ↔ `requirements-lock.txt` | gleiche Versionen. Alle Binärteile sind `cp312-win_amd64` bzw. `cp311-abi3-win_amd64` (cryptography). **G1:** 5 indirekte Pakete fehlten in der Lock-Datei (annotated-doc, et-xmlfile, opentelemetry-api, pydantic-core, typing-extensions) – ergänzt, jetzt 26 = 26 | Vergleichsskript `lock == lib: True 26 26` |
| Start nur mit `lib/` und `python -I -S` | startet (HTTP und HTTPS), auch mit Arbeitsverzeichnis `/`. Keine fehlenden Abhängigkeiten | `python3.12 -I -S -c "sys.path[:0]=[prog, lib]; run()"` |
| Echte Daten/Geheimnisse im Paket | keine `config.toml`, `.secret_key`, `.db`, `.pem`, `.sql`, keine Echtdaten. **G2:** 43 Bytecode-Dateien `cpython-313.pyc` im Paket – im neuen Paket entfernt | `find`/`grep` über das Paket |
| **G3:** Versionsnummer | Ohne neue Versionsnummer würde der Service Worker (`lager-{{version}}`) die korrigierten Skripte auf installierten TC21 nie nachladen – auf `2.2.1` gesetzt | `sw.js` liefert `const CACHE = "lager-2.2.1"` |

## 2. Datenübernahme aus Casper – bestanden

Unabhängige Soll-Werte aus dem Export, zeilenweise mit `ast.literal_eval` gelesen statt mit dem App-Parser:

| Größe | Soll (Export) | Ist (Übernahme) | |
|---|---:|---:|---|
| Artikel | 821 | 821 | ✔ |
| Summe Bestand (Artikel in `stammdaten`) | 377 | 377 | ✔ |
| Buchungen | 2.702 | 2.702 | ✔ |
| Lagerort-Zeilen im Export | 896 | 888 übernommen + 8 zu gelöschten Artikeln | ✔ |
| Lagerplätze | 92 (Schreibweisen ohne Groß-/Kleinschreibung) | 92 | ✔ |

- **Stichproben:** 13 Artikel (10 zufällig, 3 mit Umlauten) – Bezeichnung, Lieferant, Gruppe, Typ und Bestand je Platz stimmen mit dem Export überein (0 Abweichungen).
- **Sonderfälle:**
  - 7 Lagerorte mit Leerzeichen werden bereinigt.
  - 15 leere Lagerorte (6 Stück Bestand) landen auf `OHNE-PLATZ`.
  - 8 Zeilen zu gelöschten Artikeln werden nicht übernommen und im Bericht genannt.
  - Melde-/Mindestbestand „0“ wird zu „nicht gepflegt“. Das ist so dokumentiert, die Statuslogik behandelt 0 ebenso.
  - Umlaute korrekt. Apostroph-Escaping durch einen Test mit `O\'Ring` abgedeckt; im Export kommt kein Apostroph vor.
  - Doppelte Lagerort-Zeilen: im Export keine, im Test werden sie summiert.
- **G4 (behoben):** Der Parser las auch das `INSERT INTO lagerorte … VALUES (new.Artikelnummer, …)` aus dem Casper-Trigger `bewegungsdaten_after_insert` als Datenzeile (`casper_import.py:79`). Folge war nur ein falscher Hinweis („9“ statt „8“ verwaiste Zeilen). Das ist auch die Erklärung für die **897** im Prüfauftrag; der Export enthält 896 echte Zeilen. Jetzt zählen nur `INSERT` am Zeilenanfang (`test_import_ignoriert_trigger`).
- **Erneute Übernahme mit „Vorhandene Daten ersetzen“:**
  - Ohne Haken wird abgelehnt.
  - Mit Haken entsteht vorher `vor_uebernahme_….zip` (enthält den Stand inkl. Testbuchung).
  - Danach ist der Stand identisch: Anzahlen, Summen und alle Nummern/Bezeichnungen.
  - Beleg: `test_echter_export_sollwerte_und_ersetzen`.
- Der Übernahmebericht lag dauerhaft im Sitzungs-Cookie (2,1 KB, die Hälfte der 4-KB-Grenze). Jetzt liegt er in der Datenbank (zusammen mit K1 behoben).

## 3. Buchungslogik – behoben

Geprüft für Eingang, Entnahme, Umbuchung, Zählen, Ausleihe, Rückgabe, Storno, Sammelentnahme, Rückgängig, Wareneingang, Reservierungsentnahme und Inventur-Abschluss: Bestand je Platz und gesamt, `bestand_nachher`, Protokollierung (Bewegung + Benutzer, nichts wird gelöscht) und kein negativer Bestand im Standard. Bestehende Tests plus 51 neue.

| Nr. | Schwere | Befund | Behebung | Beleg |
|---|---|---|---|---|
| K3, K4 | kritisch | siehe oben (K1 Sammelentnahme und K2 Offline unter Abschnitt 4) | | |
| B1 | mittel | **„inf“, „1e999“, „Infinity“ werden als Menge angenommen** → unendlicher Bestand, danach Serverfehler auf allen Seiten mit diesem Artikel (`fmt_num`). **„nan“** → Serverfehler 500. Text im Anfangsbestand wurde stillschweigend zu 0. | `parse_num` lehnt nicht-endliche Zahlen ab. Mengen über 1 Mrd. werden abgelehnt (Barcode im Mengenfeld). Ungültiger Anfangsbestand ergibt eine Meldung. | `test_unsinnige_mengen_werden_abgelehnt` (12 Fälle) – v2.2.0: `DID NOT RAISE` bzw. `IntegrityError` |
| B2 | mittel | **Verbrauchsauswertung zählt stornierte Entnahmen** (und deren Gegenbuchung als Eingang). | Storno-Paare werden in Verbrauch und Kostenstellen ausgeschlossen. | `test_verbrauch_ohne_stornierte_entnahmen` – v2.2.0: 5 statt 1 |
| B3 | mittel | **Rückgängig verknüpft Gegenbuchungen falsch:** Alle Zeilen einer Sammelentnahme bzw. Umbuchung zeigten auf die *letzte* Gegenbuchung. | Jede Zeile zeigt auf ihre eigene Gegenbuchung. | `test_rueckgaengig_umbuchung_verknuepft`, `test_sammelentnahme_…` |
| B4 | gering | Wareneingang auf eine **stornierte** Bestellung buchte und setzte sie auf „geliefert“. | Wird abgelehnt mit Hinweis „als normalen Eingang buchen“. | `test_wareneingang_auf_stornierte_bestellung` |
| B5 | gering | Entnahme mit `reservierung_id` erledigte auch eine Reservierung eines **anderen** Artikels. | Nur offene Reservierung desselben Artikels. | `test_entnahme_erledigt_nur_passende_reservierung` |
| B6 | gering | Platz umbenennen mit unbekanntem Altnamen benannte **alle Bewegungen ohne Platz** um (`lagerplatz_id IS NULL`). | Abbruch mit Meldung. | `test_platz_umbenennen_unbekannter_altname` |
| B7 | gering | Zusammenführen eines Platzes mit negativem Bestand meldete „deaktiviert“, obwohl der Platz aktiv blieb. | Abbruch mit Hinweis „erst per Zählung korrigieren“. | Code `lager.py` |

**Parallelität:**
- 4 Threads auf das letzte Teil: genau 1 Erfolg (`test_parallel`).
- 8 echte HTTP-Anfragen über einen laufenden Uvicorn-Server, gleichzeitig per Barrier gestartet: genau 1 Entnahme, Bestand 0 (`test_parallele_entnahmen_ueber_http`).

**Grenzfälle:**
- Menge 0, negativ, Text, leer, „1,5“/„1.5“, sehr groß, unbekannter Artikel, unbekannter Platz, archivierter Artikel – alle mit verständlicher Meldung.
- Groß-/Kleinschreibung des Platzes: `c1-r1-1` bucht auf `C1-R1-1` und legt keinen zweiten Platz an (`test_grenzfaelle_platz_und_artikel`).

## 4. Scanner-App `/m` und Offline-Modus – behoben

| Prüfung (Chromium, 360×720, Android-User-Agent) | v2.2.0 | v2.2.1 |
|---|---|---|
| 19 Seiten ohne JS-Fehler | ✔ | ✔ |
| kein horizontales Scrollen | ✔ | ✔ |
| Bedienelemente ≥ 44 px | **A1 (gering):** 13 Elementarten kleiner (Kopfzeile 35 px, „PC“ 14×16, Reiter 37 px, Platz-Links 23 px, Aufklapper 19–23 px, Checkboxen 13 px, „Jetzt übertragen“ 25 px) | ✔ – Checkboxen 24 px innerhalb eines ≥ 44 px hohen Labels |
| Hardware-Scan ohne Fokus (Tastatur 8 ms/Zeichen + Enter) | Artikel → `/m/artikel/10002`, Platz → `/m/platz?code=C2-F1` ✔ | ✔ |
| Hardware-Scan mit Fokus im Artikelfeld | lädt Artikel, Fokus springt auf Menge ✔ | ✔ |
| Manifest und Service Worker (installierbar) | Manifest mit Icons 192/512, maskable, `display: standalone`; SW aktiv ✔ | ✔ |

Offline-Szenario mit 16 Schritten (`offline.cjs`). Der Ablauf: Verbindung trennen → wie mit Handscanner erfassen → Seite neu laden → Verbindung herstellen → prüfen. Die Spalten sind die beiden geprüften Versionen.

| Schritt | v2.2.0 | v2.2.1 |
|---|---|---|
| Buchung in Warteschlange, Seite lädt offline aus dem Cache, Warteschlange bleibt | ✔ | ✔ |
| genau **eine** Buchung auf dem Server, Kennzeichnung „offline erfasst …“, Bestand korrekt | ✘ (K2: Platz `C1-R2-1C1-R2-1`) | ✔ |
| gleiche UUID zweimal → keine Doppelbuchung | ✔ | ✔ |
| Fehlerfall (zu wenig Bestand) rot, „Erneut senden“, „Verwerfen“ | ✘ (K2: `could not be cloned`) | ✔ |
| Sitzung offline abgelaufen → Meldung „neu anmelden“, Buchung bleibt, nach Anmeldung übertragen | ✘ | ✔ |
| **A3 (mittel):** online, aber Anmeldung abgelaufen → Formular landete auf der Anmeldung, **Buchung verloren** | ✘ | ✔ – Buchung wird im Gerät gespeichert, nach Anmeldung übertragen |
| keine JS-Fehler | ✘ | ✔ |

Kritisch in diesem Bereich: **K1** (Sammelentnahme) und **K2** (Offline-Scan, „Erneut senden“), siehe oben.

Weitere Befunde in diesem Bereich:
- **A2 (gering):** `/m/sync` mit ungültigem Inhalt gab Serverfehler 500. Eine fehlerhafte Buchung (z. B. Zahl statt Text) brach die ganze Übertragung ab. Rückgabedatum und Reservierung offline erfasster Buchungen gingen verloren.
- Jetzt gibt es 400 bei ungültigem Inhalt, eine Fehlermeldung je Buchung statt Abbruch, und die Felder werden übernommen (`test_sync_robust_und_offline_kennzeichnung`).

## 5. Sicherheit – behoben

Die Rollenmatrix von 109 Routen (Anhang A; alle außer Anmeldung, Abmeldung und Ersteinrichtung, die bewusst öffentlich sind) wurde mit echten Anfragen als Gast/lesen/lager/admin gemessen, mit vollständigen Formulardaten. Nach der Korrektur entspricht jede Route der erwarteten Rolle, kein Aufruf endet in einem Serverfehler.

| Nr. | Schwere | Befund | Behebung | Beleg |
|---|---|---|---|---|
| S1 | mittel | **Offene Weiterleitungen** über `weiter`: `/buchen` (`buchen.py:91`, `//evil.example` wurde akzeptiert), Anhang-Upload (`artikel.py:193`), Etikettendruck (`artikel.py:259`), Wareneingang (`lager.py:246`), Login mit `/\evil.example` (`core.py:44`). | Zentrale Prüfung `sicheres_ziel()`: nur Pfade der eigenen Anwendung, ohne `//`, `\` oder Steuerzeichen. Rücksprung über Referer nur bei gleichem Host. | `test_sicheres_ziel` (9 Angriffsmuster), `test_keine_offene_weiterleitung` |
| S2 | mittel | **Sperre, Rollenentzug und Passwortänderung wirkten erst nach dem Abmelden** (bis zu 30 Tage), weil die Rolle nur aus dem Cookie gelesen wurde (`web.py:30`). | Bei jedem Aufruf Abgleich mit `users` (aktiv, Rolle, Passwort-Fingerabdruck). Eigene Sitzung bleibt beim Passwortwechsel erhalten, andere enden. | `test_rolle_und_sperre_wirken_sofort` (v2.2.0: 303 statt 403), `test_passwortwechsel_beendet_andere_sitzungen` |
| S3 | mittel | **Gespeichertes XSS über Anhänge:** HTML/SVG wurde mit dem vom Browser gemeldeten Typ inline ausgeliefert (`artikel.py:217`). Jeder Benutzer mit Rolle *lager* konnte Skripte im Namen eines Admins ausführen lassen. | Inline nur für Bilder, PDF und Text; sonst Download. Typ aus der Dateiendung, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`. | `test_anhaenge_ohne_aktive_inhalte` |
| S4 | mittel | **API `POST /api/v1/reservierungen` ohne Rollenprüfung** (`api.py:108`): ein Token der Rolle *lesen* konnte reservieren. Menge 0/negativ und archivierte Artikel wurden angenommen. | 403 für *lesen*, 422 für Menge ≤ 0, nur aktive Artikel. | `test_api_rollen` |
| S5 | gering | Seite „Keine Berechtigung“ kam mit Status 200. | 403 | `test_keine_berechtigung_gibt_403` |
| S6 | gering | Upload wurde erst nach vollständigem Einlesen auf 25 MB geprüft. Anhang zu unbekanntem Artikel ergab Serverfehler und eine verwaiste Datei. | Stückweises Lesen mit Abbruch, Artikelprüfung vor dem Schreiben. | `test_anhaenge_ohne_aktive_inhalte` |
| S7 | gering | `scan.js:45` setzte HTML aus der URL per `innerHTML` zusammen. | DOM-Methoden | Code |
| S8 | gering | Excel-Export: Texte, die mit „=“ beginnen (z. B. eine Bezeichnung `=HYPERLINK(…)`), wurden als Formel geschrieben (`excel.py:24`). | als Text speichern | `test_excel_export_ohne_formeln` |
| S9 | gering | Meldebestands-Mail: Bezeichnungen ohne HTML-Maskierung (`betrieb.py:91`). | `html.escape` | `test_mail_html_maskiert` |

Ohne Befund (bestanden):
- **CSRF:** Die Origin/Referer-Prüfung weist fremde Herkunft mit 403 ab, das Cookie ist `SameSite=Lax` (`test_keine_offene_weiterleitung`).
- **Jinja:** Autoescape aktiv. `|safe` nur für selbst erzeugtes SVG (Texte mit `html.escape`), `tojson` in einfach zitierten Attributen (escapt `'`).
- **Pfade:** keine Pfad-Traversal über `/static`, Backup-Download oder Anhänge.
- **SQL-Injection:** kein rohes SQL mit Eingaben, Stichprobe mit 15 Angriffen ohne Wirkung (`test_sql_injection_stichprobe`).
- **API:** ohne bzw. mit falschem Token 401, Rolle *lesen* darf nicht buchen (403).
- **Sitzungs-Cookie:** nach den Korrekturen rund 1 KB, auch direkt nach einer Sammelentnahme mit 60 Positionen.
- **Zertifikate:** CA mit `ca=True` und `keyCertSign`. Server-SAN enthält Hostnamen und IPs. Bei IP-Wechsel wird beim nächsten Start neu ausgestellt (gleiche CA, keine Neuinstallation am Gerät). Der private CA-Schlüssel wird nie ausgeliefert (`test_zertifikate_ca_san_erneuerung_und_kein_schluessel`).

## 6. Etikettendruck – behoben

TSPL im Modus „datei“ für beide Formate, abgeglichen mit dem HT100-Handbuch (Rev. 1.0: 203 dpi, „TSPL Simulation“, Codepages inkl. Windows-1252, Code 128 A/B/C, QR, Dichte 0–15, Geschwindigkeit 2–5):

```
SIZE 45 mm,23 mm / GAP 2.0 mm,0 mm / SPEED 4 / DENSITY 8 / DIRECTION 1,0 / REFERENCE 0,0 / CODEPAGE 1252 / CLS
BARCODE 90,16,"128",88,0,0,2,2,"10001"        (60x20: BARCODE 105,16,"128",64,0,0,3,3,"10001")
TEXT 150,112,"2",0,1,1,"10001"                (Bitmap-Font 12x20)
TEXT 0,144,"2",0,1,1,"Kugelhahn DN15 'Edelstahl' / ."
PRINT 1,1
```

- **Barcode passt ins Etikett:** 45×23 hat 180 von 360 Punkten Breite und 88 Punkte Höhe bis y=104 von 184; 60×20 hat 270 von 480 Punkten. Für einen 5-stelligen Code geprüft im Test `test_tspl_ausgabe`.
- **Code-128-Prüfsumme:** gegen eine unabhängige Implementierung nach ISO/IEC 15417 geprüft (6 Codes, inkl. `09052025` und Platzcodes). Zusätzlich wurde die Browserdruck-Ansicht als PDF gerendert und mit dem Decoder **zxing-cpp** gelesen: 6/6 Etiketten ergeben `Code128` mit der richtigen Nummer.
- **Sonderzeichen:** `"` wird zu `'`, `\` zu `/`. Umlaute kommen als CP1252 an.
- **Browserdruck:** `@page` hat die Etikettengröße. 3 Etiketten ergeben 3 PDF-Seiten mit 127,9 × 65,0 pt (45 × 23 mm) bzw. 169,9 × 56,9 pt (60 × 20 mm).

| Nr. | Schwere | Befund | Behebung |
|---|---|---|---|
| E1 | gering | Zeilenumbrüche/Steuerzeichen in der Bezeichnung wurden ungefiltert an den Drucker geschickt; ein `\r\nPRINT 999` in der Bezeichnung hätte 999 Etiketten gedruckt (`labels.py:120`). | Steuerzeichen werden zu Leerzeichen (`test_tspl_ausgabe`). |
| E2 | gering | Codes über etwa 29 Zeichen (Code 128, 45×23) ragten über den Etikettenrand. | Klare Fehlermeldung mit Hinweis auf QR (`test_tspl_zu_langer_code`). |
| E3 | gering | Geschwindigkeit 1 und 6 einstellbar, der HT100 kennt laut Handbuch nur 2–5. Unbekanntes Format in der Druckansicht ergab Serverfehler (`KeyError`). | Begrenzung auf 2–5, Standardformat bei unbekannter Angabe. |

## 7. Betrieb unter Windows (Code-Review) – behoben, Test vor Ort offen

Zeile für Zeile geprüft: alle Skripte sind ASCII mit CRLF, ohne Umlaute in Ausgaben. Pfade mit Leerzeichen sind durchgehend zitiert, `ExecutionPolicy Bypass` steht bei Skriptdateien.

- `python312._pth` enthält `python312.zip`, `.`, `..\lib`, `..`, `import site`. Damit liegen Programmordner und `lib` im Suchpfad ✔.
- Ohne Konsole (`pythonw.exe` simuliert mit `sys.stdout = sys.stderr = None`): Logging nach `logs/lagerverwaltung.log` und `logs/konsole.log` funktioniert, HTTP und HTTPS antworten ✔.
- RAW-Druck über `winspool.drv`: `OpenPrinterW` mit `byref(HANDLE)`, danach wird das `HANDLE`-Objekt selbst übergeben (nicht `h.value`). Damit ist das Handle unter 64 Bit vollständig ✔.

| Nr. | Schwere | Befund | Behebung |
|---|---|---|---|
| W1 | mittel | `FIREWALL_FREIGEBEN_als_Admin.bat` und `DIENST_EINRICHTEN_als_Admin.bat` prüften keine Adminrechte und meldeten „angelegt und gestartet“ auch, wenn `schtasks`/`netsh` mit „Zugriff verweigert“ scheiterten. | Prüfung mit `net session` und klare Fehlermeldung; Fehler von `schtasks`/`netsh` werden ausgewertet. |
| W2 | gering | `Lagerverwaltung_oeffnen.vbs` nahm die **erste** Zeile, die mit `port` beginnt (Zeile 15) – unabhängig vom Abschnitt (auch `[drucker] port = 9100`). | Liest nur in `[server]`, verträgt UTF-8-BOM, ungültiger Wert ergibt 8080. |
| W3 | gering | Firewall-Regel fest auf 8080/8443; nach Portänderung in den Einstellungen blieb der neue Port gesperrt. | Ports werden aus `config.toml` gelesen. |
| W5 | gering | Ein Zeilenumbruch in einem Einstellungsfeld (z. B. Firmenname) machte `config.toml` unlesbar – danach startete die Lagerverwaltung nicht mehr (`config.py:129`). | Steuerzeichen werden TOML-konform maskiert (`test_konfiguration_mit_steuerzeichen_bleibt_lesbar`). |
| W4 | gering | Dienst (SYSTEM) und Benutzer-Autostart konnten parallel laufen. `ENTFERNEN.bat` ohne Adminrechte ließ die Dienst-Aufgabe stillschweigend stehen. | Das Dienst-Skript entfernt den Benutzer-Autostart. `ENTFERNEN.bat` weist bei eingerichtetem Dienst auf „Als Administrator ausführen“ hin. |

## 8. Datensicherung und Wiederherstellung – behoben

- **Sicherung unter Last:** Ein Thread bucht ununterbrochen, dabei werden 3 Sicherungen erstellt. Jede ZIP enthält `lager.db` (`PRAGMA integrity_check = ok`), `anhaenge/…` und `LIESMICH.txt`. Bewegungen und Bestand passen in jedem Schnappschuss zusammen.
- **Wiederherstellung nach Anleitung:** Stand identisch (Anzahl und höchste ID der Bewegungen).
- **Aufbewahrung:** löscht nur `lager_backup_*.zip` älter als die Frist. Fremde Dateien und `vor_uebernahme_*` bleiben.
- Belege: `test_backup_konsistent_waehrend_schreiben_und_wiederherstellung`, `test_backup_aufbewahrung_loescht_nur_alte_sicherungen`.

| Nr. | Schwere | Befund | Behebung |
|---|---|---|---|
| D1 | mittel | **Wiederherstellungsanleitung unvollständig/falsch:** Die WAL-Dateien `lager.db-wal`/`-shm` wurden nicht erwähnt; bleiben sie liegen, mischt SQLite alte Restdaten in die zurückgespielte Datenbank. „Fenster schließen“ beendet den Hintergrunddienst nicht. | `LIESMICH.txt` in jeder Sicherung und Installationsanleitung mit vollständigen Schritten. |
| D2 | gering | Zwei Sicherungen in derselben Sekunde überschrieben sich (in v2.2.0 entstand aus 3 Sicherungen 1 Datei). | Laufende Nummer im Dateinamen. |
| D3 | gering | Schlug die tägliche Sicherung fehl (z. B. Netzlaufwerk weg), war der Tag trotzdem als erledigt markiert. Mail- und Sicherungsfehler teilten sich einen `try`-Block. | Erst nach Erfolg als erledigt markieren, getrennte Fehlerbehandlung. |

## 9. Dokumentation – behoben

Alle 5 Dokumente gegen die Software geprüft. Ordner `C:\Lagerverwaltung2`, Menüpfade, Ports 8080/8443/9100, `RUECKGAENGIG_MINUTEN = 10`, „bucht alles oder nichts“, „Handscanner (offline)“ und Python 3.12 embeddable stimmen.

Korrigiert (D1 ist in Abschnitt 8 gezählt):
- **D1:** Wiederherstellung, siehe Abschnitt 8.
- **DOK1:** Inventur-Abschluss beschrieben (neue Regel).
- **DOK2:** Storno nur für Eingänge/Entnahmen.
- **DOK3:** HTTPS-Zertifikat wird beim *Start* erneuert, nicht „automatisch“.
- **DOK4:** Firewall-Profil *Öffentlich*, Netzlaufwerk beim Dienst (SYSTEM) nur als UNC-Pfad, erneutes Ausführen der Firewall-Freigabe nach Portänderung.

Dazu kamen Versionsnummern 2.2.1. Alle PDFs wurden aus den aktuellen Markdown-Dateien neu erzeugt (`werkzeuge/docs_pdf.sh`).

## 10. Oberfläche – bestanden

- 34 PC-Seiten in 1440×900 und 1280×720, jeweils hell und dunkel (136 Aufrufe): keine Konsolenfehler, keine Serverfehler, kein horizontales Scrollen. Der Dunkelmodus greift überall außer in der bewusst weißen Druckansicht.
- Leere Zustände (Suche ohne Treffer, leere Listen) und Fehlermeldungen sind verständlich und deutsch. In den Bildschirmtexten fielen keine Tippfehler auf.
- 44-px-Ziele mobil: siehe Abschnitt 4 (A1).
- **U1 (gering):** Bei 1280×720 waren *Protokoll* und *Einstellungen* in der Seitenleiste nur durch Scrollen erreichbar. Jetzt kompaktere Abstände bei niedrigen Bildschirmen, alle Einträge sind sichtbar.

## 11. Nicht behoben – Empfehlungen (ohne Fehlercharakter)

1. **Etikettentext:** Der TSPL-Bitmap-Font 12×20 (45×23) bzw. 16×24 (60×20) entspricht nicht Arial 8/10 pt der Casper-Vorlage. Pro Zeile passen höchstens 30 Zeichen, längere Bezeichnungen werden gekürzt. Arial wäre als TrueType-Download oder Bitmap möglich. Das ist eine Änderung des Funktionsumfangs und bleibt deshalb Ihre Entscheidung.
2. **Ersteinrichtung:** Bis der erste Administrator angelegt ist, kann jeder im Netz `/einrichtung` aufrufen. Deshalb direkt nach der Installation einrichten (so steht es in der Anleitung) und erst danach die Firewall öffnen.
3. **Einzelbuchungen am PC:** Ein Doppelklick ergab im Test keine Doppelbuchung (Chromium verwirft den zweiten Klick). Der neue Absende-Schutz sichert das zusätzlich ab, ein serverseitiger Schutz (Einmal-Kennung je Formular) wäre die vollständige Lösung.

## 12. Vor dem Produktivstart vor Ort testen

Nur am echten Lager-PC (Windows 10/11), HT100 und TC21 prüfbar:

1. `1_EINRICHTEN.bat` mit `python-3.12.10-embed-amd64.zip`, Pfad `C:\Lagerverwaltung2` → „OK: Lagerverwaltung ist startbereit.“
2. Desktop-Symbol startet Edge im App-Modus. Bei geändertem Port wird der richtige Port geöffnet.
3. `FIREWALL_FREIGEBEN_als_Admin.bat` (als Admin → Erfolgsmeldung; ohne Admin → Fehlermeldung). TC21 erreicht `http://<PC>:8080/m` und `https://<PC>:8443/m`.
4. `DIENST_EINRICHTEN_als_Admin.bat`, Neustart des PCs ohne Anmeldung → TC21 erreicht die App. `logs\lagerverwaltung.log` wird geschrieben.
5. **HT100 per USB:** Testetikett 45×23 und 60×20. Barcode mit TC21 und PC-Scanner lesbar, Text mittig, Umlaute korrekt. Ggf. Versatz/Dichte einstellen. Ein altes Casper-Etikett scannen → richtiger Artikel.
6. **TC21:** CA-Zertifikat installieren, App installieren, DataWedge mit Enter. Scan auf Infoseite und in Feldern. Sammelentnahme mit mindestens 30 Positionen.
7. **TC21 offline (WLAN aus):** Artikel scannen → Platz-Etikett scannen (Feld wird ersetzt, nicht angehängt) → Menge → Speichern. WLAN an → Buchung am PC mit „Handscanner (offline)“. Fehlerfall „Erneut senden“/„Verwerfen“.
8. Doppel-Tipp auf „Buchen“ bei schwachem WLAN → genau eine Buchung.
9. Datenübernahme mit **frischem** Export, Ergebnis gegen Casper prüfen (Anzahl Artikel, Gesamtbestand, Stichproben).
10. Sicherung „Jetzt sichern“ ins Netzlaufwerk (UNC-Pfad), Wiederherstellung einmal nach `LIESMICH.txt` auf einer Kopie durchspielen.
11. Zweiter Büro-PC: `Lagerverwaltung_Arbeitsplatz.bat` aus *Einstellungen → Allgemein*.
12. Benutzer sperren bzw. Rolle ändern → wirkt sofort auf dem TC21.

## Anhang B – Neue Tests (`tests/test_pruefung.py`)

| Test | sichert ab |
|---|---|
| `test_unsinnige_mengen_werden_abgelehnt` (12×), `test_parse_num_und_formate`, `test_anfangsbestand_text_wird_abgelehnt`, `test_grenzfaelle_platz_und_artikel` | B1, Grenzfälle |
| `test_inventur_abschluss_behaelt_buchungen_nach_der_zaehlung` | K3 |
| `test_parallele_entnahmen_ueber_http` | Parallelität über echte HTTP-Anfragen |
| `test_sicheres_ziel`, `test_keine_offene_weiterleitung` | S1 |
| `test_rolle_und_sperre_wirken_sofort`, `test_passwortwechsel_beendet_andere_sitzungen`, `test_keine_berechtigung_gibt_403` | S2, S5 |
| `test_api_rollen`, `test_anhaenge_ohne_aktive_inhalte` | S4, S3, S6 |
| `test_sammelentnahme_nicht_im_cookie_und_nicht_doppelt`, `test_rueckgaengig_umbuchung_verknuepft` | K1, B3 |
| `test_sync_robust_und_offline_kennzeichnung` | A2, Offline-Kennzeichnung |
| `test_platz_umbenennen_unbekannter_altname`, `test_wareneingang_auf_stornierte_bestellung`, `test_verbrauch_ohne_stornierte_entnahmen`, `test_entnahme_erledigt_nur_passende_reservierung` | B6, B4, B2, B5 |
| `test_import_ignoriert_trigger`, `test_echter_export_sollwerte_und_ersetzen` (mit `LV_CASPER_EXPORT`) | G4, Abschnitt 2 |
| `test_code128_pruefsumme` (6×), `test_tspl_ausgabe` (2×), `test_tspl_zu_langer_code`, `test_druckansicht_seitengroesse` | Abschnitt 6, E1–E3 |
| `test_backup_konsistent_waehrend_schreiben_und_wiederherstellung`, `test_backup_aufbewahrung_loescht_nur_alte_sicherungen` | Abschnitt 8, D2 |
| `test_konfiguration_mit_steuerzeichen_bleibt_lesbar` | W5 |
| `test_excel_export_ohne_formeln` | S8 |
| `test_mail_html_maskiert` | S9 |
| `test_zertifikate_ca_san_erneuerung_und_kein_schluessel`, `test_sql_injection_stichprobe`, `test_start_mit_leerem_datenordner` | Abschnitte 1, 5 |

**Gegenprobe:** Die 51 neuen Tests gegen den unveränderten Code 2.2.0 ergeben 31 fehlgeschlagene und 20 bestandene; die bestandenen sichern Verhalten ab, das schon in 2.2.0 korrekt war (z. B. Code-128-Prüfsumme, Zertifikate, Parallelität). Gegen 2.2.1 sind alle 60 Tests grün.

Zusätzliche Browserprüfungen (Playwright, nicht im Paket): `mobil.cjs` (19 Seiten, Scan, PWA), `offline.cjs` (16 Schritte), `pc.cjs` (136 Seitenaufrufe), Druck-PDF + zxing-cpp, Doppel-Tipp.

## Anhang C – Geänderte Dateien

`app/`: `config.py`, `db.py`, `main.py`, `web.py`, `routes/{admin,api,artikel,buchen,core,lager,mobil}.py`, `services/{betrieb,casper_import,excel,labels,lager,queries}.py`, `static/js/{offline,scan}.js`, `templates/{base,bestellungen,einstellungen}.html`, `templates/m/{base,buchen,korb,offline,wareneingang}.html`, `templates/partials/buchen_panel.html`. Dazu `windows/{DIENST_EINRICHTEN_als_Admin,ENTFERNEN,FIREWALL_FREIGEBEN_als_Admin}.bat`, `windows/Lagerverwaltung_oeffnen.vbs`, `docs/*.md` und `*.pdf`, `requirements-lock.txt`, `README.md`, `tests/test_pruefung.py` (neu) und `tests/test_lager2.py` (ungenutzter Import). `lib/` ist unverändert und bitidentisch zum Originalpaket. Der vollständige Diff steht im Git-Verlauf (Commits nach „Lagerverwaltung 2.2.0 unverändert als Prüfgrundlage“).

## Anhang A – Rollenmatrix (gemessen, v2.2.1)

„min.“ = niedrigste Rolle, die die Aktion ausführen darf. Gast ohne Anmeldung erhält 303 → Anmeldung (Web) bzw. 401 (API, `/m/sync`); eine zu niedrige Rolle erhält 403. Erwartung und Messung stimmen für alle Routen überein. In v2.2.0 abweichend: `POST /api/v1/reservierungen` (min. *lesen* statt *lager*), alle 403-Fälle als 200, `POST /m/sync` mit ungültigem Inhalt 500.

| Methode | Pfad | erwartet | 2.2.1 | 2.2.0 | Gast | lesen |
|---|---|---|---|---|---|---|
| GET | `/api/openapi.json` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/` | lesen | lesen | lesen | → Login | 200 |
| GET | `/live` | lesen | lesen | lesen | → Login | 200 |
| GET | `/scan` | lesen | lesen | lesen | → Login | 303 |
| GET | `/manifest.webmanifest` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/arbeitsplatz.bat` | lesen | lesen | lesen | → Login | 200 |
| GET | `/zertifikat.crt` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/suche` | lesen | lesen | lesen | → Login | 200 |
| GET | `/artikel` | lesen | lesen | lesen | → Login | 200 |
| POST | `/artikel/spalten` | lesen | lesen | lesen | → Login | 303 |
| GET | `/artikel/export.{fmt}` | lesen | lesen | lesen | → Login | 200 |
| GET | `/artikel/neu` | lager | lager | lager | → Login | 403 |
| POST | `/artikel/neu` | lager | lager | lager | → Login | 403 |
| GET | `/artikel/{nr}` | lesen | lesen | lesen | → Login | 200 |
| GET | `/artikel/{nr}/bearbeiten` | lager | lager | lager | → Login | 403 |
| POST | `/artikel/{nr}/bearbeiten` | lager | lager | lager | → Login | 403 |
| POST | `/artikel/{nr}/archivieren` | admin | admin | admin | → Login | 403 |
| POST | `/artikel/{nr}/anhang` | lager | lager | lager | → Login | 403 |
| GET | `/anhang/{aid}` | lesen | lesen | lesen | → Login | 200 |
| POST | `/anhang/{aid}/loeschen` | lager | lager | lager | → Login | 403 |
| GET | `/etikett/vorschau` | lesen | lesen | lesen | → Login | 200 |
| POST | `/artikel/{nr}/etikett` | lager | lager | lager | → Login | 403 |
| POST | `/etiketten/sammeldruck` | lager | lager | lager | → Login | 403 |
| GET | `/etiketten/druckansicht` | lesen | lesen | lesen | → Login | 200 |
| GET | `/buchen` | lesen | lesen | lesen | → Login | 200 |
| GET | `/buchen/panel` | lesen | lesen | lesen | → Login | 200 |
| POST | `/buchen` | lager | lager | lager | → Login | 403 |
| GET | `/bewegungen` | lesen | lesen | lesen | → Login | 200 |
| GET | `/bewegungen/export.{fmt}` | lesen | lesen | lesen | → Login | 200 |
| POST | `/bewegungen/{bid}/storno` | lager | lager | lager | → Login | 403 |
| GET | `/ausleihen` | lesen | lesen | lesen | → Login | 200 |
| POST | `/ausleihen/{bid}/rueckgabe` | lager | lager | lager | → Login | 403 |
| GET | `/reservierungen` | lesen | lesen | lesen | → Login | 200 |
| POST | `/reservierungen/neu` | lager | lager | lager | → Login | 403 |
| POST | `/reservierungen/{rid}/status` | lager | lager | lager | → Login | 403 |
| GET | `/lagerplaetze` | lesen | lesen | lesen | → Login | 200 |
| GET | `/lagerplaetze/ansicht` | lesen | lesen | lesen | → Login | 200 |
| POST | `/lagerplaetze/speichern` | lager | lager | lager | → Login | 403 |
| POST | `/lagerplaetze/zusammenfuehren` | admin | admin | admin | → Login | 403 |
| POST | `/lagerplaetze/etikett` | lager | lager | lager | → Login | 403 |
| GET | `/nachbestellung` | lesen | lesen | lesen | → Login | 200 |
| POST | `/bestellungen/anlegen` | lager | lager | lager | → Login | 403 |
| POST | `/bestellungen/einzeln` | lager | lager | lager | → Login | 403 |
| GET | `/bestellungen` | lesen | lesen | lesen | → Login | 200 |
| POST | `/bestellungen/{bid}/status` | lager | lager | lager | → Login | 403 |
| POST | `/bestellungen/lieferant/{lid}/bestellt` | lager | lager | lager | → Login | 403 |
| POST | `/bestellungen/{bid}/wareneingang` | lager | lager | lager | → Login | 403 |
| GET | `/bestellungen/export.xlsx` | lesen | lesen | lesen | → Login | 200 |
| GET | `/inventur` | lesen | lesen | lesen | → Login | 200 |
| POST | `/inventur/neu` | lager | lager | lager | → Login | 403 |
| GET | `/inventur/{iid}` | lesen | lesen | lesen | → Login | 200 |
| POST | `/inventur/{iid}/zaehlen` | lager | lager | lager | → Login | 403 |
| POST | `/inventur/{iid}/abschliessen` | admin | admin | admin | → Login | 403 |
| GET | `/inventur/{iid}/zaehlliste.xlsx` | lesen | lesen | lesen | → Login | 200 |
| GET | `/lieferanten` | lesen | lesen | lesen | → Login | 200 |
| POST | `/lieferanten/speichern` | lager | lager | lager | → Login | 403 |
| POST | `/lieferanten/{lid}/loeschen` | admin | admin | admin | → Login | 403 |
| GET | `/auswertungen` | lesen | lesen | lesen | → Login | 200 |
| GET | `/auswertungen/{art}.xlsx` | lesen | lesen | lesen | → Login | 200 |
| GET | `/einstellungen` | admin | admin | admin | → Login | 403 |
| POST | `/einstellungen/allgemein` | admin | admin | admin | → Login | 403 |
| POST | `/einstellungen/drucker` | admin | admin | admin | → Login | 403 |
| POST | `/einstellungen/mail` | admin | admin | admin | → Login | 403 |
| POST | `/einstellungen/backup` | admin | admin | admin | → Login | 403 |
| GET | `/einstellungen/backup/{name}` | admin | admin | admin | → Login | 403 |
| POST | `/einstellungen/uebernahme` | admin | admin | admin | → Login | 403 |
| POST | `/benutzer/speichern` | admin | admin | admin | → Login | 403 |
| POST | `/benutzer/{uid}/token` | admin | admin | admin | → Login | 403 |
| GET | `/passwort` | lesen | lesen | lesen | → Login | 200 |
| POST | `/passwort` | lesen | lesen | lesen | → Login | 200 |
| GET | `/import` | admin | admin | admin | → Login | 403 |
| GET | `/import/vorlage.xlsx` | admin | admin | admin | → Login | 403 |
| POST | `/import/pruefen` | admin | admin | admin | → Login | 403 |
| POST | `/import/ausfuehren` | admin | admin | admin | → Login | 403 |
| GET | `/protokoll` | admin | admin | admin | → Login | 403 |
| GET | `/m/manifest.webmanifest` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/m/sw.js` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/m/ping` | öffentlich | öffentlich | öffentlich | 200 | 200 |
| GET | `/m` | lesen | lesen | lesen | → Login | 200 |
| GET | `/m/buchen` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/buchen` | lager | lager | lager | → Login | 403 |
| POST | `/m/rueckgaengig` | lager | lager | lager | → Login | 403 |
| GET | `/m/artikel/{nr}` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/artikel/{nr}/werte` | lager | lager | lager | → Login | 403 |
| POST | `/m/artikel/{nr}/etikett` | lager | lager | lager | → Login | 403 |
| GET | `/m/platz` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/platz/etikett` | lager | lager | lager | → Login | 403 |
| GET | `/m/suche` | lesen | lesen | lesen | → Login | 200 |
| GET | `/m/neu` | lager | lager | lager | → Login | 403 |
| POST | `/m/neu` | lager | lager | lager | → Login | 403 |
| GET | `/m/korb` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/korb/neu` | lager | lager | lager | → Login | 403 |
| POST | `/m/korb/entfernen/{i}` | lesen | lesen | lesen | → Login | 303 |
| POST | `/m/korb/buchen` | lager | lager | lager | → Login | 403 |
| GET | `/m/reservierungen` | lesen | lesen | lesen | → Login | 200 |
| GET | `/m/wareneingang` | lesen | lesen | lesen | → Login | 200 |
| GET | `/m/rueckgabe` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/rueckgabe/{bid}` | lager | lager | lager | → Login | 403 |
| GET | `/m/inventur/{iid}` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/inventur/{iid}` | lager | lager | lager | → Login | 403 |
| GET | `/m/offline` | lesen | lesen | lesen | → Login | 200 |
| GET | `/m/katalog.json` | lesen | lesen | lesen | → Login | 200 |
| POST | `/m/sync` | lager | lager | lager | 401 | 403 |
| GET | `/api/v1/artikel` | lesen | lesen | lesen | 401 | 200 |
| GET | `/api/v1/artikel/{nr}` | lesen | lesen | lesen | 401 | 200 |
| GET | `/api/v1/lagerplaetze` | lesen | lesen | lesen | 401 | 200 |
| GET | `/api/v1/bewegungen` | lesen | lesen | lesen | 401 | 200 |
| POST | `/api/v1/buchungen` | lager | lager | lager | 401 | 403 |
| POST | `/api/v1/reservierungen` | lager | lager | lesen ✘ | 401 | 403 |

Abweichungen erwartet ↔ gemessen: 2.2.1 = 0.
