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
  - **Direkt am Lagerplatz:** Platz oder Sichtlagerbox öffnen → *Artikel hier anlegen*. Der Platz ist dann schon eingetragen.
  - **Fotos gleich mit:** *Fotos / Dateien auswählen* (mehrere möglich). In der Scanner-App *Foto aufnehmen* (Kamera) oder *Aus Galerie*.
  - **Lieferant:** Namen eintippen; vorhandene Lieferanten werden vorgeschlagen. Ein neuer Name wird beim Speichern automatisch unter *Lieferanten* angelegt (Groß-/Kleinschreibung egal, es entstehen keine Doppelten).
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

Übersicht nach Bereichen (C1, C2 …) und darin nach Regalen (R1, R2 …). Plätze ohne Regal, z. B. Flächen wie C1-F1, stehen als *Einzelplätze* vorne. Ein Klick zeigt den Inhalt; dort gibt es auch das Platz-Etikett und *Artikel hier anlegen*.

- **Weinrot** markiert Plätze, an denen ein Artikel unter Melde- oder Mindestbestand liegt. Das sind dieselben Artikel wie unter *Nachbestellung*. Markiert wird auch ein Platz, an dem der Artikel gerade 0 Stück hat, denn dort wird nachgefüllt. Ein Platz wird auch dann weinrot, wenn das in einer seiner Boxen der Fall ist. Am Platz steht, welche Artikel betroffen sind. Nach dem Wareneingang verschwindet die Markierung von selbst.
- **Sichtlagerboxen:** Ein Regalfach lässt sich in Boxen unterteilen. Dazu den Platz öffnen (z. B. C1-R2-3) → *Sichtlagerboxen* → Anzahl eingeben → *Anlegen*. Die Boxen heißen dann C1-R2-3-B1, C1-R2-3-B2 … und der bisherige Platz-Code bleibt unverändert. Je Box den Inhalt eintragen (z. B. „Schrauben M8“) → *OK*. Danach *Alle Box-Etiketten drucken*: Jedes Etikett trägt den Box-Code als Barcode und den Inhalt als Text.
  - Eine Box ist ein ganz normaler Lagerplatz. Man bucht auf sie, scannt ihr Etikett, zählt sie in der Inventur, und sie erscheint in der Historie. Beim Buchen einfach die Box scannen statt des Regalfachs.
  - In der Übersicht erscheinen die Boxen nicht einzeln, sondern beim Platz („2 Art. · 10 Boxen“). Die Suche findet auch Box-Inhalte, z. B. „Schrauben“.
  - **Box entfernen:** In der Box-Liste bei der Box *Entfernen* → Box-Code eintippen → *Endgültig entfernen* → Rückfrage bestätigen. Das geht nur bei leeren Boxen; sonst steht dort „nicht leer“, dann den Inhalt erst umbuchen. Wer Boxen anlegen darf (Rolle Lager oder Administrator), darf leere Boxen auch entfernen. Frühere Buchungen bleiben in der Historie erhalten.
  - Weitere Boxen nummerieren ab der höchsten vorhandenen Nummer weiter. Benennt man den Platz um, werden seine Boxen mit umbenannt. Einen Platz mit Boxen löscht man erst, nachdem die Boxen entfernt sind.
- **Tippfehler korrigieren:** Platz öffnen → **umbenennen**. Liegt schon etwas auf dem richtigen Platz: **zusammenführen**. Das bucht alles auf den richtigen Platz um.
- **Falsch angelegten Platz löschen** (nur Administratoren): Platz öffnen → *Platz löschen* → Code zur Bestätigung eintippen → *Löschen* → Rückfrage bestätigen. Das geht nur bei leeren Plätzen. Liegt noch etwas darauf, erst umbuchen oder zusammenführen. Frühere Buchungen bleiben in der Historie mit dem alten Code erhalten. Plätze aus einer laufenden Inventur oder mit gezählten Mengen in einer abgeschlossenen Inventur lassen sich nicht löschen.

## Auswertungen

Verbrauch je Artikel und Kostenstelle, Lagerwert, Bestand je Gruppe, Ladenhüter – jeweils als Excel.

## Instandhaltung (CMMS) – erste Ausbaustufe

Ab 2.5.0 gibt es neben der Lagerverwaltung einen zweiten Bereich **Instandhaltung**. Er ist zunächst ausgeschaltet. Ein Administrator schaltet ihn unter *Einstellungen → Allgemein → Instandhaltung (CMMS) aktivieren* ein. Solange er aus ist, sieht die Lagerverwaltung genau wie bisher aus.

- **Wer sieht was:** Administratoren haben alle Rechte. Alle anderen brauchen eine **Rolle Instandhaltung** (*Einstellungen → Benutzer*): *Nur lesen*, *Operator / Anlagenfahrer*, *Techniker*, *Schichtführer / Betriebsleiter*, *Instandhaltungsingenieur / Planer*, *Instandhaltungsmanager*. In dieser Ausbaustufe dürfen Ingenieur/Planer und Manager Anlagen bearbeiten und importieren. Alle anderen sehen Anlagen und Dokumentation. Wer nur in der Instandhaltung arbeitet, bekommt im Lager die Rolle *Kein Lagerzugriff*.
- **Bereich wechseln:** Wer beide Bereiche nutzt, wählt nach der ersten Anmeldung *Lagerverwaltung* oder *Instandhaltung*. Danach öffnet sich der zuletzt genutzte Bereich. Oben in der Seitenleiste wechselt *Zur Instandhaltung* bzw. *Zur Lagerverwaltung* ohne neue Anmeldung.
- **Anlagen:** Bereiche (z. B. 1000, 3000), darunter Units (1010, 1040 …), darunter die Bauteile mit Tag-Nr. Die Suche findet Tag-Nr. auch ohne Leerzeichen (`fic1040` findet *FIC 1040 01-01*), außerdem Bezeichnung, Hersteller, Modell und Seriennummer. Filter: Bereich/Unit, Bauteilklasse, nur PLT-Sicherheitseinrichtungen, ohne Doku-Link.
- **Anlagenseite:** Stammdaten, *Dokumentation öffnen* (Link zum SharePoint-Ordner), Unterobjekte, weitere Angaben aus dem Import und *Ersatzteile im Lager*. Dort stehen die Lagerartikel, deren Feld *Verwendung* die Tag-Nr. nennt. Ingenieur/Planer und Manager können die Anlage bearbeiten. Die Tag-Nr. selbst bleibt fest, und jede Änderung steht im Protokoll.

### Asset-Liste importieren

*Instandhaltung → Asset-Import*. Geht mit Excel (.xlsx) oder CSV, auch mit dem SharePoint-Export („Als CSV exportieren“). Bei Excel-Mappen wird automatisch das Blatt mit der Tag-Nr.-Spalte und den meisten Zeilen gelesen, beim Instandhaltungsplan also die *Matrix*.

1. **Hochladen.** Die Datei wird zunächst nur zwischengespeichert.
2. **Spalten zuordnen.** Ein Vorschlag kommt aus den Spaltennamen. Pflicht ist nur die Tag-Nr. *Zusatzfeld* übernimmt eine Spalte unverändert, *ignorieren* lässt sie weg.
   - Units: Fehlt die Unit, wird sie aus der Tag-Nr. abgeleitet (*FIC 1040 01-01* und *P -10401 A* gehören zu 1040).
   - Bereiche: Units lassen sich zu Bereichen zusammenfassen (1040 → 1000).
3. **Prüfen und Testlauf.** Der Import läuft einmal komplett durch und wird sofort zurückgenommen. Danach sehen Sie, was *neu* ist, was *geändert* würde, was *unverändert* bleibt und welche Zeilen *Fehler* haben und übersprungen werden, außerdem *Hinweise*. Alles steht auch im **Importbericht (Excel)**.
   - Fehler: Tag-Nr. fehlt, Tag-Nr. doppelt in der Datei.
   - Hinweise: Platzhalter wie „VV 3010 xx“, Unit passt nicht zur Tag-Nr., ähnliche Schreibweise, unlesbarer Wert, Link, der nicht mit http(s) beginnt.
4. **Übernehmen** (Häkchen setzen). Vorher wird automatisch eine Sicherung *vor_import_…* erstellt. Übernommen wird genau das Geprüfte. Hat jemand inzwischen Anlagen geändert, verlangt das Programm eine neue Prüfung.

Regeln: Der Import löscht nie etwas. Vorhandene Anlagen werden über die Tag-Nr. erkannt, Groß-/Kleinschreibung und Leerzeichen sind egal. Es ändern sich nur die zugeordneten Spalten, eine leere Zelle lässt den vorhandenen Wert stehen. Anlagen, die nicht in der Datei stehen, bleiben unverändert. Zahlen wie „67.200“ und „2.210,45“ und SharePoint-Datumsangaben (UTC) werden richtig umgerechnet.

So entsteht der Anlagenbestand aus den heutigen Listen: erst die **Asset-Liste** (Stammdaten, Doku-Links, Bestelldaten), danach die **Matrix aus dem Instandhaltungsplan**. Die Matrix ergänzt Bauteilklasse, PLT-Sicherheitseinrichtung und die Intervalle als Zusatzfelder.

## Einstellungen (Administrator)

Benutzer und Rollen (*Nur lesen*, *Lager*, *Administrator*, *Kein Lagerzugriff*; dazu die Rolle Instandhaltung), Etikettendrucker, tägliche Meldebestands-Mail, Datensicherung (mehrere Uhrzeiten und Speicherorte, z. B. externe Festplatte; Wiederherstellen mit Vorschau), Datenübernahme aus Casper, Handscanner-Zugang mit QR-Code, Schnittstelle (API) für andere Programme. *Protokoll* zeigt jede Änderung mit Benutzer und Zeit.

**Etiketten-Schriftgröße** (*Einstellungen → Etikettendrucker → Schriftgröße der Bezeichnung*): *Automatisch* (empfohlen) verkleinert lange Bezeichnungen und bricht sie auf zwei Zeilen um, damit nichts abgeschnitten wird. *Groß*, *Normal* und *Klein* sind feste Größen; was nicht passt, wird dort gekürzt. Beim einzelnen Artikel lässt sich die Größe beim Drucken abweichend wählen; die Vorschau zeigt das Ergebnis.

Meldet die Startseite **„Datensicherung prüfen“**, konnte ein Speicherort nicht beschrieben werden (z. B. externe Festplatte abgezogen) oder die letzte Sicherung ist älter als einen Tag. Details unter *Einstellungen → Datensicherung → Zustand*.
