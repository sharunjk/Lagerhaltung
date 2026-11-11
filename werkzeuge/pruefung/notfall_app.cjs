// 2.9.0 im Browser mit Demodaten: Schicht beenden und wieder öffnen, Meldung nachtragen, Papierformulare (auch als PDF),
// Instandhaltungs-App am Handy (Startseite, Leiste unten, Manifest, Service Worker), Einstellungen Notfall/Handy, Programmname.
// Aufruf: node notfall_app.cjs <baseUrl> <ausgabe> [pdf-ordner]
const { chromium, devices } = require("playwright");
const fs = require("fs");
const [BASE, OUT, PDF] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const klick = (page, sel) => Promise.all([page.waitForNavigation(), page.click(sel)]);
const text = async (page, sel = "main") => (await page.textContent(sel)) || "";
async function login(page, name, pw) {
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", name);
  await page.fill("input[name=passwort]", pw);
  await klick(page, "form button");
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  page.on("dialog", (d) => d.accept());
  await login(page, "admin", "Demo-Passwort-1");
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.check("input[name=cmms_aktiv]");
  await klick(page, "form[action='/einstellungen/allgemein'] button");
  // Techniker anlegen (für die Handy-App)
  await page.goto(BASE + "/einstellungen?tab=benutzer");
  await page.fill("form[action='/benutzer/speichern'] input[name=username]", "techniker1");
  await page.fill("form[action='/benutzer/speichern'] input[name=passwort]", "Test-Passwort-1");
  await page.selectOption("select[name=rolle]", "keine");
  await page.selectOption("select[name=rolle_ih]", "techniker");
  await klick(page, "form[action='/benutzer/speichern'] button:has-text('Speichern')");

  // Schicht beginnen, Meldung, beenden, wieder öffnen
  await page.goto(BASE + "/ih/schichtbuch");
  await klick(page, "button:has-text('Schicht beginnen')");
  await page.goto(BASE + "/ih/schichtbuch/neu");
  await page.fill("input[name=titel]", "Pumpe undicht");
  await klick(page, "button:has-text('Speichern')>>nth=0");
  await klick(page, "a:has-text('Schicht beenden')");
  await page.fill("textarea[name^=text_]", "Dichtung bestellt");
  await klick(page, "button:has-text('Schicht beenden und übergeben')");
  const b = await text(page);
  schritt("Beendet: Wieder öffnen angeboten", b.includes("Schicht beendet") && (await page.locator("button:has-text('Schicht wieder öffnen')").count()) === 1);
  schritt("Beendet: nächste Schicht vorzeitig beginnen angeboten", (await page.locator("button:has-text('Nächste Schicht beginnen')").count()) === 1);
  await page.screenshot({ path: `${OUT}/01_beendet.png`, fullPage: false });
  await klick(page, "button:has-text('Schicht wieder öffnen')");
  const o = await text(page);
  schritt("Wieder geöffnet, Übergaben ausgeblendet", o.includes("wieder offen") && o.includes("Schicht läuft") && o.includes("Offene Übergaben (0)"));
  await klick(page, "a:has-text('Schicht beenden')");
  schritt("Erneut beenden: Hinweis vorbelegt", (await page.inputValue("textarea[name^=text_]")) === "Dichtung bestellt");
  await klick(page, "button:has-text('Schicht beenden und übergeben')");

  // Nachtrag
  await klick(page, "a:has-text('Nachtragen')");
  schritt("Nachtrag-Formular offen", await page.isVisible("input[name=zeitpunkt]"));
  const gestern = new Date(Date.now() - 20 * 3600e3);
  const iso = new Date(gestern.getTime() - gestern.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  await page.fill("input[name=zeitpunkt]", iso);
  await page.selectOption("select[name=nachtrag_team]", { label: "Rot" });
  await page.fill("input[name=nachtrag_schichtfuehrer]", "Max M.");
  await page.fill("input[name=titel]", "Kühlwasserpumpe ausgefallen (Papier)");
  await page.screenshot({ path: `${OUT}/02_nachtrag.png`, fullPage: true });
  await klick(page, "button:has-text('Speichern und Meldung öffnen')");
  const n = await text(page);
  schritt("Nachtrag gespeichert und gekennzeichnet", n.includes("Nachtrag, erfasst") && n.includes("Rot") && n.includes("Nachtrag zum"));

  // Papierformulare
  for (const [pfad, name, titel] of [["/ih/schichtbuch/papier", "Notfall_Schichtbuch", "Schichtbuch – Papierformular"], ["/papier/lager", "Notfall_Lager", "Entnahmen und Eingänge"]]) {
    await page.goto(BASE + pfad);
    schritt(`Papierformular ${pfad}`, (await page.content()).includes(titel));
    await page.screenshot({ path: `${OUT}/03_${name}.png`, fullPage: false });
    const ziel = PDF ? `${PDF}/${name}.pdf` : `${OUT}/${name}.pdf`;
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: ziel, preferCSSPageSize: true, printBackground: true });
    await page.emulateMedia({ media: "screen" });
  }
  await page.goto(BASE + "/einstellungen?tab=notfall");
  schritt("Einstellungen: Reiter Notfall", (await text(page)).includes("Papierformulare für den Systemausfall"));
  await page.screenshot({ path: `${OUT}/04_notfall.png`, fullPage: false });
  await page.goto(BASE + "/einstellungen?tab=handy");
  schritt("Einstellungen: Anleitung Instandhaltungs-App mit QR", (await text(page)).includes("Instandhaltungs-App fürs Handy") && (await text(page)).includes("/ih/m"));
  await page.screenshot({ path: `${OUT}/05_handy_anleitung.png`, fullPage: true });

  // Programmname
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.fill("input[name=programmname]", "Betriebssoftware");
  await klick(page, "form[action='/einstellungen/allgemein'] button");
  const ctx3 = await browser.newContext(); const p3 = await ctx3.newPage();
  await p3.goto(BASE + "/login");
  schritt("Programmname bei der Anmeldung", (await p3.content()).includes("Betriebssoftware"));
  await ctx3.close();
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.fill("input[name=programmname]", "Lagerverwaltung");
  await klick(page, "form[action='/einstellungen/allgemein'] button");

  // Handy: Instandhaltungs-App als Techniker
  const hctx = await browser.newContext({ ...devices["Pixel 5"] });
  const h = await hctx.newPage();
  h.on("pageerror", (e) => fehler.push(e.message));
  await login(h, "techniker1", "Test-Passwort-1");
  await h.goto(BASE + "/ih/m");
  const st = await text(h);
  schritt("App-Startseite", st.includes("Neue Meldung") && st.includes("offene Übergaben") && st.includes("Tag-Nr. scannen"));
  schritt("Leiste unten sichtbar", await h.isVisible("nav[aria-label=App-Navigation]"));
  const man = await (await h.request.get(BASE + "/ih/manifest.webmanifest")).json();
  schritt("Manifest Instandhaltung", man.scope === "/ih/" && man.short_name === "Instandhaltung");
  await h.waitForTimeout(800);
  const sw = await h.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration("/ih/"); return r ? r.scope : null; });
  schritt("Service Worker registriert (Scope /ih/)", !!sw && sw.endsWith("/ih/"), String(sw));
  await h.screenshot({ path: `${OUT}/06_app_start.png`, fullPage: true });
  for (const pfad of ["/ih/m", "/ih/schichtbuch", "/ih/schichtbuch/neu", "/ih/auftraege", "/ih/anlagen"]) {
    await h.goto(BASE + pfad);
    const breit = await h.evaluate(() => document.documentElement.scrollWidth);
    schritt(`App ohne seitliches Scrollen ${pfad}`, breit <= 393 + 2, String(breit));
  }
  await h.click("nav[aria-label=App-Navigation] a:has-text('Meldung')");
  await h.waitForLoadState();
  schritt("Leiste: Meldung öffnet das Formular", h.url().endsWith("/ih/schichtbuch/neu"));
  await h.screenshot({ path: `${OUT}/07_app_meldung.png`, fullPage: false });
  // Ohne Verbindung: Hinweis aufs Papierformular
  await hctx.setOffline(true);
  await h.goto(BASE + "/ih/schichtbuch").catch(() => {});
  const off = await h.content();
  schritt("Ohne Verbindung: Hinweis Papierformular", off.includes("Papierformular") && off.includes("Nachtragen"));
  await h.screenshot({ path: `${OUT}/08_app_offline.png`, fullPage: false });
  await hctx.setOffline(false);
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
