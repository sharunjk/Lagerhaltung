# Lagerverwaltung – Kurzanleitung

Aufruf am PC: Symbol **Lagerverwaltung** auf dem Desktop (öffnet ein eigenes Programmfenster) – am Zebra TC21 oder Handy die **Lager-App** (Scanner-Ansicht, siehe „Zebra TC21 einrichten“). Am Handheld gibt es zusätzlich Sammelentnahme, Neuanlage mit Foto, Melde-/Mindestbestand am Regal, Etikettendruck, Rückgängig und einen Offline-Modus. Jeder arbeitet mit eigenem Benutzer; der Name steht bei jeder Buchung.

## Scannen am PC

Der Pfeil **←** links oben führt zur vorherigen Seite, auch im Programmfenster ohne Browserleiste. In der Scanner-App auf dem Handheld gibt es ihn ebenfalls. Der Knopf **Scanner-Ansicht** (auf dem Handy nur das Scanner-Symbol) wechselt in die Scanner-App; dort führt *Profil → PC-Ansicht öffnen* zurück. Das Suchfeld oben ist zugleich Scanfeld (**F2** springt hinein). Ein USB-Barcodescanner funktioniert auf jeder Seite, auch ohne ins Feld zu klicken: Artikel-Barcode → Buchen, Lagerplatz-Barcode → Platzinhalt.

## Buchen

1. Art wählen: **Entnahme**, **Eingang**, **Umbuchen** (Platzwechsel), **Zählen** (Bestand am Platz auf den gezählten Wert setzen), **Ausleihe** (Werkzeug verleihen, kommt zurück).
2. Artikel scannen/eingeben, Lagerplatz antippen oder scannen, Menge, **Enter**.
3. Bei Entnahmen optional Empfänger, Kostenstelle, Verwendung – erscheinen in den Auswertungen.

Fehlbuchung? Bei der Buchung **Storno** – es entsteht eine Gegenbuchung, nichts wird gelöscht. Stornieren lassen sich Eingänge und Entnahmen; Umbuchungen und Zählungen werden durch eine neue Umbuchung bzw. Zählung korrigiert (am Handscanner geht „Rückgängig“ bis 10 Minuten für alle Arten).

## Artikel

- **Neuer Artikel:** nächste freie Nummer wird vorgeschlagen; Lagerplatz und Anfangsbestand gleich mitgeben, danach Etikett drucken.
- **Kopieren:** neuer Artikel mit den Daten eines vorhandenen.
- **Melde- und Mindestbestand:** ab Meldebestand → Nachbestellvorschlag, unter Mindestbestand → kritisch. Für viele Artikel auf einmal: Artikelliste als Excel exportieren, Spalten ergänzen, über *Excel-Import* einlesen.
- **Kritisches Ersatzteil** markieren, **Verwendung/Anlage** (Tag-Nummer) eintragen, **Fotos und Datenblätter** anhängen.
- **Archivieren:** Artikel ohne Bestand verschwinden aus den Listen, lassen sich aber jederzeit wieder aktivieren. Das ist richtig für Teile, die es nicht mehr gibt.
- **Endgültig löschen** (nur Administratoren), für falsch angelegte Artikel: Artikel öffnen → *Artikel endgültig löschen* → Artikelnummer eintippen → *Löschen* → Rückfrage bestätigen.
  - Geht nur ohne Bestand und ohne offene Reservierung, Bestellung, Ausleihe oder laufende Inventur.
  - Gelöscht werden Stammdaten, Fotos und Dokumente. Frühere Buchungen bleiben in der Historie mit der Artikelnummer erhalten.
  - Die Nummer ist danach wieder frei. Jedes Löschen steht im Protokoll.

## Reservierungen und Ausleihen

- **Reservieren** (beim Artikel oder unter *Reservierungen*): Teile für einen Auftrag oder eine Wartung zurücklegen. Reservierte Mengen zählen nicht als verfügbar. Bei der Entnahme die Reservierung wählen – sie wird erledigt.
- **Ausleihe:** Bestand geht ab, unter *Ausleihen* sieht man, wer was seit wann hat (überfällige rot). **Zurückbuchen** legt es wieder auf den Platz.

## Nachbestellen

1. *Nachbestellung* zeigt alle Artikel auf/unter Meldebestand mit Mengenvorschlag.
2. Auswählen → **Als Bestellung anlegen**.
3. *Bestellungen* (nach Lieferant gruppiert): Bestellliste als Excel für den Einkauf, **als bestellt markieren**.
4. Bei Lieferung **Wareneingang** – bucht auf den Lagerplatz und schließt die Position.

## Inventur

1. *Inventur → Neue Inventur*, Bereich wählen oder gesamtes Lager.
2. Zählen am PC (Liste) oder am Handscanner (Platz scannen, Mengen eintragen).
3. Administrator: **Inventur abschließen** bucht alle Differenzen. Wurde zwischen Zählung und Abschluss am Platz gebucht (z. B. eine Entnahme), wird das berücksichtigt: Neuer Bestand = gezählt ± Buchungen seit der Zählung.

## Lagerplätze

Übersicht nach Bereichen (C1, C2 …) und darin nach Regalen (R1, R2 …). Plätze ohne Regal, z. B. Flächen wie C1-F1, stehen als *Einzelplätze* vorne. Ein Klick zeigt den Inhalt; dort gibt es auch das Platz-Etikett.

- **Weinrot** markiert Plätze, an denen ein Artikel unter Melde- oder Mindestbestand liegt. Das sind dieselben Artikel wie unter *Nachbestellung*. Markiert wird auch ein Platz, an dem der Artikel gerade 0 Stück hat, denn dort wird nachgefüllt. Ein Platz wird auch dann weinrot, wenn das in einer seiner Boxen der Fall ist. Am Platz steht, welche Artikel betroffen sind. Nach dem Wareneingang verschwindet die Markierung von selbst.
- **Sichtlagerboxen:** Ein Regalfach lässt sich in Boxen unterteilen. Dazu den Platz öffnen (z. B. C1-R2-3) → *Sichtlagerboxen* → Anzahl eingeben → *Anlegen*. Die Boxen heißen dann C1-R2-3-B1, C1-R2-3-B2 … und der bisherige Platz-Code bleibt unverändert. Je Box den Inhalt eintragen (z. B. „Schrauben M8“) → *OK*. Danach *Alle Box-Etiketten drucken*: Jedes Etikett trägt den Box-Code als Barcode und den Inhalt als Text.
  - Eine Box ist ein ganz normaler Lagerplatz. Man bucht auf sie, scannt ihr Etikett, zählt sie in der Inventur, und sie erscheint in der Historie. Beim Buchen einfach die Box scannen statt des Regalfachs.
  - In der Übersicht erscheinen die Boxen nicht einzeln, sondern beim Platz („2 Art. · 10 Boxen“). Die Suche findet auch Box-Inhalte, z. B. „Schrauben“.
  - Weitere Boxen nummerieren fortlaufend weiter. Benennt man den Platz um, werden seine Boxen mit umbenannt. Einen Platz mit Boxen löscht man erst, nachdem die Boxen gelöscht sind.
- **Tippfehler korrigieren:** Platz öffnen → **umbenennen**. Liegt schon etwas auf dem richtigen Platz: **zusammenführen**. Das bucht alles auf den richtigen Platz um.
- **Falsch angelegten Platz löschen** (nur Administratoren): Platz öffnen → *Platz löschen* → Code zur Bestätigung eintippen → *Löschen* → Rückfrage bestätigen. Das geht nur bei leeren Plätzen. Liegt noch etwas darauf, erst umbuchen oder zusammenführen. Frühere Buchungen bleiben in der Historie mit dem alten Code erhalten. Plätze aus einer laufenden Inventur oder mit gezählten Mengen in einer abgeschlossenen Inventur lassen sich nicht löschen.

## Auswertungen

Verbrauch je Artikel und Kostenstelle, Lagerwert, Bestand je Gruppe, Ladenhüter – jeweils als Excel.

## Einstellungen (Administrator)

Benutzer und Rollen (*Nur lesen*, *Lager*, *Administrator*), Etikettendrucker, tägliche Meldebestands-Mail, Datensicherung (mehrere Uhrzeiten und Speicherorte, z. B. externe Festplatte; Wiederherstellen mit Vorschau), Datenübernahme aus Casper, Handscanner-Zugang mit QR-Code, Schnittstelle (API) für andere Programme. *Protokoll* zeigt jede Änderung mit Benutzer und Zeit.

Meldet die Startseite **„Datensicherung prüfen“**, konnte ein Speicherort nicht beschrieben werden (z. B. externe Festplatte abgezogen) oder die letzte Sicherung ist älter als einen Tag. Details unter *Einstellungen → Datensicherung → Zustand*.
