// Datensicherung 2.3.0 im Browser: Ordnerauswahl, Prüfen, Sichern, Zustand, Warnung, Wiederherstellen.
// Aufruf: node sicherung.cjs <baseUrl> <LV_HOME> <ausgabeOrdner>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const BASE = process.argv[2], HOME = process.argv[3], OUT = process.argv[4];
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);

  await page.goto(BASE + "/einstellungen?tab=backup", { waitUntil: "networkidle" });
  schritt("Modal anfangs verborgen", !(await page.locator("[role=dialog]").isVisible()));
  await page.screenshot({ path: `${OUT}/1_start.png`, fullPage: true });

  // weiteren Speicherort über die Ordnerauswahl anlegen
  await page.click("text=Weiteren Speicherort hinzufügen");
  await page.locator("button:has-text('Ordner auswählen')").nth(1).click();
  await page.waitForSelector("[role=dialog]", { state: "visible" });
  await page.waitForTimeout(400);
  const laufwerke = await page.locator("[role=dialog] li button").count();
  schritt("Ordnerauswahl zeigt Laufwerke", laufwerke >= 1, `${laufwerke}`);
  await page.fill("[role=dialog] input[aria-label=Pfad]", HOME);
  await page.click("[role=dialog] button:has-text('Öffnen')");
  await page.waitForTimeout(400);
  schritt("Ordner geöffnet", (await page.textContent("[role=dialog]")).includes("daten"));
  await page.fill("[role=dialog] input[aria-label='Name für neuen Ordner']", "USB_Lagerbackup");
  await page.click("[role=dialog] button:has-text('Anlegen')");
  await page.waitForTimeout(400);
  const ziel = path.join(HOME, "USB_Lagerbackup");
  schritt("Neuer Ordner angelegt und geöffnet", fs.existsSync(ziel) && (await page.textContent("[role=dialog]")).includes(ziel));
  await page.screenshot({ path: `${OUT}/2_ordnerwahl.png` });
  await page.click("[role=dialog] button:has-text('Diesen Ordner verwenden')");
  const wert = await page.locator("input[name=ziel_ordner]").nth(1).inputValue();
  schritt("Ordner übernommen", wert === ziel, wert);
  await page.locator("button:has-text('Prüfen')").nth(1).click();
  await page.waitForTimeout(500);
  const pruef = await page.locator("p.text-ok").first().textContent().catch(() => "");
  schritt("Prüfen meldet in Ordnung", /In Ordnung/.test(pruef), pruef);

  // speichern und sichern
  await page.fill("input[name=uhrzeit]", "07:00, 12:00, 22:00");
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Speichern und jetzt sichern')")]);
  const flashes = await page.locator("[role=status]").allTextContents();
  schritt("Beide Speicherorte gesichert", flashes.filter((t) => t.includes("gesichert")).length === 2, flashes.join(" | "));
  const zustand = await page.locator("text=in Ordnung").count();
  schritt("Zustand zweimal in Ordnung", zustand === 2, `${zustand}`);
  const zipsUsb = fs.readdirSync(ziel).filter((f) => f.endsWith(".zip"));
  schritt("ZIP auf dem zweiten Speicherort", zipsUsb.length === 1, zipsUsb.join(","));
  await page.screenshot({ path: `${OUT}/3_gesichert.png`, fullPage: true });
  const hs = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  schritt("Kein waagerechtes Scrollen bei 1280 px", !hs);

  // Wiederherstellen aus anderem Ordner (Auswahl im ZIP-Modus)
  await page.click("button:has-text('Sicherung auswählen')");
  await page.waitForTimeout(500);
  await page.fill("[role=dialog] input[aria-label=Pfad]", ziel);
  await page.click("[role=dialog] button:has-text('Öffnen')");
  await page.waitForTimeout(400);
  const zipLinks = page.locator("[role=dialog] a[href*='backup-wiederherstellen']");
  schritt("ZIP-Modus listet Sicherungen", (await zipLinks.count()) === 1);
  await page.screenshot({ path: `${OUT}/4_zipwahl.png` });
  await Promise.all([page.waitForNavigation(), zipLinks.first().click()]);
  schritt("Bestätigungsseite mit Vergleich", (await page.textContent("main")).includes("Vergleich"));
  await page.screenshot({ path: `${OUT}/5_bestaetigen.png`, fullPage: true });
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await page.check("input[name=bestaetigt]");
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Wiederherstellen')")]);
  const nach = (await page.locator("[role=status]").allTextContents()).join(" | ");
  schritt("Wiederhergestellt", /wiederhergestellt/.test(nach), nach);
  schritt("vor_wiederherstellung angelegt", fs.readdirSync(path.join(HOME, "backups")).some((f) => f.startsWith("vor_wiederherstellung_")));
  await page.goto(BASE + "/artikel", { waitUntil: "networkidle" });
  schritt("Programm läuft nach Wiederherstellen weiter", (await page.title()).length > 0 && page.url().endsWith("/artikel"));

  // Speicherort fällt aus -> Fehlermeldung + Warnung auf der Startseite
  fs.renameSync(ziel, ziel + "_weg");
  fs.writeFileSync(ziel, "Stick abgezogen");  // Datei statt Ordner -> nicht beschreibbar
  await page.goto(BASE + "/einstellungen?tab=backup", { waitUntil: "networkidle" });
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Speichern und jetzt sichern')")]);
  const f2 = await page.locator(".flash-fehler").allTextContents();
  schritt("Fehler für ausgefallenen Speicherort", f2.length === 1, f2.join(" | "));
  await page.screenshot({ path: `${OUT}/6_fehler.png`, fullPage: true });
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  schritt("Startseite warnt", (await page.textContent("main")).includes("Datensicherung prüfen"));
  await page.screenshot({ path: `${OUT}/7_startseite.png` });
  fs.unlinkSync(ziel);
  fs.renameSync(ziel + "_weg", ziel);

  // dunkles Design: Modal lesbar
  await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate(() => { localStorage.removeItem("lv-theme"); });
  await page.goto(BASE + "/einstellungen?tab=backup", { waitUntil: "networkidle" });
  await page.locator("button:has-text('Ordner auswählen')").first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/8_dunkel.png` });
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/sicherung.json`, JSON.stringify(log, null, 1));
  await browser.close();
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})();
