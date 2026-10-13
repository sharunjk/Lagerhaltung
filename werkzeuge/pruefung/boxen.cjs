// 2.4.0: Sichtlagerboxen und Weinrot-Markierung im Browser. Aufruf: node boxen.cjs <baseUrl> <ausgabe>
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
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  await login(page);
  // Übersicht: rote Plätze vorhanden (Demo hat Artikel unter Mindestbestand)
  await page.goto(BASE + "/lagerplaetze", { waitUntil: "networkidle" });
  const rot = await page.locator("main section a .bintag-nachbestellen").count();
  schritt("Weinrote Plätze in der Übersicht", rot > 0, `${rot}`);
  const farbe = await page.locator("main section a .bintag-nachbestellen").first().evaluate((e) => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color]);
  schritt("Weinrot mit weißer Schrift", farbe[0] === "rgb(128, 22, 50)" && farbe[1] === "rgb(255, 255, 255)", farbe.join(" / "));
  await page.screenshot({ path: `${OUT}/uebersicht_hell.png`, fullPage: true });
  // Boxen an C1-R2-1 anlegen
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R2-1", { waitUntil: "networkidle" });
  await page.fill("#boxanzahl", "10");
  await Promise.all([page.waitForNavigation(), page.click("#boxen button:has-text('Anlegen')")]);
  const anzahl = await page.locator("#boxen tbody tr").count();
  schritt("10 Boxen angelegt", anzahl === 10, `${anzahl}`);
  // Inhalt eintragen (bleibt auf der Platzseite)
  const inhalte = ["Schrauben M6", "Schrauben M8", "Muttern M8", "Unterlegscheiben", "O-Ringe", "Dichtungen DN25", "Dichtungen DN50", "Kabelbinder", "Sicherungen", "Splinte"];
  for (let i = 0; i < 3; i++) {
    await page.locator("#boxen tbody tr").nth(i).locator("input[name=beschreibung]").fill(inhalte[i]);
    await Promise.all([page.waitForNavigation(), page.locator("#boxen tbody tr").nth(i).locator("button[title='Inhalt speichern']").click()]);
  }
  schritt("Inhalt gespeichert, Seite bleibt beim Platz", page.url().includes("code=C1-R2-1") && (await page.locator("#boxen input[value='Muttern M8']").count()) === 1, page.url());
  // Buchen in eine Box über das normale Buchungsformular
  await page.goto(BASE + "/buchen?artikel=10003&typ=eingang");
  await page.fill("input[name=lagerort], input[name=platz]", "C1-R2-1-B2").catch(() => {});
  const feld = await page.locator("input[name=lagerort]").count() ? "input[name=lagerort]" : "input[name=platz]";
  await page.fill(feld, "C1-R2-1-B2");
  await page.fill("input[name=menge]", "25");
  await Promise.all([page.waitForNavigation(), page.click("form button.btn-primary")]);
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R2-1", { waitUntil: "networkidle" });
  const zeile = await page.locator("#boxen tbody tr").nth(1).textContent();
  schritt("Buchung in Box sichtbar", /10003/.test(zeile) && /25/.test(zeile), zeile.replace(/\s+/g, " ").slice(0, 80));
  await page.screenshot({ path: `${OUT}/platz_boxen.png`, fullPage: true });
  // Übersicht: Kachel "· 10 Boxen", keine Box-Kacheln
  await page.goto(BASE + "/lagerplaetze", { waitUntil: "networkidle" });
  const kachel = await page.locator("main section a[href*='code=C1-R2-1']").first().textContent();
  schritt("Kachel zeigt Boxen", /10 Boxen/.test(kachel), kachel.replace(/\s+/g, " "));
  schritt("Keine eigenen Box-Kacheln", (await page.locator("main section a[href*='-B']").count()) === 0);
  // Druckansicht aller Box-Etiketten
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R2-1");
  await Promise.all([page.waitForNavigation(), page.click("#boxen a:has-text('Über den Browser')")]);
  const etiketten = await page.locator(".etikett-seite").count();
  schritt("Druckansicht mit 10 Box-Etiketten", etiketten === 10 && (await page.textContent("body")).includes("Muttern M8"), `${etiketten}`);
  await page.screenshot({ path: `${OUT}/etiketten.png` });
  // Box per Scan (USB-Scanner tippt Code + Enter)
  await page.goto(BASE + "/");
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await Promise.all([page.waitForNavigation(), page.keyboard.type("C1-R2-1-B3\n", { delay: 8 })]);
  schritt("Box-Etikett scannen öffnet die Box", page.url().endsWith("code=C1-R2-1-B3") && (await page.textContent("main")).includes("Muttern M8"), page.url());
  // Box entfernen: aufklappen, Code eintippen, Rückfrage
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R2-1", { waitUntil: "networkidle" });
  const zeileB10 = page.locator("#boxen tbody tr", { hasText: "C1-R2-1-B10" });
  await zeileB10.locator("summary:has-text('Entfernen')").click();
  await zeileB10.locator("input[name=bestaetigung]").fill("C1-R2-1-B10");
  let frage = "";
  page.once("dialog", (d) => { frage = d.message(); d.dismiss(); });
  await zeileB10.locator("form button.btn-danger").click();
  await page.waitForTimeout(300);
  schritt("Box entfernen: Rückfrage, Abbrechen lässt sie stehen", /B10 entfernen/.test(frage) && (await page.locator("#boxen tbody tr").count()) === 10, frage);
  page.once("dialog", (d) => d.accept());
  await Promise.all([page.waitForNavigation(), zeileB10.locator("form button.btn-danger").click()]);
  schritt("Box entfernt, zurück bei den Boxen", (await page.locator("#boxen tbody tr").count()) === 9 && page.url().includes("code=C1-R2-1"), page.url());
  const b2 = page.locator("#boxen tbody tr", { hasText: "C1-R2-1-B2" });
  schritt("Box mit Inhalt nicht entfernbar", (await b2.locator("summary:has-text('Entfernen')").count()) === 0 && /nicht leer/.test(await b2.textContent()));
  await page.screenshot({ path: `${OUT}/box_entfernt.png`, fullPage: true });
  // dunkel
  const d = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const dp = await d.newPage();
  await login(dp);
  await dp.goto(BASE + "/lagerplaetze", { waitUntil: "networkidle" });
  await dp.screenshot({ path: `${OUT}/uebersicht_dunkel.png`, fullPage: true });
  const rotPlatz = await dp.locator("main section a .bintag-nachbestellen").first().textContent();
  await dp.goto(BASE + "/lagerplaetze/ansicht?code=" + encodeURIComponent(rotPlatz.trim()), { waitUntil: "networkidle" });
  await dp.screenshot({ path: `${OUT}/platz_rot_dunkel.png`, fullPage: true });
  schritt("Platzseite zeigt Nachbestellhinweis", (await dp.textContent("main")).includes("Nachbestellung nötig"), rotPlatz);
  // Handy
  const m = await browser.newContext({ viewport: { width: 360, height: 720 }, isMobile: true, hasTouch: true });
  const mp = await m.newPage();
  mp.on("pageerror", (e) => fehler.push(e.message));
  await login(mp);
  await mp.goto(BASE + "/m/platz?code=C1-R2-1", { waitUntil: "networkidle" });
  const boxenM = await mp.locator("main ul").nth(1).locator("li").count();
  const hs = await mp.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  schritt("Handy: Boxen am Platz, ohne Querscrollen", boxenM === 9 && !hs, `${boxenM} hs=${hs}`);
  await mp.screenshot({ path: `${OUT}/handy_platz.png`, fullPage: true });
  await Promise.all([mp.waitForNavigation(), mp.locator("main ul").nth(1).locator("li a").nth(1).click()]);
  schritt("Handy: Box öffnen", mp.url().includes("C1-R2-1-B2") && (await mp.textContent("main")).includes("gehört zu"), mp.url());
  await mp.screenshot({ path: `${OUT}/handy_box.png`, fullPage: true });
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  await browser.close();
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})();
