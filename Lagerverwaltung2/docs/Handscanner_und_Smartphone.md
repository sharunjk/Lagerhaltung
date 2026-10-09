# Handscanner und Smartphone

Die Lagerverwaltung hat eine eigene **Scanner-Ansicht** für Handhelds und Smartphones. Sie läuft im Browser des Geräts – es muss keine App installiert werden.

## Welche Geräte gehen?

| Gerät | Geht? | Scannen mit |
|---|---|---|
| Zebra TC21 (euer Gerät) | ja | Scantaste über DataWedge – eigene Anleitung „Zebra TC21 einrichten“ |
| Andere Android-Handhelds mit Scan-Taste (Honeywell, Datalogic, Unitech, Urovo …) | ja | eingebauter Scanner (wie Tastatur) |
| Normales Android-Smartphone oder iPhone | ja | Kamera |
| Tablet am Lagerplatz, PC mit USB-Barcodescanner | ja | Scanner im Tastaturmodus |
| Älteres Handheld mit Windows CE / Windows Mobile | nein | Browser zu alt – Ersatz: günstiges Android-Handheld oder Smartphone |

## Als App installieren und offline arbeiten

Die Scanner-Ansicht lässt sich auf Android als App installieren (eigenes Symbol, ohne Adressleiste) und arbeitet bei WLAN-Lücken offline weiter. Dafür einmal das Zertifikat des Lager-PCs installieren und die https-Adresse verwenden – Schritt für Schritt in „Zebra TC21 einrichten“ (gilt genauso für andere Android-Geräte).

## Verbinden

1. Das Gerät ins **Firmen-WLAN** bringen (dasselbe Netz wie der Lager-PC).
2. Am PC *Einstellungen → Handscanner / Handy* öffnen. Dort stehen die Adressen, z. B. `https://192.168.1.20:8443/m`, und ein QR-Code. Ohne installiertes Zertifikat warnt Chrome einmal „Verbindung nicht privat“ – siehe „Zebra TC21 einrichten“, Schritt 1.
3. Auf dem Gerät Chrome öffnen und die Adresse eingeben (oder QR-Code mit der Handy-Kamera scannen).
4. Anmelden – jeder Mitarbeiter mit eigenem Benutzer, damit die Buchungen zugeordnet sind. Die Anmeldung bleibt 30 Tage gespeichert.
5. Im Chrome-Menü **„Zum Startbildschirm hinzufügen“**. Dann startet die Scanner-Ansicht wie eine App.

## Eingebauter Scanner (Handheld)

Der Scanner muss den Barcode **als Tastatureingabe mit Enter am Ende** senden. Das ist bei den meisten Geräten Standard. Sonst in der Scanner-Einstellung des Geräts:

- Zebra: App *DataWedge* → Profil → *Keystroke output* an, *Send ENTER key* an
- Honeywell: *Einstellungen → Scan-Einstellungen → Data Processing → Wedge Method: Keyboard*, Suffix: Enter
- Andere: Begriffe wie „Keyboard Wedge“, „Scan to Keyboard“, „Tastaturausgabe“, Suffix/Endzeichen „Enter“ bzw. „CR“

Test: Scanner-Ansicht öffnen, Etikett scannen – der Artikel muss sich öffnen.

## Kamera (Smartphone)

Browser erlauben die Kamera nur über eine sichere Verbindung – die Adresse mit **https** und Port **8443**, z. B. `https://192.168.1.20:8443/m`, ist ohnehin die einzige, die von anderen Geräten aus erreichbar ist.

Beim ersten Öffnen zeigt Chrome „Ihre Verbindung ist nicht privat“. Das ist erwartet (das Zertifikat stammt vom Lager-PC selbst, nicht aus dem Internet): *Erweitert → Weiter zu 192.168.1.20 (unsicher)*. Danach die Kamera erlauben. Das Kamera-Symbol neben jedem Eingabefeld startet den Scan.

## Arbeiten mit der Scanner-Ansicht

- **Startseite:** Scanfeld oben – Artikel-Barcode öffnet den Artikel, Lagerplatz-Barcode zeigt den Platzinhalt.
- **Entnahme / Eingang / Umbuchen / Zählen / Ausleihe:** 1. Artikel scannen, 2. Lagerplatz antippen oder Platz-Etikett scannen, 3. Menge eingeben (+/−), **Buchen**. Grüne Meldung mit Ton = gebucht, rote Meldung mit Doppelvibration = Fehler (z. B. zu wenig Bestand).
- **Rückgabe:** offene Ausleihen mit einem Tipp zurückbuchen.
- **Inventur:** Laufende Inventur antippen, Lagerplatz scannen, gezählte Mengen eintragen, speichern, nächster Platz.
- **Foto aufnehmen:** Beim Artikel „Foto aufnehmen“ – das Bild erscheint danach auch am PC und in der Scanner-Ansicht.
- **Profil** (Leiste unten rechts): **Abmelden / Benutzer wechseln** – teilen sich mehrere Personen ein Gerät, vor der Übergabe abmelden, denn jede Buchung trägt den Namen des Angemeldeten. Noch nicht übertragene Offline-Buchungen werden vorher übertragen. Außerdem: Passwort ändern, Ton und Vibration, hell/dunkel, Offline-Daten aktualisieren und **PC-Ansicht öffnen**. Aus der PC-Ansicht führt der Knopf mit dem Scanner-Symbol oben rechts zurück.
- **←** oben links führt zur vorherigen Seite.

## Etiketten

Alle Etiketten (Artikel und Lagerplätze) enthalten einen Code-128-Barcode mit der Artikelnummer bzw. dem Platz-Code. Die alten Casper-Etiketten mit Artikelnummer funktionieren weiter, sofern ihr Barcode die Artikelnummer enthält. Lagerplatz-Etiketten werden unter *Lagerplätze → Platz öffnen → Etikett drucken* erstellt – für die Scanner-Ansicht lohnt es sich, alle Regalfächer zu beschriften.
