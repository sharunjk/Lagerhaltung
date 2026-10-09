# Lagerverwaltung 2.3.1 – Installation

Eigenständige Lagerverwaltung mit eigener Datenbank. Sie braucht weder Casper noch MySQL noch den MIS Communicator. Die bisherigen Daten werden einmalig aus einem HeidiSQL-Export übernommen. Dauer: etwa 20 Minuten.

## Was Sie brauchen

- Das Paket `Lagerverwaltung_v2.3.1.zip`
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

Eine Sicherung ist eine ZIP-Datei `lager_backup_JJJJMMTT_HHMMSS.zip` mit der Datenbank und allen Fotos/Dokumenten. Einstellungen unter *Einstellungen → Datensicherung*:

- **Uhrzeiten:** eine oder mehrere, z. B. `07:00, 12:00, 16:00, 22:00`. War der PC zu einer Uhrzeit aus, wird die Sicherung beim nächsten Start nachgeholt (einmal, nicht für jede verpasste Uhrzeit).
- **Nur bei Änderung:** Hat sich seit der letzten Sicherung nichts geändert, wird keine neue Datei geschrieben. Die vorhandene Sicherung gilt dann als aktuell.
- **Speicherorte:** Der *Hauptspeicherort* ist `C:\Lagerverwaltung2\backups`. Dazu kommen beliebig viele weitere, z. B. eine externe Festplatte (`S:\Lagerbackup`) oder ein Netzwerkordner (`\\server\freigabe\lager`). Jede Sicherung landet in **jedem** Speicherort. Mit *Ordner auswählen …* wählen Sie den Ordner am Lager-PC aus, neue Ordner lassen sich dort direkt anlegen. *Prüfen* schreibt eine Testdatei mit den Rechten der Lagerverwaltung.
- **Aufbewahren (Tage)** gilt je Speicherort, z. B. 30 Tage auf dem PC und 90 Tage auf der Festplatte. Die **neuesten 3 Sicherungen bleiben immer erhalten**, auch wenn sie älter sind. Andere Dateien im Ordner werden nie angefasst.
- **Speichern und jetzt sichern** sichert sofort in alle Speicherorte.

**Wenn ein Speicherort ausfällt**, z. B. weil die Festplatte abgezogen ist oder das Netzlaufwerk nicht erreichbar ist: Die anderen Speicherorte werden trotzdem beschrieben. Der fehlende wird alle 30 Minuten erneut versucht. Administratoren sehen auf der **Startseite** eine rote Meldung „Datensicherung prüfen“. Ist die E-Mail-Funktion eingerichtet, kommt zusätzlich höchstens eine Mail pro Tag. Dieselbe Meldung erscheint, wenn die letzte Sicherung älter als einen Tag ist oder der Speicherplatz knapp wird. Die Tabelle *Zustand* zeigt je Speicherort die letzte Sicherung, die Größe und den freien Platz.

### Externe Festplatte oder USB-Stick am Lager-PC

1. Anschließen und einmalig einen **festen Laufwerksbuchstaben** vergeben, damit Windows nach dem Ab- und Wiederanstecken nicht `E:` statt `F:` wählt. Dafür Rechtsklick auf Start → *Datenträgerverwaltung* (Adminrechte), dann Rechtsklick auf das Laufwerk → *Laufwerkbuchstaben und -pfade ändern …* → z. B. **S:**. Einen Buchstaben weit hinten im Alphabet wählen, den sonst niemand belegt.
2. In der Lagerverwaltung: *Weiteren Speicherort hinzufügen* → *Ordner auswählen …* → Laufwerk S: → Ordner `Lagerbackup` anlegen → *Diesen Ordner verwenden* → *Prüfen* → *Speichern und jetzt sichern*.
3. Läuft die Lagerverwaltung als Dienst und *Prüfen* meldet „Keine Schreibberechtigung“: Auf NTFS-formatierten Platten der Gruppe *Authentifizierte Benutzer* bzw. dem Konto *NETZWERKDIENST* Schreibrechte auf den Ordner geben (Rechtsklick → *Eigenschaften → Sicherheit*). exFAT/FAT32-Sticks haben keine Rechteverwaltung.

Eine dauerhaft angeschlossene Festplatte schützt, wenn der PC ausfällt. Gegen Diebstahl, Brand, Überspannung oder Verschlüsselungstrojaner schützt sie nicht. Dafür zusätzlich einen Netzwerkordner der IT als Speicherort eintragen oder die Platte regelmäßig tauschen und getrennt aufbewahren.

**Netzwerkordner:** Läuft die Lagerverwaltung als Dienst, kennt sie verbundene Netzlaufwerke wie `N:` nicht. Dann den Netzwerkpfad eintragen (`\\server\freigabe\lager`) und das Schreibrecht für das Computerkonto des Lager-PCs von der IT einrichten lassen. Mit *Prüfen* kontrollieren.

### Wiederherstellen

Unter *Einstellungen → Datensicherung → Vorhandene Sicherungen* bei der gewünschten Sicherung **Wiederherstellen …** wählen. Alternativ *Sicherung auswählen …* für einen anderen Ordner, z. B. die externe Festplatte, oder *Sicherung hochladen*.

1. Die Lagerverwaltung prüft die Datei (lesbar, vollständig, nicht beschädigt, mindestens ein aktiver Administrator) und zeigt den **Vergleich**: Artikel, Buchungen, letzte Buchung, Benutzer, Fotos – aktueller Stand gegenüber Sicherung.
2. Bestätigen und das eigene Passwort eingeben → *Wiederherstellen*.
3. Vorher wird der aktuelle Stand automatisch als `vor_wiederherstellung_….zip` im Hauptspeicherort gesichert. Ein Versehen lässt sich so mit derselben Funktion rückgängig machen.

Die Lagerverwaltung muss dafür nicht beendet werden. Handscanner sollten ihre offline erfassten Buchungen vorher übertragen haben. Danach gelten die Benutzer und Passwörter aus der Sicherung.

**Von Hand** (falls die Lagerverwaltung nicht mehr startet): Lagerverwaltung beenden (`windows\4_AUTOSTART_AUS.bat`, beim Dienst mit Rechtsklick *Als Administrator ausführen*). Dann in `C:\Lagerverwaltung2\daten` die Dateien `lager.db-wal` und `lager.db-shm` löschen, `lager.db` und den Ordner `anhaenge` aus der ZIP nach `daten` kopieren und wieder starten. Dieselben Schritte stehen in jeder Sicherung in `LIESMICH.txt`.

### Lager-PC defekt – Umzug auf einen neuen PC

1. Auf dem neuen PC die Lagerverwaltung nach Abschnitt 1 einrichten. Dafür das **vollständige** Paket `Lagerverwaltung_v2.3.1.zip` nehmen, nicht ein Update-Paket. Die Datenübernahme aus Casper entfällt.
2. Einen vorläufigen Administrator anlegen, anmelden.
3. Externe Festplatte anschließen → *Einstellungen → Datensicherung → Sicherung auswählen …* → neueste Sicherung → *Wiederherstellen*. Danach gelten die Benutzer aus der Sicherung, der vorläufige Administrator ist weg.
4. Speicherorte, Drucker und E-Mail neu einstellen. Diese Einstellungen stehen in `config.toml` und sind nicht Teil der Sicherung. Firewall-Freigabe und Dienst wie bei der Ersteinrichtung.
5. Auf Handhelds und Büro-PCs das Zertifikat des neuen PCs installieren (Abschnitt 3 bzw. Arbeitsplatz-Skript). Hat der neue PC eine andere IP-Adresse, die Adresse in der Scanner-App bzw. auf den Büro-PCs anpassen.

## Updates einspielen

Updates kommen als **Update-Paket** `Lagerverwaltung_Update_auf_<neu>.zip`; es gilt für alle älteren Versionen ab der in `UPDATE_LIESMICH.txt` genannten. Es enthält nur geänderte Programmdateien, nie `daten`, `backups`, `logs`, `python`, `lib`, `config.toml` oder `.secret_key`. Daten, Einstellungen, Benutzer und Zertifikate bleiben also unverändert.

1. Lagerverwaltung beenden: `windows\4_AUTOSTART_AUS.bat` (beim Dienst mit Rechtsklick *Als Administrator ausführen*). Das Programmfenster zu schließen genügt nicht.
2. Update-Paket entpacken (Rechtsklick → *Alle extrahieren …*), nicht direkt aus der ZIP ziehen.
3. Im entpackten Ordner `Lagerverwaltung2` öffnen, alles markieren (Strg+A) und in `C:\Lagerverwaltung2` ziehen → **Dateien im Ziel ersetzen**.
4. Wieder starten: beim Dienst den PC neu starten oder `schtasks /Run /TN Lagerverwaltung` als Administrator, sonst `windows\3_AUTOSTART_EIN.bat` und das Symbol *Lagerverwaltung*. Unten in der Seitenleiste steht die neue Versionsnummer.

`UPDATE_LIESMICH.txt` im Paket listet die geänderten Dateien und Besonderheiten des jeweiligen Updates. Die Scanner-App lädt sich beim nächsten Öffnen selbst neu.

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
| Startseite: „Datensicherung prüfen“ | *Einstellungen → Datensicherung → Zustand* zeigt, welcher Speicherort betroffen ist. „Laufwerk S: ist nicht vorhanden“: Festplatte anschließen bzw. Laufwerksbuchstaben prüfen, danach *Speichern und jetzt sichern*. Die Meldung verschwindet nach der nächsten erfolgreichen Sicherung. |
| Skript meldet „Keine Administratorrechte“ | Rechtsklick auf die Datei → *Als Administrator ausführen*. |
| Etikett wird nicht gedruckt | Druckername exakt wie in Windows? Drucker an, Etiketten kalibriert? Sonst „Über den Browser drucken“. |
| „database is locked“ im Protokoll | Kommt nur vor, wenn jemand die Datei `daten\lager.db` mit einem anderen Programm geöffnet hat. Programm schließen. |
