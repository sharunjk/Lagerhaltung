---
title: "Legacy-Analyse Casper-Lagerverwaltung"
subtitle: "Phase 0 – Neubau der Lagerverwaltung bei CAPHENIA"
date: "07.10.2026"
---

# Legacy-Analyse Casper-Lagerverwaltung (Phase 0)

**Stand:** 07.10.2026 · **Status:** Analyse abgeschlossen, soweit mit den vorliegenden Dateien möglich. Mehrere Kernfragen lassen sich erst mit dem **Datenbank-Dump mit Daten** belegen (siehe Abschnitt 11 und `docs/offene-fragen.md`).

Legende für die Belastbarkeit der Aussagen:

| Kennzeichen | Bedeutung |
|---|---|
| **BELEGT** | Direkt aus den Dateien ablesbar oder statistisch eindeutig |
| **WAHRSCHEINLICH** | Starke Indizien, aber noch nicht am Dump bzw. am Gerät bestätigt |
| **OFFEN** | Mit den vorliegenden Dateien nicht entscheidbar |

## 1. Ausgewertete Quellen

| Datei | Inhalt | Ausgewertet |
|---|---|---|
| `LagerverwaltungDB2023.sql` | Schema der DB `daten` (HeidiSQL-Export 2023, Struktur + Inhalt von `benutzer`/`freifelder`) | ja |
| `Lagerverwaltung/Lagerverwaltung/SelektionBewegungsdaten.CSV` | Export der Bewegungshistorie, 2.578 Zeilen | ja (Skript `tools/analyse_bewegungen_csv.py`) |
| `Lagerverwaltung/Lagerverwaltung/SelektionStammdaten.CSV`, `Meldebestand.CSV`, `Mindestbestand.CSV` | Exporte | **leer (0 Byte)** |
| `Lagerverwaltung/Lagerverwaltung/config.ini` | Konfiguration der PC-Oberfläche | ja |
| `Lagerverwaltung/Lagerverwaltung/45x23.txt`, `60x20.txt` | Etikettenlayouts | ja |
| `Lagerverwaltung/MFS.mfc` | Kommunikationsprofil (Kalipso) | ja |
| `MISCommunicatorV5_32bits/*.ini`, `OEM/OEM.ini` | Konfiguration MIS Communicator | ja |
| `HeidiSQL_9.5_64_Portable/Drucker.ini` | ältere Druckerkonfiguration | ja |
| `HPRT HT100 Series User Manual_Rev.1.0.pdf` | Druckerhandbuch | ja (technische Daten) |
| **Datenbank-Dump mit Daten** | – | **fehlt noch** |
| **Foto eines alten Etiketts** | – | **fehlt noch** |
| **Modell/Betriebssystem des Handhelds** | – | **fehlt noch** |

Hinweis: Alle `.ini`-Dateien von Casper sind UTF-16LE mit BOM, die CSV-Exporte Latin-1 (ISO-8859-1) mit CRLF. Es wurden keine Casper-Binär- oder Projektdateien geöffnet, dekompiliert oder verändert.

## 2. Architektur des Altsystems

```
 Handheld (KC40/KC50, Kalipso-Runtime, Windows CE/Embedded Handheld)
        │  Synchronisation über KDriver (ToPC_ToPDA), Sync-Ordner C:\Casper\Syncro
        ▼
 MIS Communicator (Windows-Dienst, TCP 9000)  ◄──── Lagerverwaltung.exe (Kalipso, PC)
        │  ODBC (MySQL Connector/ODBC 8.0.19)            config.ini: Server 127.0.0.1:9000
        ▼
 MySQL Community Server 8.0.23, Datenbank `daten`
```

**BELEGT** aus den Konfigurationen:

- `config.ini [Server]`: `Server=127.0.0.1`, `Port=9000`, Benutzer/Passwort leer, `Encrypted=0` → die PC-Oberfläche spricht nicht direkt mit MySQL, sondern mit dem MIS Communicator.
- `Connections.ini [Connection_1]`: `Type=3`, `Port=9000`, `Timeout=10`, `Tries=3`, `CompressionLevel=4`, `MinimumTLSVersion=1.2`, `Encrypted=0`, kein Passwort → TCP-Listener des Communicators ohne Verschlüsselung.
- `Products.ini`: zwei Produkte `KC40` und `KC50`, beide mit Sync-Pfad `C:\Casper\Syncro` und Aufruf `KDriverV40\KDriver.exe` bzw. `KDriverV50\KDriver.exe ToPC_ToPDA P1 [TERMINAL] [PRODUCT] [VERSION] [USER]`, Timeout 300 s.
- `Configurations.ini`: Dienstname `MISCommunicator`, `SendDateTimeToMSS=1` (Datum/Uhrzeit wird beim Sync an das Gerät übertragen), `ODBCMaxConnections=0` (= keine Begrenzung bzw. Standard), Logging aus.
- `MFS.mfc`: `A|SYN|3|TCP/IP|3|8000|…|IP|…` – ein Kalipso-Kommunikationsprofil „SYN“ über TCP/IP mit Port **8000** (abweichend von 9000). Zweck **OFFEN** (evtl. Profil für das Handheld oder Altlast).

**WAHRSCHEINLICH:** Das Handheld arbeitet **offline mit Synchronisation** (Batch), nicht dauerhaft online. Indizien:

1. Der Aufruf `KDriver.exe ToPC_ToPDA` mit Sync-Ordner ist das klassische Muster „Daten zum PC / Daten zum PDA“.
2. In der Bewegungshistorie stehen 5 `Umlagerung`-Buchungen (Zeitstempel 12.06.–03.07.2025) *hinter* jüngeren PC-Buchungen, d. h. sie wurden **erst später in die DB geschrieben** als ihr Zeitstempel sagt (siehe 5.3). Das passt genau zu „am Gerät erfasst, später synchronisiert“.

**Konsequenz für den Neubau:** „Live-Anzeige von Handheld-Buchungen“ heißt „sobald synchronisiert“. Kritisch ist, *wie* der Sync die Tabelle `lagerorte` aktualisiert – relativ (`Anzahl = Anzahl - x`) oder absolut (Gerät überschreibt mit seinem Stand). Bei absoluter Fortschreibung würden PC-Buchungen zwischen zwei Syncs überschrieben. Das ist **OFFEN** und wird im Handheld-Testplan gezielt geprüft (Testfall „Parallelbuchung“).

## 3. Datenbankschema `daten`

Zeichensatz aller Tabellen: `utf8mb4`, Kollation `utf8mb4_0900_ai_ci`, Engine InnoDB.

### 3.1 `stammdaten` – Artikelstamm

| Spalte | Typ | Bemerkung |
|---|---|---|
| `Artikelnummer` | varchar(255) NOT NULL | PRIMARY KEY **und** zusätzlich UNIQUE KEY `Artikelnummer` (redundanter Index) |
| `Bezeichnung` | varchar(255) | |
| `Meldebestand` | varchar(255) | **Zahl als Text** |
| `Mindestbestand` | varchar(255) | **Zahl als Text** |
| `Freifeld1` … `Freifeld5` | varchar(255) | Anzeigename aus `freifelder` |

Kein Bestand in dieser Tabelle – der Bestand steht ausschließlich in `lagerorte`.

### 3.2 `lagerorte` – Bestand je Lagerort

| Spalte | Typ | Bemerkung |
|---|---|---|
| `Artikel` | varchar(255) | entspricht `stammdaten.Artikelnummer` (kein Fremdschlüssel) |
| `Lagerort` | varchar(255) | Freitext |
| `Anzahl` | decimal(10,3) | Bestand an diesem Ort, 3 Nachkommastellen |

**Kein Primärschlüssel, kein Index.** Duplikate (`Artikel`, `Lagerort`) sind technisch möglich. Für den Neubau heißt das: Zeilensperren per `SELECT … FOR UPDATE` müssen einen Full Table Scan machen und sperren dabei faktisch alle gelesenen Zeilen. Bei der Tabellengröße (geschätzt < 2.000 Zeilen) ist das unkritisch, aber es serialisiert Buchungen – das ist hier sogar erwünscht. Einen Index anlegen dürfen wir nicht (Regel 1).

### 3.3 `bewegungsdaten` – Historie

| Spalte | Typ | Bemerkung |
|---|---|---|
| `Artikelnummer` | varchar(255) | |
| `Lagerort` | varchar(50), Default `''` | **nur 50 Zeichen** (in `lagerorte` 255) |
| `ISTBestand` | double | Bedeutung siehe 5.1 |
| `Zeit` | varchar(255) | `HH:MM:SS` |
| `Datum` | varchar(255) | `TT.MM.JJJJ` |
| `EingangAusgang` | varchar(255) | Aktionstext |
| `Benutzer` | varchar(255) | |
| `ID` | int AUTO_INCREMENT, PK | einziger verlässlicher Sortierschlüssel |

Die `Bezeichnung` steht **nicht** in `bewegungsdaten`; der CSV-Export holt sie per Join aus `stammdaten`. Bei gelöschten Artikeln ist sie im Export trotzdem vorhanden – entweder wird der Export vor dem Löschen erzeugt oder der Artikel existiert weiter (siehe 5.3).

### 3.4 `freifelder` – Spaltenkonfiguration

11 Zeilen. Jede Zeile enthält in `Freifeld1`–`Freifeld5` die Anzeigenamen der Freifelder (in jeder Zeile identisch, Stand 2023: Standardnamen „Freifeld1“ … „Freifeld5“) und in `Felder`/`Nummer` die **Spaltenreihenfolge** der Artikeltabelle:

| Nummer | Felder |
|---|---|
| 1 | Artikelnummer |
| 2 | Bezeichnung |
| 3 | Lagerort |
| 4 | ISTBestand |
| 5 | Meldebestand |
| 6 | Mindestbestand |
| 7–11 | Freifeld1 … Freifeld5 |

Die Spaltenreihenfolge zeigt: Die Artikeltabelle der alten Oberfläche ist **zeilenweise je Lagerort** aufgebaut (Spalten Lagerort und ISTBestand) – eine „Artikelzeile“ im Altsystem entspricht damit vermutlich einer `lagerorte`-Zeile. Das ist wichtig für die Deutung von „Neuer Artikel“/„Artikel gelöscht“ (5.3, 5.4).

Ob die Kalipso-App die Anzeigenamen aus der ersten Zeile oder aus allen Zeilen liest, ist **OFFEN**; der Neubau schreibt bei Umbenennung alle 11 Zeilen gleich (so wie im Bestand).

### 3.5 `benutzer`

Stand 2023: eine Zeile `('Administrator', NULL)`, Passwort im Klartext. In der Historie taucht zusätzlich der Benutzer **„Sharun“** auf (21 Buchungen, siehe 6.2) – der aktuelle Inhalt der Tabelle ist daher **OFFEN**.

### 3.6 Kollation – wichtig für Lagerorte

`utf8mb4_0900_ai_ci` ist **akzent- und groß-/kleinschreibungs-unempfindlich**. `WHERE Lagerort = 'technikum'` findet also auch `Technikum`. Für die Kalipso-App (und für uns) sind `technikum`/`Technikum` beim Suchen identisch, beim Gruppieren mit `GROUP BY` ebenfalls. Die Kollation ist `NO PAD`: `'C2-F1 '` (mit Leerzeichen) ≠ `'C2-F1'`. Der Neubau muss sich bei Vergleichen genauso verhalten wie MySQL (Vergleiche in SQL, nicht in Python).

## 4. CSV-Export `SelektionBewegungsdaten.CSV`

**BELEGT:**

- 2.578 Zeilen, alle mit genau 7 Feldern, **keine Kopfzeile**, Trenner `;`, Latin-1, CRLF.
- Spalten: `Artikelnummer;Bezeichnung;Menge;Aktion;Benutzer;Datum;Zeit`.
- **Die Spalte `Lagerort` fehlt im Export.** Damit ist aus dem CSV allein nicht ablesbar, an welchem Ort gebucht wurde – nur bei Umbuchung/Umlagerung steht der Ort im Aktionstext.
- Mengen sind ganzzahlig, mit Vorzeichen (`-1`), ohne Nachkommastellen (keine Dezimalwerte im Export).
- Zeitraum: 28.03.2025 09:51:49 bis 02.10.2026 09:06:08.
- Reihenfolge: neueste zuerst (vermutlich nach `ID` absteigend, siehe 5.3).
- `Datum` immer `TT.MM.JJJJ`, `Zeit` immer `HH:MM:SS` mit führenden Nullen – keine einzige Abweichung.
- Benutzer: `Administrator` 2.557×, `Sharun` 21×.

Aktionen:

| Aktion | Anzahl | davon Menge < 0 | davon Menge = 0 |
|---|---:|---:|---:|
| Neuer Artikel | 838 | 0 | 14 |
| Ausgang | 668 | 642 | 26 |
| Umbuchung (…) | 390 | 189 | 12 |
| Artikel bearbeitet | 382 | 0 | 41 |
| Artikel gelöscht | 202 | 1 | 160 |
| Eingang | 56 | 0 | 0 |
| Umlagerung (… -> …) | 36 | 18 | 0 |
| Inventur (… -> …) | 6 | 0 | 4 |

Die exakten Aktionstexte (inklusive Leerzeichen und `->`):

- `Eingang`, `Ausgang`, `Neuer Artikel`, `Artikel bearbeitet`, `Artikel gelöscht`
- `Umbuchung (<Lagerort>)` – z. B. `Umbuchung (C2-R2-4)`, auch `Umbuchung ()` bei leerem Ort
- `Umlagerung (<von> -> <nach>)` – z. B. `Umlagerung (C2-R1-0 -> C2-F1)`, auch `Umlagerung ( -> C1-F3)` bei leerem Quellort
- `Inventur (<alt> -> <neu>)` – z. B. `Inventur (1 -> 1)`, `Inventur ( -> 1)` bei leerem Altwert

## 5. Antworten auf die Pflichtfragen (Regel 4)

### 5.1 Ist `ISTBestand` die bewegte Menge oder der resultierende Bestand?

Annahme für diese Auswertung: Die CSV-Spalte „Menge“ ist `bewegungsdaten.ISTBestand` (**WAHRSCHEINLICH**, am Dump zu bestätigen).

| Aktion | Bedeutung von `ISTBestand` | Beleg | Status |
|---|---|---|---|
| Eingang | **bewegte Menge, positiv** | 56× positiv (1, 2, 3), nie 0 | BELEGT |
| Ausgang | **bewegte Menge, negativ** | 642× negativ (`-1`…`-4`); ein resultierender Bestand könnte nicht negativ sein | BELEGT |
| Umbuchung / Umlagerung | **bewegte Menge je Zeile**: `-x` am Quellort, `+x` am Zielort | immer Paare mit gleichem Betrag und entgegengesetztem Vorzeichen | BELEGT |
| Inventur | **Differenz neu − alt** | `Inventur (1 -> 1)` → `0`; `Inventur ( -> 1)` → `1` | BELEGT (nur 6 Fälle) |
| Neuer Artikel | **Anfangsbestand** der neuen Zeile | 838× ≥ 0; danach passen die Deltas | WAHRSCHEINLICH |
| Artikel bearbeitet | **Bestand zum Zeitpunkt der Bearbeitung** (absolut, kein Delta) | in 339 von 382 Fällen exakt gleich dem aus allen Deltas rekonstruierten Gesamtbestand des Artikels; Abweichungen fast nur bei Artikeln mit mehreren Lagerorten/Löschungen | WAHRSCHEINLICH |
| Artikel gelöscht | **Bestand der gelöschten Zeile** oder 0 | 160× `0`, 41× `1`, 1× `-1`; passt nur in 59 von 202 Fällen zum Gesamtbestand → eher Bestand *eines* Lagerorts | OFFEN |

**Fazit:** `ISTBestand` ist trotz des Namens bei allen **Buchungen** die **vorzeichenbehaftete bewegte Menge**. Nur bei den Stammdaten-Aktionen steht dort ein absoluter Wert. Der Neubau schreibt es genauso.

Auffällig: **26× `Ausgang` mit Menge 0.** Wahrscheinlichste Erklärung: Ausbuchung an einem Lagerort mit Bestand 0 – das Altsystem kappt auf den vorhandenen Bestand und protokolliert die tatsächlich bewegte Menge 0 (statt einer Fehlermeldung). Mit dem Dump prüfbar (Lagerort der Zeile + Bestand davor).

### 5.2 Unterschied zwischen „Umbuchung“ und „Umlagerung“

Beide verschieben Bestand von einem Ort zum anderen und erzeugen **zwei Zeilen** mit gleicher Zeit (`-x` und `+x`). Der Unterschied liegt im Aktionstext und in der Herkunft:

| | Umbuchung | Umlagerung |
|---|---|---|
| Zeilen | 2 (195 Paare; davon 14 über eine Sekundengrenze verteilt, z. B. `09:55:06` / `09:55:07`) | 2 (18 Paare, immer gleiche Sekunde) |
| Aktionstext | **jede Zeile trägt ihren eigenen Ort**: `-1 Umbuchung (C2-F1)` und `+1 Umbuchung (C2-R2-4)` | **beide Zeilen tragen denselben Text** `Umlagerung (C2-R1-0 -> C2-F1)` |
| Reihenfolge | erst `-x` (Quelle), dann `+x` (Ziel) | `-1` und `+1` in derselben Sekunde |
| Zeitraum | 11.04.2025 – 30.09.2026 (laufend genutzt) | 08.04.2025 – 16.07.2025 (seitdem nicht mehr) |
| Später eingefügt? | nein | **ja** – 5 Paare stehen in der ID-Reihenfolge hinter jüngeren Buchungen |
| Typische Fehler | Tippfehler mit gedrückter Umschalttaste (`C!-F§`, `C"-R1-1`, `C2-R(-0`) → **Tastatureingabe** | Artikelnummer als Zielort (`C1-R1-1 -> 10343`) → **Scanfehler** |

**WAHRSCHEINLICH:** *Umbuchung* ist die Funktion der **PC-Oberfläche**, *Umlagerung* die Funktion des **Handhelds** (Erfassung offline, Übertragung beim Sync). Die Inventur-Buchungen vom 16.07.2025 fallen in dasselbe Sync-Fenster und stammen vermutlich ebenfalls vom Handheld.

**Konsequenz:** Der Neubau bucht Ortswechsel am PC als **„Umbuchung“** (zwei Zeilen, je eigener Ort, erst Quelle dann Ziel). „Umlagerung“ wird gelesen und angezeigt, aber vom PC nicht erzeugt. Offen ist noch, welcher Wert in der Spalte `Lagerort` der beiden Umlagerungszeilen steht (Dump).

### 5.3 „Artikel gelöscht“ – wie sehen die Einträge aus, wird `lagerorte` bereinigt?

**BELEGT aus dem CSV:**

- 202 Einträge für 151 Artikelnummern; **24 Artikel wurden mehrfach „gelöscht“** (Artikel 10216 z. B. 25×).
- **121 Artikel haben nach einem „Artikel gelöscht“ weitere Buchungen** (Ausgang, Eingang, Bearbeitung) – teils ohne erneutes „Neuer Artikel“ dazwischen. Beispiel 10221: `Ausgang 0` → `Artikel gelöscht 1` → `Ausgang 0` → `Artikel gelöscht 1` → … → `Artikel bearbeitet 1`.
- 17 Artikelnummern wurden mehrfach mit „Neuer Artikel“ angelegt.
- Die Bezeichnung ist je Artikelnummer über die gesamte Historie identisch (0 Artikel mit mehr als einer Bezeichnung).

**WAHRSCHEINLICH:** „Artikel gelöscht“ bedeutet im Altsystem **das Löschen einer Artikel-*Zeile*, also einer `lagerorte`-Zeile (Artikel an einem Lagerort)**, nicht zwingend des Stammsatzes. Ebenso legt „Neuer Artikel“ vermutlich eine neue `lagerorte`-Zeile an (und den Stammsatz nur, wenn er fehlt). Das erklärt die vielen Lösch-/Neuanlage-Folgen mit weiterlaufender Historie und passt zur zeilenweisen Artikeltabelle (3.4). Die Menge wäre dann der Bestand der gelöschten Zeile.

**OFFEN (nur mit Dump klärbar):**

- Existiert der `stammdaten`-Satz nach „Artikel gelöscht“ weiter, wenn noch andere Lagerorte vorhanden sind? Und wenn nicht?
- Bleibt die `lagerorte`-Zeile stehen (mit `Anzahl` 0) oder wird sie gelöscht?
- Was steht in `bewegungsdaten.Lagerort` bei „Artikel gelöscht“?

Bis das belegt ist, wird **keine Löschfunktion** gebaut, die in Legacy-Tabellen schreibt.

### 5.4 Wie entstehen mehrere `lagerorte`-Zeilen pro Artikel, gibt es Duplikate?

**WAHRSCHEINLICH** entstehen weitere Zeilen durch:

1. **Umbuchung/Umlagerung an einen neuen Ort** (Zielort hat noch keine Zeile → INSERT).
2. **„Neuer Artikel“ mit bereits existierender Artikelnummer** an einem weiteren Ort (17 Fälle).

Ob nach einer vollständigen Umbuchung die Quellzeile mit `Anzahl = 0` stehen bleibt, und ob es **Duplikate** (gleicher Artikel + gleicher Ort mehrfach, auch durch Groß-/Kleinschreibung wie `technikum`/`Technikum`) gibt, ist **OFFEN** und wird mit den Abfragen in `tools/legacy_dump_checks.sql` am Dump geprüft.

## 6. Weitere Befunde aus der Historie

### 6.1 Zwei Erfassungsquellen parallel

Am 28.03.2025 (Erstbefüllung) wurden zwei Nummernkreise **gleichzeitig** angelegt: 10001–10070 und 10200–10250. In der ID-Reihenfolge wechseln sie sich ab, die Uhrzeiten springen dabei um bis zu 15 Minuten zurück (9 Reihenfolge-Sprünge). Das spricht für **zwei Geräte/Clients mit unterschiedlich gehenden Uhren oder Zwischenspeicherung** – z. B. PC + Handheld oder zwei PCs.

### 6.2 Benutzer „Sharun“

21 Buchungen als `Sharun`: 18× `Ausgang` am 17.02.2026 (11:38–16:13) und 3× `Artikel bearbeitet` am 09.10.2025. Alles andere als `Administrator`. Wo dieser Benutzer angemeldet war (PC-Login oder Handheld), ist **OFFEN**.

### 6.3 Artikelnummern

- 821 verschiedene Nummern, Bereiche **10001–10348** und **20001–20911** (fortlaufend, 5-stellig).
- Ausreißer: `09052025` („CAPHENIA Tasse“) – offenbar ein Datum als Nummer, mit führender Null. Muss als String behandelt werden (Zahl würde die `0` verlieren).
- Rund 790 Nummern sind nach der Historie aktuell vermutlich aktiv (nicht als letzte Aktion gelöscht).

### 6.4 Mengen

- Fast nur Stückzahlen 1–4; keine Dezimalwerte im Export. `lagerorte.Anzahl` erlaubt 3 Nachkommastellen, `ISTBestand` ist `double`. Ob Dezimalmengen (z. B. Meter, Liter) gebraucht werden, ist eine Frage an dich.
- In der Rekonstruktion aus Deltas wird genau ein Artikel negativ (10315, `-1`) – wahrscheinlich weil der Anfangsbestand vor dem Exportzeitraum liegt oder über „Artikel bearbeitet“ gesetzt wurde.

### 6.5 Nutzungsintensität

Monatliche Buchungszeilen: Spitzen 07/2025 (580) und 10/2025 (348), seit 04/2026 deutlich ruhiger (5–42 pro Monat). Die Last ist für MySQL vernachlässigbar.

## 7. Lagerortschema

**BELEGT:** In Aktionstexten kommen 66 verschiedene Orte vor, davon 53 im Schema:

```
<Bereich>-R<Regal>-<Fach>   z. B. C2-R9-2   (Regal 1–9, Fach 0–4)
<Bereich>-F<Nummer>         z. B. C1-F3     (F = Fläche/Fachboden? → Frage)
Bereiche: C2 (32 Orte), C1 (18), B0 (3)
```

Vorschlag Validierungsregel für neue Eingaben: `^[A-Z][0-9]-(R[0-9]+-[0-9]+|F[0-9]+)$` plus eine Liste freigegebener Sonderorte (z. B. „Technikum“).

**Abweichende Varianten und Vorschlag für `lv_lagerort_alias`** (nur Zuordnung, Altdaten werden nicht geändert):

| Variante | Vorkommen | Vermutete Ursache | Vorschlag Zuordnung |
|---|---:|---|---|
| *(leer)* | 76 | Ort nicht angegeben | „ohne Lagerort“ (eigener Eintrag, keine Zuordnung) |
| `Technikum` | 6 | Sonderort | Sonderort `Technikum` freigeben |
| `technikum` | 1 | Kleinschreibung | → `Technikum` |
| `C!-F§` | 1 | Umschalttaste gedrückt (`!`=1, `§`=3) | → `C1-F3` |
| `C"-R1-1` | 1 | Umschalttaste (`"`=2) | → `C2-R1-1` |
| `C2-R(-0` | 1 | Umschalttaste (`(`=8) | → `C2-R8-0` |
| `C1R4-3` | 1 | Bindestrich fehlt | → `C1-R4-3` |
| `C2-R6-01` | 2 | führende Null | → `C2-R6-1` |
| `C?` | 4 | unvollständig (`?` = Umschalt+ß) | **keine Zuordnung möglich** – Frage |
| `C2-R4-3/1` | 1 | Unterteilung? | Frage |
| `C2-R7/8-4` | 4 | Ort über zwei Regale | Frage (später nach `C2-R7-4` umgelagert) |
| `10343` | 2 | Artikelnummer als Ort gescannt | **keine Zuordnung** – Datenfehler |
| `VV 3061 10` | 2 | Bezeichnung als Ort eingegeben | **keine Zuordnung** – Datenfehler |

Die vollständige Liste der Orte in `lagerorte` (inkl. Orten ohne Umbuchung) kommt erst aus dem Dump.

## 8. Konfiguration der PC-Oberfläche (`config.ini`)

| Abschnitt | Schlüssel | Wert | Deutung |
|---|---|---|---|
| Sonstiges | `Farbe` | `000000204` | Windows-COLORREF 204 = `0x0000CC` = Rot – vermutlich Markierungsfarbe für Artikel unter Meldebestand (WAHRSCHEINLICH) |
| Tabelle | `Feld1`–`Feld5` | 1,1,1,1,0 | Freifeld 1–4 sichtbar, 5 ausgeblendet |
| Tabelle | `checked1`–`checked5` | 1,1,1,1,0 | dito (Checkbox-Zustand im Dialog) |
| Tabelle | `Spalten` | 8 | Anzahl sichtbarer Spalten (Bedeutung OFFEN, evtl. 4 Basisspalten + 4 Freifelder) |
| Sprache | `Sprache` | Deutsch | |
| E-Mail | Empfänger, Absender, Benutzer, Passwort, Postausgangsserver, Port | **alle leer** | E-Mail-Versand ist **nicht eingerichtet** |
| E-Mail | `SSL` | 0 | |
| Server | `Server`/`Port` | 127.0.0.1 / 9000 | MIS Communicator |
| Druck | `Direkt` | 1 | Direktdruck ohne Dialog |
| Druck | `Size` | `45x23` | aktive Etikettengröße |
| Druck | `Name` | `HPRT HT100` | Windows-Druckername |

`HeidiSQL_9.5_64_Portable/Drucker.ini`: `Drucker=Godex RT700` – ältere Druckerkonfiguration (Godex, EZPL).

## 9. Etikettenlayouts

Die Layoutdateien sind UTF-16LE und nutzen eine Kalipso-eigene Tag-Sprache. Einheit ist **Millimeter** (abgeleitet: Werte passen exakt zu den Etikettengrößen und ergeben zentrierte Barcodes).

### 9.1 Gemeinsame Kopfzeilen

| Tag | Wert | Deutung |
|---|---|---|
| `<NI 1>` | 1 | Anzahl Etiketten je Auftrag |
| `<PP 45 23 0 0 0 0>` / `<PP 60 20 0 0 0 0>` | Breite, Höhe, Ränder | Etikettengröße in mm |
| `<PI "Lagerverwaltung">` | | Druckauftragsname |
| `<DM "YYYY-MM-DD">`, `<HM "HH:MM:SS">`, `<DS ".">`, `<TS "">` | | Datums-/Zeitformat, Dezimal-/Tausendertrenner |
| `<FN "Arial">`, `<FS 8>` / `<FS 10>` | | Schrift Arial 8 pt (45×23) bzw. 10 pt (60×20) |
| `<FC 000000000>`, `<BD 0>`, `<UN 0>`, `<IT 0>`, `<ST 0>` | | schwarz, nicht fett/unterstrichen/kursiv/durchgestrichen |
| `<EF>` | | Ende |

### 9.2 Barcode `<IB …>`

| | 45×23 | 60×20 |
|---|---|---|
| Rohdaten | `<IB 0 0 1 6 2 33 11 1 2 3 0 0 -1 1>` | `<IB 0 0 1 7 2 46 8 1 2 3 0 0 -1 1>` |
| x (4. Wert) | 6 mm | 7 mm |
| y (5. Wert) | 2 mm | 2 mm |
| Breite (6. Wert) | 33 mm | 46 mm |
| Höhe (7. Wert) | 11 mm | 8 mm |
| Zentrierung | (45 − 33) / 2 = **6** ✔ | (60 − 46) / 2 = **7** ✔ |

Die Werte 1–3 (`0 0 1`) sind vermutlich Drehung/Seite/Datenfeld (Feld 1 = Artikelnummer), die Werte 8–14 (`1 2 3 0 0 -1 1`) codieren Barcodetyp, Modulbreite/Verhältnis, Klartext und Prüfziffer. **Barcodetyp und -inhalt sind ohne Etikettenfoto nicht sicher bestimmbar (OFFEN).** Plausibel ist Code 128 oder Code 39 mit der Artikelnummer als Inhalt und ohne Klartextzeile unter dem Barcode (der Text steht ja separat darunter).

### 9.3 Textzeilen `<CA …>`

| | 45×23 | 60×20 |
|---|---|---|
| Zeile 1 | `<CA 0 1 N C 0 14 45 -1>` → Feld 1 (Artikelnummer), normal, **zentriert**, x 0, **y 14 mm**, Breite 45 mm | `<CA 0 1 N C 0 11 60 -1>` → y **11 mm**, Breite 60 mm |
| Zeile 2 | `<CA 0 2 N C 0 18 45 -1>` → Feld 2 (Bezeichnung), y **18 mm** | `<CA 0 2 N C 0 15 60 -1>` → y **15 mm** |

### 9.4 Umrechnung für TSPL bei 203 dpi (8 Punkte/mm)

| Element | 45×23 (Punkte) | 60×20 (Punkte) |
|---|---|---|
| Etikett | 360 × 184 | 480 × 160 |
| Barcode x / y / Breite / Höhe | 48 / 16 / 264 / 88 | 56 / 16 / 368 / 64 |
| Text 1 y | 112 | 88 |
| Text 2 y | 144 | 120 |
| Schrifthöhe | 8 pt ≈ 2,8 mm ≈ 23 Punkte | 10 pt ≈ 3,5 mm ≈ 28 Punkte |

Achtung: Ein Code 128 mit 5 Ziffern ist bei Modulbreite 2 Punkte nur ca. 20–23 mm breit; die Kalipso-Angabe „Breite 33 mm“ ist ein Rahmen. Für den originalgetreuen Nachbau wird die Modulbreite so gewählt, dass der Barcode im Rahmen zentriert ist, und am Foto abgeglichen. Zentrierte Arial-Texte werden in TSPL als Bitmap gerendert (`BITMAP`), weil die internen TSPL-Schriften kein Arial haben und die HT100-„TSPL Simulation“ nicht sicher alle Textausrichtungsbefehle unterstützt.

## 10. Hardware

**Etikettendrucker HPRT HT100** (Handbuch Rev. 1.0, BELEGT): Thermotransfer/Thermodirekt, **203 dpi (8 Punkte/mm)**, Befehlssprache **„TSPL Simulation“**, Schnittstellen **USB, RS-232C, Ethernet** (Standard), Windows-Treiber von Seagull (Win 7/8/10). → RAW-TSPL über den Windows-Spooler (`win32print`) ist der Weg; Ethernet (RAW-Port 9100) später möglich.

**Godex RT700** (früher): 203 dpi, EZPL – im Druckerprofil-Konzept als zweiter Treiber vorgesehen, nicht im MVP.

**Handheld:** Produktcodes KC40/KC50 (Casper-Bezeichnungen), DLLs deuten auf Windows CE / Windows Embedded Handheld. Hersteller, Modell, Browser und Scanner-Engine **OFFEN**.

**PC-Handscanner:** keine Konfiguration im Altsystem gefunden → läuft vermutlich als Tastatur (Keyboard Wedge). Suffix (Enter/Tab) **OFFEN**.

## 11. Abfragen für den Dump (`tools/legacy_dump_checks.sql`)

Sobald der Dump vorliegt, spiele ich ihn in die lokale Entwicklungs-DB ein (nie in Produktion) und beantworte mit `tools/legacy_dump_checks.sql` (nur `SELECT`) die offenen Punkte:

1. Bedeutung von `ISTBestand` je Aktion inkl. Spalte `Lagerort`.
2. Werte von `bewegungsdaten.Lagerort` bei Umbuchung, Umlagerung, Inventur, Neuer Artikel, Artikel gelöscht.
3. Gibt es nach „Artikel gelöscht“ noch `stammdaten`- und `lagerorte`-Zeilen?
4. Duplikate in `lagerorte` (exakt und unter Kollation), Zeilen mit `Anzahl = 0`, negative Bestände, Waisen ohne Stammsatz, Artikel ohne Lagerort.
5. Nicht-numerische Melde-/Mindestbestände.
6. Abgleich: Summe der Deltas je Artikel/Ort ↔ `lagerorte.Anzahl`.
7. Aktueller Inhalt von `benutzer` und `freifelder`.
8. Zeichensatzprüfung (Umlaute korrekt oder doppelt kodiert durch ODBC).

## 12. Folgerungen für den Neubau (Entwurf, erst nach Freigabe)

**Schreibformat (vorläufig, wird nach Dump-Analyse bestätigt oder korrigiert):**

| Vorgang | `bewegungsdaten` | `lagerorte` |
|---|---|---|
| Eingang x an Ort L | 1 Zeile: `ISTBestand = +x`, `EingangAusgang = 'Eingang'`, `Lagerort = L` | `Anzahl += x` (Zeile anlegen, falls fehlt) |
| Ausgang x an Ort L | 1 Zeile: `ISTBestand = -x`, `'Ausgang'` | `Anzahl -= x`; kein negativer Bestand (Fehlermeldung statt stiller Kappung) |
| Umbuchung x von A nach B | 2 Zeilen, erst `-x` mit `'Umbuchung (A)'`, dann `+x` mit `'Umbuchung (B)'`, gleiche Zeit | A `-= x`, B `+= x` |
| Inventur an Ort L, alt a → neu n | 1 Zeile: `ISTBestand = n - a`, `'Inventur (a -> n)'` | `Anzahl = n` |
| Neuer Artikel | 1 Zeile mit Anfangsbestand, `'Neuer Artikel'` | Zeile mit Anfangsbestand |
| Artikel bearbeitet | 1 Zeile mit aktuellem Bestand, `'Artikel bearbeitet'` | unverändert |
| Artikel gelöscht | **erst nach Dump-Analyse** | **erst nach Dump-Analyse** |

Allgemein: `Datum = TT.MM.JJJJ`, `Zeit = HH:MM:SS` (Ortszeit des Lager-PCs), `Benutzer` = Login-Name, Mengen ohne unnötige Nachkommastellen, Melde-/Mindestbestand als String ohne Tausendertrenner. Alle Schreibvorgänge in **einer Transaktion** mit `SELECT … FOR UPDATE` auf die betroffenen `lagerorte`-Zeilen; Bestände nie cachen.

**Risiken:**

1. **Sync-Semantik des Handhelds** (absolut vs. relativ) – höchstes Risiko, wird im Testplan zuerst geprüft.
2. Unbekannte Lese-Erwartungen der Kalipso-App (z. B. Lagerort-Zeilen mit Anzahl 0, Reihenfolge, Leerzeichen). Der Neubau schreibt deshalb so „unauffällig“ wie möglich im Altformat.
3. `bewegungsdaten.Lagerort` ist nur 50 Zeichen lang – Lagerortnamen im Neubau auf 50 Zeichen begrenzen.
4. Uhrzeit: PC und Handheld müssen dieselbe Zeit haben (`SendDateTimeToMSS=1` sorgt beim Sync dafür).
