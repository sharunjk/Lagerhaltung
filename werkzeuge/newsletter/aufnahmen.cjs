// Rohbilder für den Newsletter (Schaufenster-Daten). Aufruf: node aufnahmen.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const UA = "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
async function login(page, user = "admin") {
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", user);
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
}
(async () => {
  const browser = await chromium.launch();
  const pc = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
  const p = await pc.newPage();
  await login(p);
  // Sicherung einmal ausführen, damit der Zustand grün ist
  await p.goto(BASE + "/einstellungen?tab=backup");
  await Promise.all([p.waitForNavigation(), p.click("button:has-text('Speichern und jetzt sichern')")]);
  await p.mouse.move(0, 0);
  for (const [name, url, scroll] of [["pc_uebersicht", "/", 0], ["pc_lagerplaetze", "/lagerplaetze", 0], ["pc_boxen", "/lagerplaetze/ansicht?code=C1-R2-3", 0],
                                     ["pc_nachbestellung", "/nachbestellung", 0], ["pc_artikel", "/artikel/10002", 0], ["pc_sicherung", "/einstellungen?tab=backup", 0]]) {
    await p.goto(BASE + url, { waitUntil: "networkidle" });
    await p.mouse.move(1, 1);
    await p.waitForTimeout(700);
    await p.screenshot({ path: `${OUT}/${name}.png` });
  }
  await p.goto(BASE + "/etiketten/druckansicht?nr=10007&nr=10017&platz=C1-R2-3-B1&platz=C1-R2-3-B2&platz=C1-R2-3-B3&platz=C1-R3-1", { waitUntil: "networkidle" });
  const etiketten = p.locator(".etikett-seite");
  for (let i = 0; i < await etiketten.count(); i++) await etiketten.nth(i).screenshot({ path: `${OUT}/etikett_${i + 1}.png` });
  // Handheld
  const m = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 3, userAgent: UA, isMobile: true, hasTouch: true });
  const mp = await m.newPage();
  await login(mp, "werkstatt");
  for (const [name, url] of [["m_start", "/m"], ["m_entnahme", "/m/buchen?typ=ausgang&artikel=10007"], ["m_platz", "/m/platz?code=C1-R2-3"],
                             ["m_artikel", "/m/artikel/10002"], ["m_profil", "/m/profil"]]) {
    await mp.goto(BASE + url, { waitUntil: "networkidle" });
    await mp.waitForTimeout(700);
    await mp.screenshot({ path: `${OUT}/${name}.png` });
  }
  // Entnahme: Menge eintragen, damit es "in Aktion" aussieht
  await mp.goto(BASE + "/m/buchen?typ=ausgang&artikel=10007", { waitUntil: "networkidle" });
  const menge = mp.locator("input[name=menge]");
  if (await menge.count()) { await menge.fill("2"); }
  await mp.waitForTimeout(300);
  await mp.screenshot({ path: `${OUT}/m_entnahme.png` });
  await browser.close();
})();
