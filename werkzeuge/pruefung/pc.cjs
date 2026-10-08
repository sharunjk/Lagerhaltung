// PC-Oberfläche: alle Seiten bei 1440x900 und 1280x720, hell/dunkel. Aufruf: node pc.cjs <baseUrl> <ausgabeOrdner>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const SEITEN = ["/", "/artikel", "/artikel?filter=melden", "/artikel?q=zzzz", "/artikel/10001", "/artikel/neu", "/artikel/10001/bearbeiten", "/buchen",
  "/buchen?artikel=10001&typ=ausgang", "/bewegungen", "/bewegungen?q=zzzz", "/ausleihen", "/reservierungen", "/lagerplaetze", "/lagerplaetze/ansicht?code=C1-R1-1",
  "/nachbestellung", "/bestellungen", "/inventur", "/inventur/1", "/lieferanten", "/auswertungen", "/import", "/protokoll", "/passwort",
  "/einstellungen?tab=allgemein", "/einstellungen?tab=benutzer", "/einstellungen?tab=drucker", "/einstellungen?tab=mail", "/einstellungen?tab=backup",
  "/einstellungen?tab=uebernahme", "/einstellungen?tab=api", "/einstellungen?tab=handy", "/artikel/99999", "/etiketten/druckansicht?nr=10001&nr=10003"];

(async () => {
  const browser = await chromium.launch();
  const ergebnis = [];
  for (const [w, h] of [[1440, 900], [1280, 720]]) {
    for (const schema of ["light", "dark"]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: schema });
      const page = await ctx.newPage();
      const fehler = [];
      page.on("pageerror", (e) => fehler.push(`${page.url()} pageerror: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") fehler.push(`${page.url()} console: ${m.text()}`); });
      page.on("response", (r) => { if (r.status() >= 500) fehler.push(`${r.url()} HTTP ${r.status()}`); });
      await page.goto(BASE + "/login");
      await page.fill("input[name=username]", "admin");
      await page.fill("input[name=passwort]", "Demo-Passwort-1");
      await Promise.all([page.waitForNavigation(), page.click("form button")]);
      for (const s of SEITEN) {
        const r = await page.goto(BASE + s, { waitUntil: "networkidle" });
        await page.waitForTimeout(100);
        const info = await page.evaluate(() => ({ breite: document.documentElement.scrollWidth, sicht: document.documentElement.clientWidth,
          dunkel: document.documentElement.classList.contains("dark"), titel: document.title }));
        ergebnis.push({ w, schema, seite: s, status: r.status(), hscroll: info.breite > info.sicht, dunkel: info.dunkel, titel: info.titel });
        if (w === 1440 || s === "/" || s === "/artikel")
          await page.screenshot({ path: `${OUT}/pc_${w}_${schema}_${s.replace(/[^a-z0-9]+/gi, "_")}.png`, fullPage: w === 1440 });
      }
      ergebnis.push({ w, schema, fehler });
      await ctx.close();
    }
  }
  fs.writeFileSync(`${OUT}/pc.json`, JSON.stringify(ergebnis, null, 1));
  for (const e of ergebnis) {
    if (e.fehler) console.log(e.w, e.schema, "Fehler:", e.fehler.length ? e.fehler.join("\n  ") : "keine");
    else if (e.status !== 200 || e.hscroll || (e.schema === "dark") !== e.dunkel) console.log(e.w, e.schema, e.seite, e.status, e.hscroll ? "HSCROLL" : "", "dunkel=" + e.dunkel);
  }
  await browser.close();
})();
