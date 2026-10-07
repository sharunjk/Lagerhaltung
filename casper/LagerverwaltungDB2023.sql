-- --------------------------------------------------------
-- Host:                         127.0.0.1
-- Server Version:               8.0.23 - MySQL Community Server - GPL
-- Server Betriebssystem:        Win64
-- HeidiSQL Version:             9.5.0.5196
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;


-- Exportiere Datenbank Struktur für daten
CREATE DATABASE IF NOT EXISTS `daten` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;
USE `daten`;

-- Exportiere Struktur von Tabelle daten.benutzer
CREATE TABLE IF NOT EXISTS `benutzer` (
  `benutzer` varchar(255) DEFAULT NULL,
  `passwort` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Exportiere Daten aus Tabelle daten.benutzer: ~0 rows (ungefähr)
/*!40000 ALTER TABLE `benutzer` DISABLE KEYS */;
INSERT INTO `benutzer` (`benutzer`, `passwort`) VALUES
	('Administrator', NULL);
/*!40000 ALTER TABLE `benutzer` ENABLE KEYS */;

-- Exportiere Struktur von Tabelle daten.bewegungsdaten
CREATE TABLE IF NOT EXISTS `bewegungsdaten` (
  `Artikelnummer` varchar(255) DEFAULT NULL,
  `Lagerort` varchar(50) DEFAULT '',
  `ISTBestand` double DEFAULT NULL,
  `Zeit` varchar(255) DEFAULT NULL,
  `Datum` varchar(255) DEFAULT NULL,
  `EingangAusgang` varchar(255) DEFAULT NULL,
  `Benutzer` varchar(255) DEFAULT NULL,
  `ID` int NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Exportiere Daten aus Tabelle daten.bewegungsdaten: ~18 rows (ungefähr)
/*!40000 ALTER TABLE `bewegungsdaten` DISABLE KEYS */;
/*!40000 ALTER TABLE `bewegungsdaten` ENABLE KEYS */;

-- Exportiere Struktur von Tabelle daten.freifelder
CREATE TABLE IF NOT EXISTS `freifelder` (
  `Freifeld1` varchar(255) DEFAULT NULL,
  `Freifeld2` varchar(255) DEFAULT NULL,
  `Freifeld3` varchar(255) DEFAULT NULL,
  `Freifeld4` varchar(255) DEFAULT NULL,
  `Freifeld5` varchar(255) DEFAULT NULL,
  `Felder` varchar(255) DEFAULT NULL,
  `Nummer` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Exportiere Daten aus Tabelle daten.freifelder: ~11 rows (ungefähr)
/*!40000 ALTER TABLE `freifelder` DISABLE KEYS */;
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Artikelnummer', '1');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Bezeichnung', '2');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Lagerort', '3');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'ISTBestand', '4');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Meldebestand', '5');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Mindestbestand', '6');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Freifeld1', '7');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Freifeld2', '8');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Freifeld3', '9');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Freifeld4', '10');
INSERT INTO `freifelder` (`Freifeld1`, `Freifeld2`, `Freifeld3`, `Freifeld4`, `Freifeld5`, `Felder`, `Nummer`) VALUES
	('Freifeld1', 'Freifeld2', 'Freifeld3', 'Freifeld4', 'Freifeld5', 'Freifeld5', '11');
/*!40000 ALTER TABLE `freifelder` ENABLE KEYS */;

-- Exportiere Struktur von Tabelle daten.lagerorte
CREATE TABLE IF NOT EXISTS `lagerorte` (
  `Artikel` varchar(255) DEFAULT NULL,
  `Lagerort` varchar(255) DEFAULT NULL,
  `Anzahl` decimal(10,3) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Exportiere Daten aus Tabelle daten.lagerorte: ~2 rows (ungefähr)
/*!40000 ALTER TABLE `lagerorte` DISABLE KEYS */;
/*!40000 ALTER TABLE `lagerorte` ENABLE KEYS */;

-- Exportiere Struktur von Tabelle daten.stammdaten
CREATE TABLE IF NOT EXISTS `stammdaten` (
  `Artikelnummer` varchar(255) NOT NULL,
  `Bezeichnung` varchar(255) DEFAULT NULL,
  `Meldebestand` varchar(255) DEFAULT NULL,
  `Mindestbestand` varchar(255) DEFAULT NULL,
  `Freifeld1` varchar(255) DEFAULT NULL,
  `Freifeld2` varchar(255) DEFAULT NULL,
  `Freifeld3` varchar(255) DEFAULT NULL,
  `Freifeld4` varchar(255) DEFAULT NULL,
  `Freifeld5` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`Artikelnummer`),
  UNIQUE KEY `Artikelnummer` (`Artikelnummer`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Exportiere Daten aus Tabelle daten.stammdaten: ~0 rows (ungefähr)
/*!40000 ALTER TABLE `stammdaten` DISABLE KEYS */;
/*!40000 ALTER TABLE `stammdaten` ENABLE KEYS */;

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
