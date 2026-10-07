---
title: "Offene Fragen nach Phase 0"
subtitle: "Neubau Lagerverwaltung CAPHENIA"
date: "07.10.2026"
---

# Offene Fragen nach Phase 0

Zu jeder Frage steht mein **Vorschlag**. Wenn er passt, reicht ein „ok“ mit der Nummer. Fragen mit **[blockierend]** blockieren den Start von Phase 1 (Datenbankanbindung mit Schreibzugriff).

## A. Material, das noch fehlt

**A1 [blockierend] Datenbank-Dump mit Daten.** Bitte einen aktuellen HeidiSQL-Export der Datenbank `daten` (Struktur **und** Daten, alle 5 Tabellen) hochladen. Ohne ihn kann ich die Pflichtfragen aus Regel 4 (`ISTBestand`, Löschen, Duplikate, Lagerort-Spalte bei Umlagerung) nicht belegen, siehe `docs/legacy-analyse.md` Abschnitt 5 und 11. Ich spiele ihn nur lokal in die Entwicklungs-DB ein.
*Vorschlag:* Dump nicht ins Git-Repository einchecken (enthält Echtdaten). Für Tests leite ich daraus anonymisierte Testdaten ab.

**A2 [blockierend] Etikettenfoto** (45×23, gern auch 60×20) – scharf, von oben. Zusätzlich hilfreich: das alte Etikett mit dem PC-Scanner in Notepad scannen und mir den gelesenen Text schicken. Damit bestimme ich Barcodetyp und Inhalt eindeutig.

**A3 [blockierend] Handheld:** Hersteller und Modell (Typenschild auf der Rückseite), Betriebssystem (Start → Einstellungen → System → Info), und: Gibt es darauf einen Browser (Internet Explorer Mobile)?

**A4 Gibt es eine neuere Fassung von `LagerverwaltungDB2023.sql`?** Das Schema stammt von 2023. Falls seitdem etwas geändert wurde, zeigt es der Dump aus A1 ohnehin.

## B. Handheld und Synchronisation

**B1 [blockierend] Wie kommen Handheld-Buchungen in die Datenbank?** (a) sofort per WLAN, oder (b) erst beim Einstecken in die Station / Starten der Synchronisation? Wie oft wird synchronisiert?
*Indiz aus der Historie:* (b) – Umlagerungen vom Juni/Juli 2025 wurden erst am 16.07.2025 in die DB geschrieben.

**B2 [blockierend] Welche Funktionen nutzt ihr am Handheld?** Eingang, Ausgang, Umlagerung, Inventur, Artikel anlegen, Artikel suchen/anzeigen?

**B3 Umbuchung vs. Umlagerung:** Meine Auswertung ergibt: „Umbuchung“ kommt von der PC-Oberfläche, „Umlagerung“ vom Handheld. Deckt sich das mit deiner Erfahrung?
*Vorschlag:* Der Neubau bucht Ortswechsel als „Umbuchung“ (wie die alte PC-Oberfläche).

**B4 Benutzer „Sharun“:** Wo meldet sich dieser Benutzer an – am PC oder am Handheld? (18 Ausgänge am 17.02.2026, 3 Bearbeitungen am 09.10.2025.)

**B5 Lagerplatz-Barcodes:** Gibt es bereits Etiketten an den Regalen/Fächern, die am Handheld gescannt werden? Wenn ja: Was steht im Barcode (z. B. `C2-R9-2`)?

## C. Fachliche Regeln

**C1 [blockierend] Was bedeutet „Artikel löschen“ für dich?** (a) Den Artikel an *einem* Lagerort entfernen, oder (b) den ganzen Artikel mit allen Lagerorten?
*Vorschlag:* Im Neubau gibt es beides getrennt: „Lagerort entfernen“ (nur bei Bestand 0) und „Artikel löschen“ (nur bei Gesamtbestand 0, nur Admin). Das genaue Schreibformat lege ich erst nach dem Dump fest.

**C2 [blockierend] Negativer Bestand:** Darf ein Ausgang mehr ausbuchen, als am Ort liegt?
*Vorschlag:* Nein – klare Fehlermeldung mit dem vorhandenen Bestand. (Das Altsystem bucht in solchen Fällen offenbar stillschweigend „Ausgang 0“.)

**C3 Dezimalmengen:** Braucht ihr Mengen mit Komma (Meter Kabel, Liter Öl)?
*Vorschlag:* Ja, bis 3 Nachkommastellen je Artikel einstellbar über die Einheit; Standard „Stück“ ganzzahlig.

**C4 Lagerortschema:** Was bedeuten B0, C1, C2 (Gebäude/Raum?), was ist `F` in `C1-F3` (Fläche, Fachboden, Fach)? Gibt es weitere Bereiche? Ist „Technikum“ ein gültiger Lagerort?
*Vorschlag:* Schema `<Bereich>-R<Regal>-<Fach>` und `<Bereich>-F<Nr>`, plus freigegebene Sonderorte (Technikum). Neue Eingaben werden dagegen geprüft.

**C5 Unklare Altorte:** `C?` (4×), `C2-R4-3/1`, `C2-R7/8-4`, leerer Lagerort (76 Buchungen) – wie sollen die heißen? Alle übrigen Tippfehler-Zuordnungen stehen als Vorschlag in `docs/legacy-analyse.md`, Abschnitt 7.

**C6 Artikelnummern:** Was bedeuten die Nummernkreise 10001–10348 und 20001–20911? Soll der Neubau beim Anlegen die nächste freie Nummer vorschlagen – in welchem Kreis?
*Vorschlag:* Nächste freie Nummer im 20000er-Kreis vorschlagen, überschreibbar.

**C7 Freifelder:** Wofür nutzt ihr Freifeld 1–5 heute (Anzeigenamen stehen im Dump)? Einige Inhalte (z. B. Hersteller) würden im Neubau besser in eigene Felder wandern – ohne die Altdaten zu ändern.

## D. Betrieb und IT

**D1 [blockierend] Lager-PC:** Windows-Version (10/11, 64 Bit)? Hast du dort Administratorrechte (für Dienst-Installation und Firewall-Freigabe)? Läuft MySQL auf demselben PC?

**D2 [blockierend] MySQL-Zugang:** Kannst du dich am Lager-PC mit HeidiSQL als `root` (oder anderem Admin) anmelden? Den brauche ich einmalig, um den eigenen App-Benutzer mit minimalen Rechten anzulegen (ein SQL-Skript, das du selbst ausführst).

**D3 Netzwerk:** Sollen andere PCs/Tablets per Browser zugreifen? Dafür muss die IT den Port (Standard 8080) im Firmennetz freigeben. Gibt es einen festen Rechnernamen/IP?

**D4 E-Mail:** In der alten `config.ini` ist der E-Mail-Versand leer, also nie eingerichtet. Welcher Mailserver (SMTP-Host, Port, Absender, Empfänger)? Ist das ein interner Server oder Microsoft 365?
*Vorschlag:* Funktion bauen, aber erst aktivieren, wenn die Zugangsdaten vorliegen.

**D5 Drucker:** Heißt der Drucker in Windows exakt „HPRT HT100“? Welche Etikettengröße liegt aktuell ein – nur 45×23 oder auch 60×20? Ist der Godex RT700 noch irgendwo im Einsatz?

**D6 Backups:** Wohin sollen die täglichen Sicherungen (lokaler Ordner, Netzlaufwerk)?
*Vorschlag:* `D:\Lagerverwaltung\Backup` bzw. ein Netzlaufwerk, 30 Tage Aufbewahrung.

**D7 Benutzer und Rollen:** Wer bekommt welche Rolle (Admin / Lager / Nur-Lesen)? Wer ist der erste Admin?

**D8 Repository:** Darf ich die nicht-sensiblen Altdateien (Schema, `.ini`-Konfigurationen, Etikettenlayouts) im Repository unter `casper/` ablegen? Der Bewegungs-CSV-Export und das Druckerhandbuch bleiben draußen.
*Vorschlag:* Ja für Schema/Konfiguration/Layouts (habe ich so vorbereitet), nein für Echtdaten.
