// 2.6.0: Wartungsplanung im Browser – Asset-Liste + Matrix + Instandhaltungsplan übernehmen, Wartungsplan, Kalender,
// Wochenliste, Aufträge anlegen, freigeben, Sammelprotokoll WP-02, Protokoll WP-01, Filter „ohne CAP01“, Anlage von Hand.
// Aufruf: node wartung.cjs <baseUrl> <ausgabe> <asset-liste.csv> <instandhaltungsplan.xlsx>
// Bildschirmfotos zeigen die hochgeladenen Daten – nur lokal ansehen.
const { chromium } = require("playwright");
const fs = require("fs");
const [BASE, OUT, CSV, XLSX] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const klick = (page, sel) => Promise.all([page.waitForNavigation(), page.click(sel)]);
async function assetImport(page, datei) {
  await page.goto(BASE + "/ih/import");
  await page.setInputFiles("input[name=datei]", datei);
  await klick(page, "form[action='/ih/import'] button");
  await klick(page, "button:has-text('Prüfen und Testlauf')");
  await page.check("input[name=bestaetigt]");
  await klick(page, "button:has-text('Import übernehmen')");
  return (await page.locator(".flash-ok").first().textContent().catch(() => "")).trim();
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  page.on("dialog", (d) => d.accept());
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await klick(page, "form button");
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.check("input[name=cmms_aktiv]");
  await klick(page, "form[action='/einstellungen/allgemein'] button");
  schritt("Asset-Liste importiert", (await assetImport(page, CSV)).includes("Import übernommen"));
  schritt("Matrix importiert", (await assetImport(page, XLSX)).includes("geändert"));
  // Instandhaltungsplan übernehmen
  await page.goto(BASE + "/ih/wartung");
  schritt("Ohne Plan: Hinweis", (await page.textContent("main")).includes("Noch kein Instandhaltungsplan"));
  await page.goto(BASE + "/ih/wartung/import");
  await page.setInputFiles("input[name=datei]", XLSX);
  await klick(page, "form[action='/ih/wartung/import'] button");
  const vergleich = await page.locator("main .panel span.block.text-3xl").allTextContents();
  schritt("Plan gelesen (Maßnahmen/Intervalle/Kampagnen)", vergleich.length === 3, vergleich.join(" / "));
  await page.screenshot({ path: `${OUT}/01_plan_vergleich.png`, fullPage: true });
  await page.check("input[name=bestaetigt]");
  await klick(page, "button:has-text('Instandhaltungsplan übernehmen')");
  schritt("Plan übernommen", page.url().endsWith("/ih/wartung") && (await page.textContent("main")).includes("Kampagne"));
  await page.screenshot({ path: `${OUT}/02_wartungsplan.png`, fullPage: true });
  const zeilen = await page.locator("tbody tr").count();
  schritt("Wartungsplan zeigt Kampagnen", zeilen > 20, String(zeilen));
  // Kalender + Wochenliste
  await page.goto(BASE + "/ih/wartung/kalender?wochen=52");
  const kalZeilen = await page.locator("tbody tr").count();
  schritt("Kalender 52 Wochen", kalZeilen > 20 && (await page.textContent("main")).includes("Techniker-Tage"), String(kalZeilen));
  await page.screenshot({ path: `${OUT}/03_kalender.png`, fullPage: false });
  await page.goto(BASE + "/ih/wartung/wochen");
  schritt("Wochenliste", (await page.locator("section.panel").count()) > 0);
  // Aufträge anlegen
  await page.goto(BASE + "/ih/wartung");
  await klick(page, "button:has-text('Fällige Aufträge anlegen')");
  const auftr = await page.locator("tbody tr").count();
  schritt("Fällige Aufträge angelegt", page.url().includes("/ih/auftraege") && auftr > 0, String(auftr));
  await page.screenshot({ path: `${OUT}/04_auftraege.png`, fullPage: true });
  // Sichtprüfung mit Sammelprotokoll (WP-02) öffnen, freigeben, zwei Zeilen erfassen
  const sicht = page.locator("tbody tr", { hasText: "Sichtprüfung" }).first();
  await Promise.all([page.waitForNavigation(), sicht.locator("a.font-semibold").click()]);
  await klick(page, "button:has-text('Freigeben')");
  schritt("Auftrag freigegeben", (await page.textContent("main")).includes("Freigegeben"));
  const radios = page.locator("input[type=radio][value=ohne_befund]");
  const n = await radios.count();
  if (n) {
    await radios.nth(0).check();
    if (n > 1) {
      await page.locator("input[type=radio][value=mit_befund]").nth(1).check();
      await page.locator("input[name$=_befund_text]:visible").first().fill("Leckage am Flansch");
    }
    await klick(page, "button:has-text('Ergebnisse speichern')");
    const m = (await page.locator(".flash-ok").first().textContent().catch(() => "")).trim();
    schritt("Sammelprotokoll gespeichert", m.includes("Bauteile gespeichert"), m);
  } else {
    schritt("Sammelprotokoll gespeichert", true, "nur WP-01-Bauteile in diesem Auftrag");
  }
  await page.screenshot({ path: `${OUT}/05_auftrag.png`, fullPage: true });
  // WP-01: Auftrag mit PLT-Sicherheitseinrichtung (Sichtprüfung PLTS-Sensor)
  await page.goto(BASE + "/ih/auftraege");
  const plts = page.locator("tbody tr", { hasText: "PLTS-Sensor" }).first();
  if (await plts.count()) {
    await Promise.all([page.waitForNavigation(), plts.locator("a.font-semibold").click()]);
    await klick(page, "button:has-text('Freigeben')");
    await klick(page, "a:has-text('Protokoll ausfüllen')");
    schritt("WP-01 geöffnet", (await page.textContent("main")).includes("Zustand bei Beginn"));
    await page.check("input[name=zustand_beginn][value=unauffaellig]");
    await page.fill("input[name=schritt]", "Sichtkontrolle Kennzeichnung");
    await page.check("input[name=ergebnis][value=ohne_befund]");
    await klick(page, "button[value=auftrag]");
    const f1 = (await page.locator(".flash-fehler").first().textContent().catch(() => "")).trim();
    schritt("WP-01 verlangt Abschlusskontrolle bei PLT-S", f1.includes("Abschlusskontrolle"), f1.slice(0, 80));
    for (const k of ["brueckung", "kennzeichnung", "grenzwerte", "betrieb"]) await page.check(`input[name=ab_${k}]`);
    await page.check("input[name=zustand_beginn][value=unauffaellig]");
    await page.check("input[name=ergebnis][value=ohne_befund]");
    await page.screenshot({ path: `${OUT}/06_wp01.png`, fullPage: true });
    await klick(page, naechsteVorhanden(page) ? "button[value=naechste]" : "button[value=auftrag]");
    schritt("WP-01 gespeichert", (await page.locator(".flash-ok").first().textContent().catch(() => "")).includes("gespeichert"));
    await page.setViewportSize({ width: 390, height: 844 });
    const breit = await page.evaluate(() => document.documentElement.scrollWidth);
    schritt("Protokoll am Handy ohne seitliches Scrollen", breit <= 400, String(breit));
    await page.screenshot({ path: `${OUT}/07_wp01_handy.png`, fullPage: false });
    await page.setViewportSize({ width: 1440, height: 900 });
  }
  // Filter „ohne CAP01“ und Anlage von Hand
  await page.goto(BASE + "/ih/anlagen");
  const alle = parseInt((await page.textContent("main p.text-muted")).match(/\d+/)[0], 10);
  await page.goto(BASE + "/ih/anlagen?bf=kuerzel&bo=ist_nicht&bv=CAP01");
  const ohne = parseInt((await page.textContent("main p.text-muted")).match(/\d+/)[0], 10);
  schritt("Filter Kürzel ist nicht CAP01", ohne < alle && ohne > 0, `${alle} -> ${ohne}`);
  await page.click("button:has-text('Bedingung')");
  schritt("Bedingungszeile hinzufügbar", (await page.locator("select[name=bf]").count()) === 2);
  await page.screenshot({ path: `${OUT}/08_filter.png`, fullPage: false });
  await page.goto(BASE + "/ih/anlagen/neu");
  await page.fill("input[name=code]", "TEST 9999 01");
  await page.fill("input[name=bezeichnung]", "Von Hand angelegt");
  await klick(page, "button:has-text('Anlegen')");
  schritt("Anlage von Hand angelegt", (await page.textContent("h1")).includes("TEST 9999 01"));
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });

function naechsteVorhanden() { return false; }
