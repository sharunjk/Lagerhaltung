// 2.8.0: Schichtbuch im Browser mit Demodaten – Einrichten (Team zuordnen), Schicht beginnen, Meldung mit Asset aus der
// Auswahlliste, ergänzen, Schicht beenden mit Übergabe, Übergabe übernehmen, Liste, Excel-Export, Handy-Breite.
// Aufruf: node schichtbuch.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const [BASE, OUT] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const klick = (page, sel) => Promise.all([page.waitForNavigation(), page.click(sel)]);
const text = async (page, sel = "main") => (await page.textContent(sel)) || "";
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
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
  await page.goto(BASE + "/ih/anlagen/neu");
  await page.fill("input[name=code]", "P -20101 A");
  await page.selectOption("select[name=art]", "platz");
  await page.fill("input[name=bezeichnung]", "Demo-Pumpe");
  await klick(page, "button:has-text('Anlegen')");

  // Navigation und Einrichten
  await page.goto(BASE + "/ih");
  schritt("Navigation: Schichtbuch", (await page.locator("aside a[href='/ih/schichtbuch']").count()) === 1);
  await page.goto(BASE + "/ih/schichtbuch/einrichten");
  const teams = await page.locator("#teams input[name^=name_]").evaluateAll((e) => e.map((x) => x.value));
  schritt("Vier Teams vorbelegt", teams.join(",") === "Grün,Blau,Gelb,Rot", teams.join(","));
  await page.locator("#mitglieder select").first().selectOption({ label: "Grün" });
  await klick(page, "#mitglieder button");
  schritt("Benutzer Team Grün zugeordnet", (await page.locator(".flash-ok").first().textContent()).includes("Zuordnung gespeichert"));
  await page.screenshot({ path: `${OUT}/01_einrichten.png`, fullPage: true });

  // Schichtbeginn
  await page.goto(BASE + "/ih/schichtbuch");
  schritt("Dashboard: Ihr Team Grün", (await text(page)).includes("Ihr Team") && (await text(page)).includes("Schicht noch nicht begonnen"));
  await klick(page, "button:has-text('Schicht beginnen')");
  schritt("Schicht begonnen", (await text(page)).includes("Schicht läuft"));

  // Meldung
  await klick(page, "a:has-text('Neue Meldung')");
  await page.fill("input[name=titel]", "Pumpe undicht am Gleitring");
  await page.selectOption("select[name=ereignistyp]", "Störung");
  await page.click("label:has-text('Hoch')");
  await page.fill("textarea[name=beschreibung]", "Tropft ca. 1 l/h");
  await page.fill("input[name=asset]", "P -20101 A – Demo-Pumpe");
  await page.check("input[name=stillstand]");
  await page.fill("input[name=stillstand_h]", "1,5");
  await page.check("input[name=sicherheitsrelevant]");
  await page.screenshot({ path: `${OUT}/02_meldung_neu.png`, fullPage: true });
  await klick(page, "button:has-text('Speichern und Meldung öffnen')");
  const det = await text(page);
  schritt("Meldung gespeichert", det.includes("Pumpe undicht") && det.includes("Prio hoch") && det.includes("Stillstand 1,5 h") && det.includes("P -20101 A"));
  await page.fill("#ergaenzen textarea[name=text]", "Auffangwanne gestellt, Gleitring bestellt");
  await page.click("#ergaenzen label:has-text('In Bearbeitung')");
  await klick(page, "#ergaenzen button");
  schritt("Ergänzt, Status In Bearbeitung", (await text(page)).includes("Auffangwanne gestellt") && (await text(page)).includes("Status → In Bearbeitung"));
  await page.screenshot({ path: `${OUT}/03_meldung.png`, fullPage: true });

  // Schichtende mit Übergabe
  await page.goto(BASE + "/ih/schichtbuch");
  await page.screenshot({ path: `${OUT}/04_dashboard.png`, fullPage: true });
  await klick(page, "a:has-text('Schicht beenden')");
  schritt("Schichtende: Meldung vorausgewählt", await page.locator("input[name=ueb]").first().isChecked());
  await page.fill("textarea[name^=text_]", "Ersatzteil kommt morgen früh");
  await page.fill("textarea[name=notiz]", "Anlage auf Teillast");
  await page.screenshot({ path: `${OUT}/05_beenden.png`, fullPage: true });
  await klick(page, "button:has-text('Schicht beenden und übergeben')");
  const d2 = await text(page);
  schritt("Übergeben, Übergabe sichtbar", d2.includes("1 Punkt(e) an die nächste Schicht") && d2.includes("Ersatzteil kommt morgen früh") && d2.includes("Offene Übergaben (1)"));
  await page.fill("#uebergaben input[name=kommentar]", "Gelesen");
  await klick(page, "#uebergaben button:has-text('übernommen')");
  schritt("Übergabe übernommen", (await text(page)).includes("Offene Übergaben (0)"));

  // Liste und Export
  await page.goto(BASE + "/ih/schichtbuch/meldungen?nur=sicherheit");
  schritt("Liste mit Filter", (await text(page)).includes("Pumpe undicht"));
  const [dl] = await Promise.all([page.waitForEvent("download"), page.click("a:has-text('Excel')")]);
  schritt("Excel-Export", (await dl.suggestedFilename()).startsWith("Schichtbuch_"), await dl.suggestedFilename());
  await page.goto(BASE + "/ih/anlagen");
  await page.goto(BASE + (await page.locator("a:has-text('P -20101 A')").first().getAttribute("href")));
  schritt("Anlage zeigt die Meldung", (await text(page)).includes("Pumpe undicht"));

  // Handy
  await page.setViewportSize({ width: 390, height: 844 });
  const mid = (await page.locator("a[href^='/ih/schichtbuch/meldung/']").first().getAttribute("href"));
  for (const [pfad, name] of [["/ih/schichtbuch", "06_handy_dashboard"], ["/ih/schichtbuch/neu", "07_handy_neu"], [mid, "08_handy_meldung"],
                              ["/ih/schichtbuch/beenden", "09_handy_beenden"]]) {
    await page.goto(BASE + pfad);
    const breit = await page.evaluate(() => document.documentElement.scrollWidth);
    schritt(`Handy ohne seitliches Scrollen ${pfad}`, breit <= 400, String(breit));
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  }
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
