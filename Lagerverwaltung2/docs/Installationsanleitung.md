# Lagerverwaltung 2.2 – Installation

Eigenständige Lagerverwaltung mit eigener Datenbank. Sie braucht weder Casper noch MySQL noch den MIS Communicator. Die bisherigen Daten werden einmalig aus einem HeidiSQL-Export übernommen. Dauer: etwa 20 Minuten.

## Was Sie brauchen

- Das Paket `Lagerverwaltung_v2.2.zip`
- Die Datei **python-3.12.10-embed-amd64.zip** von python.org (*Downloads → Windows → Python 3.12.10 → „Windows embeddable package (64-bit)“*). Keine Installation, keine Adminrechte nötig.
- Den SQL-Export der Casper-Datenbank (HeidiSQL → Rechtsklick auf `daten` → *Datenbank als SQL exportieren*, Daten: „Einfügen“). Frisch exportieren, damit die letzten Buchungen enthalten sind.
- Für Handscanner/Smartphones und andere PCs: einmalig Adminrechte für die Firewall-Freigabe (IT)

Die Lagerverwaltung kann auf dem bisherigen Lager-PC oder auf jedem anderen Windows-PC laufen, der dauerhaft eingeschaltet ist.

## 1. Installieren

1. `Lagerverwaltung_v2.2.zip` nach `C:\` entpacken. Es entsteht `C:\Lagerverwaltung2`.
2. `python-3.12.10-embed-amd64.zip` **ungeöffnet** in `C:\Lagerverwaltung2` legen.
3. Doppelklick auf `windows\1_EINRICHTEN.bat`. Erwartet: `OK: Lagerverwaltung ist startbereit.`
4. Rechtsklick auf `windows\FIREWALL_FREIGEBEN_als_Admin.bat` → *Als Administrator ausführen* (für Handscanner, Smartphones und andere PCs).
5. Doppelklick auf das neue Symbol **Lagerverwaltung** auf dem Desktop (auch im Startmenü). Die Lagerverwaltung öffnet sich als eigenes Programmfenster – ohne Adressleiste und Browser-Tabs. Beim ersten Mal startet sie dabei im Hintergrund, das dauert ein paar Sekunden.

## 2. Ersten Administrator anlegen

Beim ersten Aufruf erscheint *Ersten Administrator anlegen*. Benutzername und Passwort wählen (z. B. „Sharun“).

## 3. Daten aus Casper übernehmen

1. *Einstellungen → Datenübernahme* öffnen.
2. Die SQL-Exportdatei auswählen, **Übernahme starten**.
3. Ergebnis prüfen: Anzahl Artikel, Lagerplätze, Gesamtbestand, Buchungen und Hinweise (z. B. zusammengeführte Lieferanten-Schreibweisen, Lagerplätze außerhalb des Schemas, Bestand ohne Lagerplatz auf `OHNE-PLATZ`).

Übernommen werden: Artikel (Freifeld „Lieferant“ → Lieferant, „Gruppe“ → Gruppe, „Typenbezeichnung“ → Typ, „Austragungsgrund“ → Notiz), Lagerplätze mit Beständen, die komplette Buchungshistorie und die Benutzernamen. Benutzer aus dem Altsystem sind danach gesperrt und ohne Passwort – unter *Einstellungen → Benutzer* anklicken, Passwort vergeben, „Aktiv“ anhaken.

Muss die Übernahme wiederholt werden (z. B. mit einem neueren Export), „Vorhandene Daten ersetzen“ anhaken. Vorher wird automatisch gesichert.

## 4. Etikettendrucker

*Einstellungen → Etikettendrucker*: Modus *Windows-Drucker (USB)*, Druckername genau wie in Windows (vermutlich „HPRT HT100“), **Speichern und Testetikett drucken**. Sitzt der Druck schief, Versatz in mm anpassen. Hängt der Drucker am Netzwerk: Modus *Netzwerk*, IP-Adresse, Port 9100.

Falls der Direktdruck nicht klappt: Bei jedem Etikett gibt es „Über den Browser drucken“ – das nutzt den normalen Windows-Druckertreiber.

## 5. Handscanner und Smartphones

Siehe Anleitung *Zebra TC21 einrichten*. Kurz: *Einstellungen → Handscanner / Handy* zeigt Adressen und QR-Codes. Pro Gerät einmal das Zertifikat installieren, die App öffnen, „App installieren“ tippen, DataWedge prüfen. Bitten Sie die IT, dem Lager-PC eine feste IP-Adresse zu geben.

## 6. Als Programm auf dem Desktop

Die Lagerverwaltung besteht aus zwei Teilen: dem **Hintergrunddienst** auf dem Lager-PC (Datenbank, Handscanner, Drucker) und dem **Programmfenster**.

- Das Symbol *Lagerverwaltung* startet bei Bedarf den Hintergrunddienst und öffnet das Fenster (über Microsoft Edge im App-Modus, auf jedem Windows 10/11 vorhanden). Rechtsklick auf das Symbol in der Taskleiste → *An Taskleiste anheften*.
- Fenster schließen beendet nur das Fenster. Der Hintergrunddienst läuft weiter, damit Handscanner und andere PCs weiterarbeiten können.
- Verknüpfung verloren? `windows\VERKNUEPFUNG_ERSTELLEN.bat` legt sie neu an.

**Weitere Büro-PCs:** Dort wird nichts installiert. Unter *Einstellungen → Allgemein → „Verknüpfung für Arbeitsplatz-PCs herunterladen“* gibt es ein kleines Skript; auf dem jeweiligen PC doppelklicken – danach hat auch dieser PC ein Symbol *Lagerverwaltung*, das die Lagerverwaltung des Lager-PCs als eigenes Fenster öffnet.

## 7. Dauerbetrieb

- **Ohne Adminrechte:** `windows\3_AUTOSTART_EIN.bat` – startet unsichtbar bei jeder Anmeldung am PC.
- **Mit Adminrechten (empfohlen):** Rechtsklick auf `windows\DIENST_EINRICHTEN_als_Admin.bat` → *Als Administrator ausführen* – startet beim Hochfahren, auch ohne Anmeldung.

## 8. Umstieg

1. Ein paar Tage parallel testen: in der neuen Lagerverwaltung buchen, die alte nur noch ansehen.
2. Stichtag festlegen: Casper-Datenbank frisch exportieren, unter *Datenübernahme* mit „Vorhandene Daten ersetzen“ neu übernehmen (Testbuchungen verschwinden dabei), ab dann nur noch die neue Lagerverwaltung benutzen.
3. Die Casper-Software kann danach abgeschaltet werden. Den letzten SQL-Export aufheben.

## Datensicherung

Täglich um 22:00 Uhr entsteht eine ZIP-Datei in `C:\Lagerverwaltung2\backups` (Datenbank + Fotos/Dokumente, 30 Tage). Ordner, Uhrzeit, Dauer unter *Einstellungen → Datensicherung*; am besten ein Netzlaufwerk wählen. „Jetzt sichern“ geht jederzeit.

**Wiederherstellen:** Lagerverwaltung beenden (`4_AUTOSTART_AUS.bat` bzw. Fenster schließen), ZIP entpacken, `lager.db` nach `C:\Lagerverwaltung2\daten\lager.db` kopieren, Ordner `anhaenge` nach `daten\anhaenge`, wieder starten.

**Umzug auf einen anderen PC:** Ordner `C:\Lagerverwaltung2` komplett kopieren (bei beendeter Lagerverwaltung), dort `1_EINRICHTEN.bat` und Firewall-Freigabe ausführen.

## Entfernen

`windows\ENTFERNEN.bat` beendet die Lagerverwaltung und entfernt Autostart, Dienst, Desktop-Verknüpfung und Firewall-Regel. Danach den Ordner löschen (vorher `backups` sichern, falls die Daten noch gebraucht werden). Es bleiben keine Spuren auf dem PC; die Casper-Software wurde nie verändert.

## Häufige Probleme

| Problem | Lösung |
|---|---|
| `FEHLER: Python fehlt` | Python-ZIP liegt nicht im Programmordner oder ist nicht 3.12 / 64-bit / embeddable. |
| Seite lädt nicht | Läuft das Fenster bzw. der Autostart? Protokoll: `logs\lagerverwaltung.log`. |
| Handy/Handscanner erreicht die Seite nicht | Firewall-Freigabe ausgeführt? Gerät im selben Netz (Firmen-WLAN, nicht Gäste-WLAN)? Adresse aus *Einstellungen → Handscanner / Handy* verwenden. |
| Port 8080 belegt | *Einstellungen → Allgemein* oder `config.toml`: anderen Port eintragen, neu starten. |
| Etikett wird nicht gedruckt | Druckername exakt wie in Windows? Drucker an, Etiketten kalibriert? Sonst „Über den Browser drucken“. |
| „database is locked“ im Protokoll | Kommt nur vor, wenn jemand die Datei `daten\lager.db` mit einem anderen Programm geöffnet hat. Programm schließen. |
