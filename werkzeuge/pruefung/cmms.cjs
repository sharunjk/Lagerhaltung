// 2.5.0: Instandhaltung (CMMS) Phase 0 im Browser – Aktivieren, Bereichswechsel, Asset-Import (CSV + Excel), Anlagen.
// Aufruf: node cmms.cjs <baseUrl> <ausgabe> <asset-liste.csv> [instandhaltungsplan.xlsx]
// Die Dateien werden nur hochgeladen; Inhalte erscheinen nicht in der Ausgabe außer in Bildschirmfotos (nur lokal ansehen).
const { chromium } = require("playwright");
const fs = require("fs");
const [BASE, OUT, CSV, XLSX] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
  schritt("Ohne Aktivierung kein CMMS sichtbar", !(await page.textContent("aside")).includes("Instandhaltung"));
  // Aktivieren
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.check("input[name=cmms_aktiv]");
  await Promise.all([page.waitForNavigation(), page.click("form[action='/einstellungen/allgemein'] button")]);
  await page.goto(BASE + "/");
  const wechsel = page.locator("aside a[href='/bereich/ih']");
  schritt("Umschalter zur Instandhaltung", (await wechsel.count()) === 1);
  await Promise.all([page.waitForNavigation(), wechsel.click()]);
  schritt("Instandhaltung geöffnet", page.url().endsWith("/ih") && (await page.textContent("aside")).includes("Zur Lagerverwaltung"));
  await page.screenshot({ path: `${OUT}/01_leer.png`, fullPage: true });
  // Import CSV
  await page.goto(BASE + "/ih/import");
  await page.setInputFiles("input[name=datei]", CSV);
  await Promise.all([page.waitForNavigation(), page.click("form[action='/ih/import'] button")]);
  schritt("CSV hochgeladen", /\/ih\/import\/\d+$/.test(page.url()), page.url());
  const zuordnung = await page.locator("select[name^=spalte_]").evaluateAll((s) => s.map((x) => x.value));
  schritt("Zuordnung vorgeschlagen (Tag-Nr. erkannt)", zuordnung.filter((z) => z === "code").length === 1, zuordnung.join(","));
  await page.screenshot({ path: `${OUT}/02_zuordnung.png`, fullPage: true });
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Prüfen und Testlauf')")]);
  const kacheln = await page.locator("#ergebnis a.panel span.block").allTextContents();
  schritt("Testlauf mit Ergebnis", kacheln.length === 5, kacheln.join(" / "));
  await page.goto(BASE + "/ih/anlagen");
  schritt("Testlauf hat nichts angelegt", (await page.textContent("main")).includes("0 Bauteile"));
  await page.goto(BASE + "/ih/import");
  await Promise.all([page.waitForNavigation(), page.locator("table a").first().click()]);
  await page.screenshot({ path: `${OUT}/03_ergebnis.png`, fullPage: true });
  await page.check("input[name=bestaetigt]");
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Import übernehmen')")]);
  const meldung = await page.locator(".flash-ok").first().textContent().catch(() => "");
  schritt("Import übernommen", meldung.includes("Import übernommen"), meldung.trim());
  // Excel (Instandhaltungsplan, Blatt Matrix automatisch)
  if (XLSX) {
    await page.goto(BASE + "/ih/import");
    await page.setInputFiles("input[name=datei]", XLSX);
    await Promise.all([page.waitForNavigation(), page.click("form[action='/ih/import'] button")]);
    schritt("Excel: Blatt Matrix gewählt", (await page.textContent("main")).includes("Tabellenblatt „Matrix“"));
    await Promise.all([page.waitForNavigation(), page.click("button:has-text('Prüfen und Testlauf')")]);
    await page.check("input[name=bestaetigt]");
    await Promise.all([page.waitForNavigation(), page.click("button:has-text('Import übernehmen')")]);
    const m2 = await page.locator(".flash-ok").first().textContent().catch(() => "");
    schritt("Matrix übernommen", m2.includes("geändert"), m2.trim());
  }
  // Übersicht, Liste, Detail
  await page.goto(BASE + "/ih");
  await page.screenshot({ path: `${OUT}/04_uebersicht.png`, fullPage: true });
  const zahl = await page.locator("main a.panel span.block").first().textContent();
  schritt("Übersicht zeigt Bauteile", Number(zahl) > 0, zahl);
  await page.goto(BASE + "/ih/anlagen?filter=sicher");
  const sicher = await page.locator("tbody tr").count();
  schritt("Filter PLT-Sicherheitseinrichtungen", !XLSX || sicher > 0, String(sicher));
  await page.goto(BASE + "/ih/anlagen");
  await page.screenshot({ path: `${OUT}/05_anlagen.png`, fullPage: false });
  await Promise.all([page.waitForNavigation(), page.locator("tbody tr a").first().click()]);
  schritt("Anlagenseite", (await page.locator("h1").count()) === 1 && (await page.textContent("main")).includes("Stammdaten"));
  await page.screenshot({ path: `${OUT}/06_anlage.png`, fullPage: true });
  // Suche im Kopf (Tag-Nr. ohne Leerzeichen)
  await page.fill("#scanfeld", "fic1040");
  await Promise.all([page.waitForNavigation(), page.press("#scanfeld", "Enter")]);
  schritt("Suche ohne Leerzeichen", page.url().includes("/ih/anlagen?q=fic1040"), String(await page.locator("tbody tr").count()));
  // dunkel + schmal
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(BASE + "/ih/anlagen");
  const breit = await page.evaluate(() => document.documentElement.scrollWidth);
  schritt("Schmal: kein seitliches Scrollen der Seite", breit <= 400, String(breit));
  await page.screenshot({ path: `${OUT}/07_schmal_dunkel.png`, fullPage: false });
  // zurück ins Lager ohne neue Anmeldung
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(BASE + "/ih");
  await Promise.all([page.waitForNavigation(), page.click("aside a[href='/bereich/lager']")]);
  schritt("Zurück zur Lagerverwaltung", page.url().endsWith("/") && (await page.textContent("aside")).includes("Lagerverwaltung"));
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
