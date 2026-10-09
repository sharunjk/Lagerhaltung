# Zebra TC21 als Lager-App einrichten

Die Lagerverwaltung läuft auf dem TC21 als **App aus dem Browser** (Web-App). Es wird nichts aus einem App-Store installiert. Die App hat ein eigenes Symbol, startet ohne Adressleiste, nutzt die Scantaste und funktioniert auch in WLAN-Funklöchern.

Einmal pro Gerät, etwa 10 Minuten. Die Adressen und QR-Codes für Ihr Netz stehen am PC unter **Einstellungen → Handscanner / Handy**. In dieser Anleitung steht beispielhaft `192.168.1.20` für den Lager-PC.

## Voraussetzungen

- TC21 im **Firmen-WLAN** (gleiches Netz wie der Lager-PC, nicht das Gäste-WLAN)
- Am Lager-PC wurde `FIREWALL_FREIGEBEN_als_Admin.bat` ausgeführt
- Ein Benutzer für die Person, die das Gerät nutzt (*Einstellungen → Benutzer*)
- Der Lager-PC sollte eine **feste IP-Adresse** haben (IT fragen), sonst ändert sich die App-Adresse. Nach einem IP-Wechsel die Lagerverwaltung am PC neu starten (das HTTPS-Zertifikat wird beim Start neu ausgestellt).

## Schritt 1: Sicherheitszertifikat installieren

Damit Chrome die Lagerverwaltung als sichere App akzeptiert (nötig für Installation und Offline-Modus), wird einmal das Zertifikat des Lager-PCs installiert. Es enthält keine Zugangsdaten und gilt nur für interne Adressen dieses PCs – es kann keine anderen Webseiten beglaubigen.

1. Chrome öffnen, Adresse eingeben: `https://192.168.1.20:8443/zertifikat.crt` – oder den QR-Code „Zertifikat“ am PC mit der Kamera-App scannen. Chrome warnt dabei einmal „Verbindung nicht privat“ (das Zertifikat ist ja noch nicht installiert): *Erweitert → Weiter zu 192.168.1.20*. Die Datei *Lagerverwaltung-CA.crt* wird heruntergeladen.
2. *Einstellungen* → *Sicherheit* (bzw. *Sicherheit & Standort*) → *Verschlüsselung & Anmeldedaten* → *Zertifikat installieren* → **CA-Zertifikat** → „Trotzdem installieren“.
3. Gerätesperre (PIN) bestätigen, Datei *Lagerverwaltung-CA.crt* aus „Downloads“ wählen.

Android zeigt danach dauerhaft einen Hinweis „Netzwerk wird möglicherweise überwacht“ – das ist bei selbst installierten Zertifikaten normal.

**Geht nicht (Gerät von der IT gesperrt)?** Dann die IT bitten, die Datei *Lagerverwaltung-CA.crt* über die Geräteverwaltung zu verteilen. Unverschlüsseltes http ist aus Sicherheitsgründen nur am Lager-PC selbst erreichbar.

## Schritt 2: App öffnen und installieren

1. In Chrome `https://192.168.1.20:8443/m` öffnen (oder QR-Code „App öffnen“ scannen).
2. Anmelden. Die Anmeldung bleibt 30 Tage gespeichert.
3. Auf der Startseite **„App installieren“** tippen – oder Chrome-Menü ⋮ → *App installieren* bzw. *Zum Startbildschirm hinzufügen*.
4. Das Symbol „Lager“ auf dem Startbildschirm verwenden.

## Schritt 3: Scantaste einrichten (DataWedge)

Der TC21 gibt Barcodes über **DataWedge** wie eine Tastatur ein. Meist funktioniert das schon. Falls nicht, oder falls ohne Enter gescannt wird (Menünamen je nach Android- und DataWedge-Version leicht unterschiedlich):

1. App **DataWedge** öffnen → ⋮ → *Neues Profil* → Name „Lager“.
2. *Zugeordnete Apps* → ⋮ → *Neue App/Aktivität* → **com.android.chrome** → **\***. (Wird die Lager-App als eigene App gelistet, diese ebenfalls zuordnen.)
3. *Barcode-Eingang*: **aktiviert**. Unter *Decoder* mindestens Code 128 und QR-Code an.
4. *Tastatureingabe (Keystroke output)*: **aktiviert**. *Intent-Ausgabe*: aus.
5. *Tastatureingabe → Basisdatenformatierung*: aktiviert, **„ENTER-Taste senden“** an.

Test: In der App *Suchen* öffnen und ein Etikett scannen – der Artikel muss erscheinen.

## Arbeiten mit der App

| Funktion | So geht's |
|---|---|
| Artikel oder Platz ansehen | Auf der Startseite (oder jeder Infoseite) einfach scannen |
| Entnahme / Eingang / Umbuchen / Zählen | Kachel wählen → Artikel scannen → Platz antippen oder Platz-Etikett scannen → Menge → Buchen |
| Rückgängig | Nach einer Buchung oben „Rückgängig“ (bis 10 Minuten, nur eigene letzte Buchung) |
| Sammelentnahme | Mehrere Teile scannen, Menge je Teil, am Ende einmal mit Kostenstelle/Auftrag ausbuchen. Bucht alles oder nichts. |
| Neuer Artikel | Unbekannten Barcode scannen → „Neu anlegen“, oder Kachel *Neuer Artikel*. Bezeichnung, Platz, Menge, auf Wunsch Etikett drucken, danach Foto aufnehmen |
| Melde-/Mindestbestand | Artikel scannen → „Melde-/Mindestbestand und Infos“ – direkt am Regal pflegen |
| Etiketten | Beim Artikel „Etikett“, beim Lagerplatz „Platz-Etikett“ – wird am Etikettendrucker im Lager ausgedruckt |
| Reservierte Teile | Kachel *Reserviert* → Reservierung antippen → Entnahme ist vorausgefüllt und erledigt die Reservierung |
| Wareneingang | Kachel *Wareneingang* → bestellte Position → Platz scannen → Buchen |
| Ausleihe / Rückgabe | Werkzeug an Personen oder Firmen verleihen und zurückbuchen |
| Profil (Leiste unten rechts) | Abmelden bzw. Benutzer wechseln, Passwort ändern, Ton/Vibration, hell/dunkel, Offline-Daten aktualisieren, PC-Ansicht öffnen |
| ← (oben links) | zurück zur vorherigen Seite |
| Inventur | Laufende Inventur antippen → Platz scannen → gezählte Mengen eintragen |

Grüne Meldung mit kurzem Ton = gebucht. Rote Meldung mit Doppelvibration = nicht gebucht (Grund steht dabei, z. B. zu wenig Bestand am Platz).

## Ohne WLAN (Offline-Modus)

Fehlt an einer Stelle im Lager das WLAN, wird eine Buchung **nicht verloren**. Voraussetzung: Die App wurde wie oben über die **https**-Adresse installiert (nur dann hält Chrome die Offline-Seite vor).

- Beim Buchen prüft die App kurz die Verbindung. Ist der Lager-PC nicht erreichbar, wird die Buchung im Gerät gespeichert und die Seite *Offline erfassen* geöffnet.
- Ist nur die Anmeldung abgelaufen, wird die Buchung ebenfalls im Gerät gespeichert und die Anmeldung geöffnet; nach dem Anmelden wird sie übertragen.
- Auf *Offline erfassen* lässt sich ohne Verbindung weiterarbeiten: Artikel scannen (Bezeichnung und Bestände vom letzten Abgleich werden angezeigt), Platz, Menge, Speichern.
- Oben rechts zeigt ein Zähler „1 wartet“. Sobald wieder Verbindung besteht, überträgt die App automatisch (spätestens nach 30 Sekunden). Doppelt gebucht wird dabei nie.
- Lässt sich eine offline erfasste Buchung später nicht ausführen (z. B. Bestand inzwischen woanders entnommen), erscheint sie rot unter *Offline erfassen* mit dem Grund – dort „Erneut senden“ oder „Verwerfen“.
- Am PC sind solche Buchungen mit „Handscanner (offline)“ und der Erfassungszeit gekennzeichnet.

## Etiketten der Casper-Software

Alte Etiketten mit der Artikelnummer im Barcode funktionieren weiter. Neue Etiketten druckt die Lagerverwaltung im gleichen Format (45 × 23 mm oder 60 × 20 mm, Code 128).
