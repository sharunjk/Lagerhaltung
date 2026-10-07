-- Phase-0-Prüfabfragen für die Legacy-Datenbank `daten`.
-- NUR SELECT. Gedacht für die lokale Entwicklungs-DB mit eingespieltem Dump,
-- niemals für Änderungen an der Produktionsdatenbank.
-- Ergebnisse fließen in docs/legacy-analyse.md (Abschnitte 5 und 11) ein.

USE daten;

-- 0. Überblick
SELECT 'stammdaten' AS tabelle, COUNT(*) AS zeilen FROM stammdaten
UNION ALL SELECT 'lagerorte', COUNT(*) FROM lagerorte
UNION ALL SELECT 'bewegungsdaten', COUNT(*) FROM bewegungsdaten
UNION ALL SELECT 'freifelder', COUNT(*) FROM freifelder
UNION ALL SELECT 'benutzer', COUNT(*) FROM benutzer;

SELECT * FROM benutzer;            -- Passwörter nicht in Berichte übernehmen
SELECT * FROM freifelder ORDER BY CAST(Nummer AS UNSIGNED);

-- 1. ISTBestand und Lagerort je Aktion
SELECT REGEXP_REPLACE(EingangAusgang, ' \\(.*\\)$', '') AS aktion,
       COUNT(*) AS n,
       SUM(ISTBestand < 0) AS negativ, SUM(ISTBestand = 0) AS null_werte,
       SUM(Lagerort = '' OR Lagerort IS NULL) AS ohne_ort,
       MIN(ID) AS erste_id, MAX(ID) AS letzte_id
FROM bewegungsdaten GROUP BY aktion ORDER BY n DESC;

-- 2. Lagerort-Spalte bei Umbuchung / Umlagerung / Inventur / Löschen (Beispiele)
SELECT ID, Artikelnummer, Lagerort, ISTBestand, EingangAusgang, Datum, Zeit, Benutzer
FROM bewegungsdaten
WHERE EingangAusgang LIKE 'Umlagerung%' OR EingangAusgang LIKE 'Inventur%'
ORDER BY ID;

SELECT ID, Artikelnummer, Lagerort, ISTBestand, EingangAusgang, Datum, Zeit
FROM bewegungsdaten WHERE EingangAusgang LIKE 'Umbuchung%' ORDER BY ID DESC LIMIT 60;

SELECT ID, Artikelnummer, Lagerort, ISTBestand, Datum, Zeit
FROM bewegungsdaten WHERE EingangAusgang = 'Artikel gelöscht' ORDER BY ID DESC LIMIT 60;

-- 3. Was existiert nach der letzten Löschung noch?
WITH letzte AS (
  SELECT Artikelnummer, MAX(ID) AS max_id,
         MAX(CASE WHEN EingangAusgang = 'Artikel gelöscht' THEN ID END) AS del_id
  FROM bewegungsdaten GROUP BY Artikelnummer
)
SELECT l.Artikelnummer,
       l.del_id = l.max_id AS loeschung_ist_letzte_aktion,
       s.Artikelnummer IS NOT NULL AS stammsatz_vorhanden,
       (SELECT COUNT(*) FROM lagerorte o WHERE o.Artikel = l.Artikelnummer) AS lagerort_zeilen,
       (SELECT SUM(Anzahl) FROM lagerorte o WHERE o.Artikel = l.Artikelnummer) AS bestand
FROM letzte l LEFT JOIN stammdaten s ON s.Artikelnummer = l.Artikelnummer
WHERE l.del_id IS NOT NULL
ORDER BY loeschung_ist_letzte_aktion DESC, l.Artikelnummer;

-- 4a. Duplikate in lagerorte: exakt (binär) und unter der Tabellen-Kollation
SELECT Artikel, Lagerort, COUNT(*) AS n, SUM(Anzahl) AS summe
FROM lagerorte GROUP BY Artikel, Lagerort HAVING n > 1;

SELECT Artikel, BINARY Lagerort AS ort_binaer, COUNT(*) AS n
FROM lagerorte GROUP BY Artikel, BINARY Lagerort HAVING n > 1;

-- 4b. Null- und Negativbestände, Leerorte, Waisen
SELECT 'Anzahl = 0' AS befund, COUNT(*) FROM lagerorte WHERE Anzahl = 0
UNION ALL SELECT 'Anzahl < 0', COUNT(*) FROM lagerorte WHERE Anzahl < 0
UNION ALL SELECT 'Anzahl NULL', COUNT(*) FROM lagerorte WHERE Anzahl IS NULL
UNION ALL SELECT 'Lagerort leer/NULL', COUNT(*) FROM lagerorte WHERE Lagerort = '' OR Lagerort IS NULL
UNION ALL SELECT 'Lagerort mit Rand-Leerzeichen', COUNT(*) FROM lagerorte WHERE Lagerort <> TRIM(Lagerort)
UNION ALL SELECT 'lagerorte ohne Stammsatz', COUNT(*) FROM lagerorte o
          LEFT JOIN stammdaten s ON s.Artikelnummer = o.Artikel WHERE s.Artikelnummer IS NULL
UNION ALL SELECT 'Stammsatz ohne lagerorte', COUNT(*) FROM stammdaten s
          WHERE NOT EXISTS (SELECT 1 FROM lagerorte o WHERE o.Artikel = s.Artikelnummer);

SELECT * FROM lagerorte WHERE Anzahl < 0;

-- 4c. Alle Lagerort-Schreibweisen mit Häufigkeit
SELECT BINARY Lagerort AS ort, COUNT(*) AS zeilen, SUM(Anzahl) AS bestand,
       Lagerort REGEXP '^[A-Z][0-9]-(R[0-9]+-[0-9]+|F[0-9]+)$' AS schema_ok
FROM lagerorte GROUP BY BINARY Lagerort ORDER BY schema_ok, ort;

-- 5. Melde-/Mindestbestand nicht numerisch
SELECT Artikelnummer, Bezeichnung, Meldebestand, Mindestbestand
FROM stammdaten
WHERE (Meldebestand IS NOT NULL AND Meldebestand <> '' AND Meldebestand NOT REGEXP '^-?[0-9]+([.,][0-9]+)?$')
   OR (Mindestbestand IS NOT NULL AND Mindestbestand <> '' AND Mindestbestand NOT REGEXP '^-?[0-9]+([.,][0-9]+)?$');

SELECT Meldebestand, COUNT(*) FROM stammdaten GROUP BY Meldebestand ORDER BY COUNT(*) DESC LIMIT 20;

-- 6. Abgleich Deltas ↔ Bestand je Artikel und Ort (nur Buchungsarten mit Delta)
SELECT o.Artikel, o.Lagerort, o.Anzahl,
       (SELECT SUM(b.ISTBestand) FROM bewegungsdaten b
         WHERE b.Artikelnummer = o.Artikel AND b.Lagerort = o.Lagerort
           AND (b.EingangAusgang IN ('Eingang', 'Ausgang', 'Neuer Artikel')
                OR b.EingangAusgang LIKE 'Umbuchung%' OR b.EingangAusgang LIKE 'Umlagerung%'
                OR b.EingangAusgang LIKE 'Inventur%')) AS summe_deltas
FROM lagerorte o
ORDER BY ABS(o.Anzahl - IFNULL(summe_deltas, 0)) DESC
LIMIT 50;

-- 7. Ausgang mit Menge 0: Bestand an diesem Ort davor?
SELECT ID, Artikelnummer, Lagerort, Datum, Zeit FROM bewegungsdaten
WHERE EingangAusgang = 'Ausgang' AND ISTBestand = 0 ORDER BY ID;

-- 8. Zeichensatz: Umlaute korrekt oder doppelt kodiert?
SELECT Artikelnummer, Bezeichnung, HEX(Bezeichnung) FROM stammdaten
WHERE Bezeichnung REGEXP '[äöüÄÖÜß]' OR Bezeichnung LIKE '%Ã%' LIMIT 20;

-- 9. Reihenfolge ID ↔ Zeitstempel (später eingefügte Zeilen = Sync)
SELECT ID, Artikelnummer, EingangAusgang, Datum, Zeit, Benutzer
FROM (
  SELECT b.*, STR_TO_DATE(CONCAT(Datum, ' ', Zeit), '%d.%m.%Y %H:%i:%s') AS ts,
         LAG(STR_TO_DATE(CONCAT(Datum, ' ', Zeit), '%d.%m.%Y %H:%i:%s')) OVER (ORDER BY ID) AS ts_vorher
  FROM bewegungsdaten b
) x WHERE ts < ts_vorher ORDER BY ID;
