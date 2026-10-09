// Scanner-App: Profil, Abmelden/Benutzer wechseln, Geräteeinstellungen, Wechsel PC <-> Scanner. Aufruf: node profil.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const UA = "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 360, height: 720 }, userAgent: UA, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_INTERNET_DISCONNECTED/.test(m.text())) fehler.push(m.text()); });  // Abbruch ist hier simuliert
  // nicht angemeldet -> Anmeldung innerhalb /m
  await page.goto(BASE + "/m/profil");
  schritt("Anmeldung unter /m/login", new URL(page.url()).pathname === "/m/login", page.url());
  await page.fill("input[name=username]", "lager");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
  schritt("Nach Anmeldung auf Profil", new URL(page.url()).pathname === "/m/profil", page.url());
  await page.waitForTimeout(600);
  schritt("Kein PC-Knopf oben", (await page.locator("header a[href='/']").count()) === 0);
  const nav = await page.locator("nav a").allTextContents();
  schritt("Leiste mit Profil", nav.map((t) => t.trim()).join(",") === "Start,Entnahme,Suchen,Rückgabe,Profil", nav.join(","));
  const kl = await page.evaluate(() => [...document.querySelectorAll("nav a, main .btn, main label")].filter((e) => e.offsetParent).map((e) => e.getBoundingClientRect()).filter((b) => b.height < 44).length);
  schritt("Bedienelemente mind. 44 px hoch", kl === 0, String(kl));
  schritt("Verbindung angezeigt", (await page.textContent("main")).includes("verbunden"));
  await page.screenshot({ path: `${OUT}/profil_hell.png`, fullPage: true });
  // Darstellung dunkel, Ton aus
  await page.click("label:has-text('Dunkel')");
  await page.locator("label:has-text('Ton beim Scannen') input").uncheck();
  const st = await page.evaluate(() => ({ dunkel: document.documentElement.classList.contains("dark"), theme: localStorage.getItem("lv-theme"), ton: localStorage.getItem("lv-ton"), ein: LV.einstellung("lv-ton") }));
  schritt("Dunkel und Ton aus gespeichert", st.dunkel && st.theme === "dark" && st.ton === "aus" && st.ein === false, JSON.stringify(st));
  await page.reload();
  await page.waitForTimeout(300);
  schritt("Einstellungen bleiben nach Neuladen", (await page.evaluate(() => document.documentElement.classList.contains("dark"))) &&
    !(await page.locator("label:has-text('Ton beim Scannen') input").isChecked()));
  await page.screenshot({ path: `${OUT}/profil_dunkel.png`, fullPage: true });
  await page.click("label:has-text('Automatisch')");
  await page.click("button:has-text('Aktualisieren')");
  await page.waitForTimeout(800);
  schritt("Offline-Daten aktualisiert", /Artikelliste für den Offline-Modus vom/.test(await page.textContent("main")));
  // PC-Ansicht und zurück
  await Promise.all([page.waitForNavigation(), page.click("a:has-text('PC-Ansicht öffnen')")]);
  schritt("PC-Ansicht geöffnet", new URL(page.url()).pathname === "/", page.url());
  const knopf = page.locator("header a[aria-label='Scanner-Ansicht']");
  schritt("Scanner-Knopf in der PC-Ansicht sichtbar (360 px)", await knopf.isVisible());
  await page.screenshot({ path: `${OUT}/pc_handy.png` });
  await Promise.all([page.waitForNavigation(), knopf.click()]);
  schritt("Zurück in der Scanner-Ansicht", new URL(page.url()).pathname === "/m", page.url());
  // Benutzer wechseln mit einer wartenden Offline-Buchung
  await page.goto(BASE + "/m/profil");
  await page.evaluate(() => LV.queue.add({ typ: "ausgang", artikel: "10003", lagerort: "C1-R2-1", menge: "1" }));
  await ctx.setOffline(true);
  let frage = "";
  page.once("dialog", (d) => { frage = d.message(); d.dismiss(); });
  await page.click("button:has-text('Abmelden')");
  await page.waitForTimeout(800);
  schritt("Rückfrage bei nicht übertragener Buchung", /offline erfasste Buchung/.test(frage) && new URL(page.url()).pathname === "/m/profil", frage.slice(0, 60));
  await ctx.setOffline(false);  // löst sofort eine automatische Übertragung aus – Abmelden muss deren Ende abwarten
  page.on("dialog", (d) => { fehler.push("unerwartete Rückfrage: " + d.message().slice(0, 40)); d.dismiss(); });
  await Promise.all([page.waitForNavigation({ timeout: 15000 }), page.click("button:has-text('Abmelden')")]);
  schritt("Abgemeldet, Anmeldung in der App", new URL(page.url()).pathname === "/m/login", page.url());
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
  await page.goto(BASE + "/m/profil");
  schritt("Anderer Benutzer angemeldet", (await page.textContent("main")).includes("Administrator"));
  const q = await page.evaluate(() => LV.queue.alle().then((a) => a.length));
  await page.goto(BASE + "/bewegungen?q=10003");
  const zeile = await page.locator("tbody tr").first().textContent();
  schritt("Offline-Buchung vor dem Abmelden unter dem richtigen Namen übertragen", q === 0 && /lager/.test(zeile) && !/admin/i.test(zeile), `queue=${q} | ${zeile.replace(/\s+/g, " ").slice(0, 90)}`);
  // Passwort ändern in der App
  await page.goto(BASE + "/m/passwort");
  await page.fill("#alt", "falsch-falsch");
  await page.fill("#neu", "Neues-Passwort-9");
  await page.fill("#neu2", "Neues-Passwort-9");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
  schritt("Passwortfehler in der App-Ansicht", (await page.locator("nav a").count()) === 5 && /falsch/.test(await page.textContent("main")));
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  await browser.close();
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})();
