// Mobile Prüfung der Scanner-App: 360x720, Android-UA. Aufruf: node mobil.cjs <baseUrl> <ausgabeOrdner>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const UA = "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
const SEITEN = ["/m", "/m/buchen?typ=ausgang", "/m/buchen?typ=ausgang&artikel=10001", "/m/buchen?typ=eingang&artikel=10003",
  "/m/buchen?typ=umbuchung&artikel=10001", "/m/buchen?typ=inventur&artikel=10006", "/m/buchen?typ=ausleihe&artikel=10008",
  "/m/artikel/10001", "/m/platz?code=C1-R1-1", "/m/suche?q=Kugel", "/m/neu", "/m/korb", "/m/korb?artikel=10003", "/m/reservierungen",
  "/m/wareneingang", "/m/rueckgabe", "/m/inventur/1", "/m/inventur/1?platz=C1-R1-1", "/m/offline"];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 360, height: 720 }, userAgent: UA, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`${page.url()} pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(`${page.url()} console: ${m.text()}`); });
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "lager");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("button[type=submit], form button")]);
  const ergebnis = { start: page.url(), seiten: [] };
  for (const s of SEITEN) {
    const r = await page.goto(BASE + s, { waitUntil: "networkidle" });
    await page.waitForTimeout(150);
    const info = await page.evaluate(() => {
      const de = document.documentElement;
      const klein = [];
      for (const el of document.querySelectorAll("a, button, input:not([type=hidden]), select, textarea, summary, [role=button], label.btn")) {
        const st = getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden" || el.closest(".hidden, [hidden], #kamera")) continue;
        const b = el.getBoundingClientRect();
        if (!b.width || !b.height) continue;
        if (b.height < 44 || b.width < 44) {
          const t = (el.innerText || el.value || el.getAttribute("aria-label") || el.name || el.tagName).trim().replace(/\s+/g, " ").slice(0, 30);
          klein.push(`${el.tagName.toLowerCase()} "${t}" ${Math.round(b.width)}x${Math.round(b.height)}`);
        }
      }
      return { breite: de.scrollWidth, sicht: de.clientWidth, klein };
    });
    ergebnis.seiten.push({ seite: s, status: r.status(), horizontal: info.breite > info.sicht ? `${info.breite}>${info.sicht}` : "", klein: info.klein });
    await page.screenshot({ path: `${OUT}/m_${s.replace(/[^a-z0-9]+/gi, "_")}.png`, fullPage: true });
  }
  // Hardware-Scan ohne fokussiertes Feld (Infoseite): schnelle Tastatureingabe + Enter
  await page.goto(BASE + "/m/artikel/10001", { waitUntil: "networkidle" });
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await Promise.all([page.waitForNavigation({ timeout: 5000 }).catch(() => null), page.keyboard.type("10002\n", { delay: 8 })]);
  ergebnis.scan_ohne_feld = page.url();
  await page.goto(BASE + "/m/artikel/10001", { waitUntil: "networkidle" });
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await Promise.all([page.waitForNavigation({ timeout: 5000 }).catch(() => null), page.keyboard.type("C2-F1\n", { delay: 8 })]);
  ergebnis.scan_platz_ohne_feld = page.url();
  // Hardware-Scan mit fokussiertem Artikelfeld auf der Buchungsseite
  await page.goto(BASE + "/m/buchen?typ=ausgang", { waitUntil: "networkidle" });
  ergebnis.fokus_buchen = await page.evaluate(() => document.activeElement && (document.activeElement.id || document.activeElement.name));
  await Promise.all([page.waitForNavigation({ timeout: 5000 }).catch(() => null), page.keyboard.type("10003\n", { delay: 8 })]);
  await page.waitForTimeout(400);
  ergebnis.scan_mit_feld_url = page.url();
  ergebnis.scan_mit_feld_fokus = await page.evaluate(() => document.activeElement && (document.activeElement.id || document.activeElement.name));
  // PWA: Manifest + Service Worker (http://127.0.0.1 gilt als sicherer Kontext)
  await page.goto(BASE + "/m", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  ergebnis.sw = await page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration("/m"); return r ? (r.active ? "aktiv" : "registriert") : "keiner"; });
  ergebnis.manifest = await page.evaluate(async () => { const r = await fetch("/m/manifest.webmanifest"); return r.ok ? await r.json() : r.status; });
  ergebnis.fehler = fehler;
  fs.writeFileSync(`${OUT}/mobil.json`, JSON.stringify(ergebnis, null, 1));
  console.log(JSON.stringify(ergebnis, null, 1));
  await browser.close();
})();
