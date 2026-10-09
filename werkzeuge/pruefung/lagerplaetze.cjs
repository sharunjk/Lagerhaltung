// Lagerplätze (Unterteilung nach Regal, Löschen) und Zurück-Knopf. Aufruf: node lagerplaetze.cjs <baseUrl> <ausgabeOrdner>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
async function login(page) {
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  // PC, dunkel
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  await login(page);
  // Plätze anlegen wie im Lager
  for (const code of ["C1-R2-1", "C1-R10-1", "C1-R1-2", "C1-F1", "C1-RR1-1"]) {
    await page.goto(BASE + "/lagerplaetze");
    await page.fill("aside input[name=code]", code);
    await Promise.all([page.waitForNavigation(), page.click("aside button.btn-primary")]);
  }
  await page.goto(BASE + "/lagerplaetze?leer=1", { waitUntil: "networkidle" });
  const reihen = await page.locator("main section.panel span.font-semibold").allTextContents();
  schritt("Unterteilung nach Regal", reihen.includes("R1") && reihen.indexOf("R2") < reihen.indexOf("R10"), reihen.join(","));
  await page.screenshot({ path: `${OUT}/lp_uebersicht.png`, fullPage: true });
  schritt("Startseite ohne Zurück-Knopf", await page.goto(BASE + "/").then(() => page.locator("button[aria-label=Zurück]").count()) === 0);
  // Zurück: Übersicht -> Platz -> Zurück
  await page.goto(BASE + "/lagerplaetze?leer=1");
  await Promise.all([page.waitForNavigation(), page.click("a[href*='code=C1-R10-1']")]);
  await Promise.all([page.waitForNavigation(), page.click("button[aria-label=Zurück]")]);
  schritt("Zurück zur vorherigen Seite", page.url().endsWith("/lagerplaetze?leer=1"), page.url());
  // Direkt geöffnet (wie App-Start auf einer Unterseite): Zurück führt zur Startseite
  const p2 = await ctx.newPage();
  await p2.goto(BASE + "/lagerplaetze/ansicht?code=C1-R10-1");
  await Promise.all([p2.waitForNavigation(), p2.click("button[aria-label=Zurück]")]);
  schritt("Ohne Vorgänger zur Startseite", new URL(p2.url()).pathname === "/", p2.url());
  // Löschen
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-RR1-1", { waitUntil: "networkidle" });
  await page.screenshot({ path: `${OUT}/lp_loeschen.png`, fullPage: true });
  let dialog = "";
  page.once("dialog", (d) => { dialog = d.message(); d.dismiss(); });
  await page.fill("input[name=bestaetigung]", "C1-RR1-1");
  await page.click("button:has-text('Löschen')");
  await page.waitForTimeout(500);
  schritt("Rückfrage vor dem Löschen", dialog.includes("endgültig"), dialog);
  schritt("Abbrechen löscht nichts", page.url().includes("C1-RR1-1"));
  page.once("dialog", (d) => d.accept());
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Löschen')")]);
  const meldung = (await page.locator("[role=status]").allTextContents()).join(" ");
  schritt("Gelöscht", /gelöscht/.test(meldung) && page.url().endsWith("/lagerplaetze"), meldung);
  // Platz mit Bestand: kein Löschfeld
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R1-1");
  schritt("Belegter Platz ohne Löschfeld", (await page.locator("input[name=bestaetigung]").count()) === 0);
  // Mobil
  const m = await browser.newContext({ viewport: { width: 360, height: 720 }, isMobile: true, hasTouch: true });
  const mp = await m.newPage();
  mp.on("pageerror", (e) => fehler.push(e.message));
  await login(mp);
  await mp.goto(BASE + "/m");
  schritt("Mobil Start ohne Zurück", (await mp.locator("header a[aria-label=Zurück]").count()) === 0);
  await Promise.all([mp.waitForNavigation(), mp.click("nav a[href='/m/suche']")]);
  const box = await mp.locator("header a[aria-label=Zurück]").boundingBox();
  schritt("Mobil Zurück mind. 44 px", box && box.width >= 44 && box.height >= 44, JSON.stringify(box));
  await mp.screenshot({ path: `${OUT}/lp_mobil.png` });
  await Promise.all([mp.waitForNavigation(), mp.click("header a[aria-label=Zurück]")]);
  schritt("Mobil Zurück", new URL(mp.url()).pathname === "/m", mp.url());
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  await browser.close();
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})();
