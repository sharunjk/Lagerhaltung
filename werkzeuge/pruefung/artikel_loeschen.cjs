// 2.4.0: Artikel endgültig löschen im Browser. Aufruf: node artikel_loeschen.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
  // Testartikel ohne Bestand anlegen
  await page.goto(BASE + "/artikel/neu");
  await page.fill("input[name=nummer]", "90001");
  await page.fill("input[name=bezeichnung]", "Tippfehler-Artikel");
  await Promise.all([page.waitForNavigation(), page.click("form button.btn-primary")]);
  schritt("Artikel angelegt", page.url().includes("/artikel/90001"), page.url());
  await page.click("summary:has-text('Artikel endgültig löschen')");
  await page.screenshot({ path: `${OUT}/loeschen.png`, fullPage: true });
  let frage = "";
  page.once("dialog", (d) => { frage = d.message(); d.dismiss(); });
  await page.fill("input[name=bestaetigung]", "90001");
  await page.click("details button:has-text('Löschen')");
  await page.waitForTimeout(400);
  schritt("Rückfrage, Abbrechen löscht nichts", /endgültig/.test(frage) && page.url().includes("/artikel/90001"), frage);
  page.once("dialog", (d) => d.accept());
  await Promise.all([page.waitForNavigation(), page.click("details button:has-text('Löschen')")]);
  const meldung = (await page.locator("[role=status]").allTextContents()).join(" ");
  schritt("Gelöscht", /90001 gelöscht/.test(meldung) && new URL(page.url()).pathname === "/artikel", meldung);
  const r = await page.goto(BASE + "/artikel/90001");
  schritt("Artikelseite meldet nicht gefunden", /nicht gefunden|gibt es nicht/.test(await page.textContent("main")));
  // Artikel mit Bestand: kein Löschfeld
  await page.goto(BASE + "/artikel/10001");
  await page.click("summary:has-text('Artikel endgültig löschen')");
  schritt("Mit Bestand kein Löschfeld, Hinweis", (await page.locator("input[name=bestaetigung]").count()) === 0 && /noch .* Bestand/.test(await page.textContent("details:has-text('endgültig')")));
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  await browser.close();
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})();
