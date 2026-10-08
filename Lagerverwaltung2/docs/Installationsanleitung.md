# Lagerverwaltung 2.2.2 – Installation

Eigenständige Lagerverwaltung mit eigener Datenbank. Sie braucht weder Casper noch MySQL noch den MIS Communicator. Die bisherigen Daten werden einmalig aus einem HeidiSQL-Export übernommen. Dauer: etwa 20 Minuten.

## Was Sie brauchen

- Das Paket `Lagerverwaltung_v2.2.2.zip`
- Die Datei **python-3.12.10-embed-amd64.zip** von python.org (*Downloads → Windows → Python 3.12.10 → „Windows embeddable package (64-bit)“*). Keine Installation, keine Adminrechte nötig.
- Den SQL-Export der Casper-Datenbank (HeidiSQL → Rechtsklick auf `daten` → *Datenbank als SQL exportieren*, Daten: „Einfügen“). Frisch exportieren, damit die letzten Buchungen enthalten sind.
- Für Handscanner/Smartphones und andere PCs: einmalig Adminrechte für die Firewall-Freigabe (IT)

Die Lagerverwaltung kann auf dem bisherigen Lager-PC oder auf jedem anderen Windows-PC laufen, der dauerhaft eingeschaltet ist.

## 1. Installieren

1. `Lagerverwaltung_v2.2.2.zip` nach `C:\` entpacken. Es entsteht `C:\Lagerverwaltung2`.
2. `python-3.12.10-embed-amd64.zip` **ungeöffnet** in `C:\Lagerverwaltung2` legen.
3. Doppelklick auf `windows\1_EINRICHTEN.bat`. Erwartet: `OK: Lagerverwaltung ist startbereit.`
4. Rechtsklick auf `windows\FIREWALL_FREIGEBEN_als_Admin.bat` → *Als Administrator ausführen* (für Handscanner, Smartphones und andere PCs). Erwartet: `Firewall-Regel "Lagerverwaltung" fuer TCP-Port(s) 8443 angelegt`. Geöffnet wird nur der verschlüsselte Port 8443 – `http://…:8080` ist aus Sicherheitsgründen nur am Lager-PC selbst erreichbar (`http_nur_lokal = true` in `config.toml`). Die Regel gilt für die Netzwerkprofile *Domäne* und *Privat* – ist das Firmennetz am Lager-PC als *Öffentlich* eingestuft, bitte die IT das Profil ändern lassen.
5. Doppelklick auf das neue Symbol **Lagerverwaltung** auf dem Desktop (auch im Startmenü). Die Lagerverwaltung öffnet sich als eigenes Programmfenster – ohne Adressleiste und Browser-Tabs. Beim ersten Mal startet sie dabei im Hintergrund, das dauert ein paar Sekunden.

## 2. Ersten Administrator anlegen

Beim ersten Aufruf erscheint *Ersten Administrator anlegen*. Benutzername und Passwort (mindestens 10 Zeichen) wählen. Das geht nur direkt am Lager-PC – von anderen Geräten aus ist die Einrichtung gesperrt.

Alle Passwörter brauchen mindestens 10 Zeichen. Nach 5 falschen Passwörtern für ein Konto (bzw. 20 von einem Gerät) ist die Anmeldung von diesem Gerät 15 Minuten gesperrt.

## 3. Daten aus Casper übernehmen

1. *Einstellungen → Datenübernahme* öffnen.
2. Die SQL-Exportdatei auswählen, **Übernahme starten**.
3. Ergebnis prüfen: Anzahl Artikel, Lagerplätze, Gesamtbestand, Buchungen und Hinweise (z. B. zusammengeführte Lieferanten-Schreibweisen, Lagerplätze außerhalb des Schemas, Bestand ohne Lagerplatz auf `OHNE-PLATZ`).

Übernommen werden: Artikel (Freifeld „Lieferant“ → Lieferant, „Gruppe“ → Gruppe, „Typenbezeichnung“ → Typ, „Austragungsgrund“ → Notiz), Lagerplätze mit Beständen, die komplette Buchungshistorie und die Benutzernamen. Benutzer aus dem Altsystem sind danach gesperrt und ohne Passwort – unter *Einstellungen → Benutzer* anklicken, Passwort vergeben, „Aktiv“ anhaken.

Muss die Übernahme wiederholt werden (z. B. mit einem neueren Export), „Vorhandene Daten ersetzen“ anhaken. Vorher wird automatisch gesichert (`backups\vor_uebernahme_….zip`; diese Sicherungen werden nie automatisch gelöscht).

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

**Weitere Büro-PCs:** Dort wird nichts installiert. Unter *Einstellungen → Allgemein → „Verknüpfung für Arbeitsplatz-PCs herunterladen“* gibt es ein kleines Skript; auf dem jeweiligen PC doppelklicken (keine Adminrechte nötig). Es installiert das Zertifikat der Lagerverwaltung für den angemeldeten Windows-Benutzer – die Sicherheitsabfrage von Windows mit *Ja* bestätigen – und legt ein Symbol *Lagerverwaltung* an, das die Lagerverwaltung des Lager-PCs verschlüsselt (https) als eigenes Fenster öffnet.

## 7. Dauerbetrieb

- **Ohne Adminrechte:** `windows\3_AUTOSTART_EIN.bat` – startet unsichtbar bei jeder Anmeldung am PC.
- **Mit Adminrechten (empfohlen):** Rechtsklick auf `windows\DIENST_EINRICHTEN_als_Admin.bat` → *Als Administrator ausführen* – startet beim Hochfahren, auch ohne Anmeldung. Die Lagerverwaltung läuft dann unter dem eingeschränkten Windows-Konto *NETZWERKDIENST* (keine Administratorrechte, Schreibzugriff nur auf `daten`, `logs`, `backups`, `druckausgabe` und `config.toml`). Danach einmal ein Testetikett drucken – der Drucker muss in Windows für alle Benutzer eingerichtet sein. Das Skript entfernt dabei einen vorher eingerichteten Benutzer-Autostart, damit nicht zwei Instanzen laufen.

Nur eine der beiden Varianten verwenden.

## 8. Umstieg

1. Ein paar Tage parallel testen: in der neuen Lagerverwaltung buchen, die alte nur noch ansehen.
2. Stichtag festlegen: Casper-Datenbank frisch exportieren, unter *Datenübernahme* mit „Vorhandene Daten ersetzen“ neu übernehmen (Testbuchungen verschwinden dabei), ab dann nur noch die neue Lagerverwaltung benutzen.
3. Die Casper-Software kann danach abgeschaltet werden. Den letzten SQL-Export aufheben.

## Datensicherung

Täglich um 22:00 Uhr entsteht eine ZIP-Datei `lager_backup_….zip` in `C:\Lagerverwaltung2\backups` (Datenbank + Fotos/Dokumente, 30 Tage; andere Dateien im Ordner werden nicht angefasst). Läuft die Lagerverwaltung um 22:00 Uhr nicht, wird die Sicherung nachgeholt, sobald sie am selben Tag nach 22:00 Uhr wieder läuft – sonst folgt die nächste Sicherung am Folgetag. Schlägt eine Sicherung fehl (z. B. Netzlaufwerk nicht erreichbar), wird sie jede Minute erneut versucht; Details im Protokoll `logs\lagerverwaltung.log`. Ordner, Uhrzeit, Dauer unter *Einstellungen → Datensicherung*; „Jetzt sichern“ geht jederzeit.

Zusätzlich eine Kopie außerhalb des PCs ablegen (Netzlaufwerk). Wichtig: Läuft die Lagerverwaltung als Dienst (`DIENST_EINRICHTEN_als_Admin.bat`), kennt sie keine Laufwerksbuchstaben wie `N:` – dann den Netzwerkpfad eintragen (z. B. `\\server\freigabe\lager`) und das Schreibrecht für das Computerkonto des Lager-PCs von der IT einrichten lassen. Nach dem Ändern einmal „Jetzt sichern“ und prüfen, ob die Datei ankommt.

**Wiederherstellen:**

1. Lagerverwaltung beenden: `windows\4_AUTOSTART_AUS.bat` – ist sie als Dienst eingerichtet, mit Rechtsklick *Als Administrator ausführen*. Das Programmfenster zu schließen genügt **nicht**, der Hintergrunddienst läuft weiter.
2. Im Ordner `C:\Lagerverwaltung2\daten` die Dateien `lager.db-wal` und `lager.db-shm` löschen (falls vorhanden) – sonst mischt SQLite Reste der alten Datenbank in die Sicherung.
3. ZIP entpacken, `lager.db` nach `C:\Lagerverwaltung2\daten\lager.db` kopieren (überschreiben), Ordner `anhaenge` nach `daten\anhaenge`.
4. Wieder starten (Symbol *Lagerverwaltung*; beim Dienst den PC neu starten oder `schtasks /Run /TN Lagerverwaltung` als Administrator).

Dieselben Schritte stehen in jeder Sicherung in `LIESMICH.txt`.

**Umzug auf einen anderen PC:** Ordner `C:\Lagerverwaltung2` komplett kopieren (bei beendeter Lagerverwaltung), dort `1_EINRICHTEN.bat` und Firewall-Freigabe ausführen.

## Entfernen

`windows\ENTFERNEN.bat` beendet die Lagerverwaltung und entfernt Autostart, Dienst, Desktop-Verknüpfung und Firewall-Regel. Danach den Ordner löschen (vorher `backups` sichern, falls die Daten noch gebraucht werden). Es bleiben keine Spuren auf dem PC; die Casper-Software wurde nie verändert.

## Häufige Probleme

| Problem | Lösung |
|---|---|
| `FEHLER: Python fehlt` | Python-ZIP liegt nicht im Programmordner oder ist nicht 3.12 / 64-bit / embeddable. |
| Seite lädt nicht | Läuft das Fenster bzw. der Autostart? Protokoll: `logs\lagerverwaltung.log`. |
| Handy/Handscanner erreicht die Seite nicht | Firewall-Freigabe ausgeführt? Gerät im selben Netz (Firmen-WLAN, nicht Gäste-WLAN)? Adresse aus *Einstellungen → Handscanner / Handy* verwenden. |
| Port 8080 belegt | *Einstellungen → Allgemein* oder `config.toml` (Abschnitt `[server]`): anderen Port eintragen, Lagerverwaltung neu starten und `FIREWALL_FREIGEBEN_als_Admin.bat` erneut ausführen (liest die Ports aus `config.toml`). |
| Handy meldet nach IP-Wechsel des Lager-PCs „Verbindung nicht privat“ | Lagerverwaltung neu starten – das HTTPS-Zertifikat wird beim Start für die aktuellen Adressen neu ausgestellt. Das Zertifikat auf den Geräten muss nicht neu installiert werden. Nach einer **Umbenennung des PCs** gilt der neue Name erst mit einem neuen Zertifikat; bis dahin die IP-Adresse verwenden. |
| „Zu viele Fehlversuche“ | 15 Minuten warten oder die Lagerverwaltung neu starten (hebt alle Sperren auf). |
| Update von 2.2.1 oder älter | Beim ersten Start wird das Zertifikat der Lagerverwaltung durch eine beschränkte Version ersetzt (siehe *Technik*). Auf Handhelds und Büro-PCs das Zertifikat einmal neu installieren bzw. das Arbeitsplatz-Skript erneut ausführen. |
| Skript meldet „Keine Administratorrechte“ | Rechtsklick auf die Datei → *Als Administrator ausführen*. |
| Etikett wird nicht gedruckt | Druckername exakt wie in Windows? Drucker an, Etiketten kalibriert? Sonst „Über den Browser drucken“. |
| „database is locked“ im Protokoll | Kommt nur vor, wenn jemand die Datei `daten\lager.db` mit einem anderen Programm geöffnet hat. Programm schließen. |
