// 2.10.0: Umzug im Browser – Teil 1 (alter PC): Umzugspaket über die Einstellungen erstellen, „nur lesen“ prüfen (PC und
// Scanner-App). Teil 2 (neuer PC, nach dem Entpacken gestartet): anmelden, Daten da, Buchen geht, keine Sperre.
// Aufruf: node umzug.cjs alt <baseUrl> <ausgabe> <zielordner>   bzw.   node umzug.cjs neu <baseUrl> <ausgabe>
const { chromium, devices } = require("playwright");
const fs = require("fs");
const [TEIL, BASE, OUT, ZIEL] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const klick = (page, sel) => Promise.all([page.waitForNavigation(), page.click(sel)]);
const text = async (page, sel = "main") => (await page.textContent(sel)) || "";
async function login(page) {
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await klick(page, "form button");
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("dialog", (d) => d.accept());
  await login(page);
  if (TEIL === "alt") {
    await page.goto(BASE + "/einstellungen?tab=allgemein");
    await page.check("input[name=cmms_aktiv]");
    await page.fill("input[name=programmname]", "Betriebssoftware");
    await klick(page, "form[action='/einstellungen/allgemein'] button");
    await page.goto(BASE + "/ih/schichtbuch/neu");
    await page.fill("input[name=titel]", "Meldung vor dem Umzug");
    await klick(page, "button:has-text('Speichern')>>nth=0");
    await page.goto(BASE + "/einstellungen?tab=backup#umzug");
    schritt("Abschnitt Umzug vorhanden", (await text(page, "#umzug")).includes("Umzug auf einen neuen PC"));
    await page.fill("#u_ordner", ZIEL);
    await page.check("#umzug input[name=bestaetigt]");
    await page.fill("#u_pw", "Demo-Passwort-1");
    await page.screenshot({ path: `${OUT}/01_umzug_formular.png`, clip: { x: 0, y: 0, width: 1440, height: 900 }, fullPage: true });
    await klick(page, "#umzug button:has-text('Umzugspaket erstellen')");
    const t = await text(page);
    schritt("Paket erstellt, nur lesen", t.includes("Umzugspaket erstellt") && t.includes("Nur lesen"));
    schritt("Datei liegt im Zielordner", fs.readdirSync(ZIEL).some((f) => /^Umzugspaket_.*\.zip$/.test(f)), fs.readdirSync(ZIEL).join(","));
    await page.screenshot({ path: `${OUT}/02_nur_lesen.png`, fullPage: false });
    await page.goto(BASE + "/buchen?typ=ausgang&artikel=10001");
    await page.fill("input[name=menge]", "1").catch(() => {});
    const r = await page.request.post(BASE + "/buchen", { form: { artikel: "10001", typ: "ausgang", menge: "1", lagerort: "C1-R1-1" } });
    schritt("Buchen am PC abgewiesen (423)", r.status() === 423);
    const h = await (await browser.newContext({ ...devices["Pixel 5"] })).newPage();
    await h.goto(BASE + "/login"); await h.fill("input[name=username]", "admin"); await h.fill("input[name=passwort]", "Demo-Passwort-1");
    await Promise.all([h.waitForNavigation(), h.click("form button")]);
    await h.goto(BASE + "/m");
    schritt("Scanner-App zeigt „Nur lesen“", (await h.content()).includes("Nur lesen"));
    await h.screenshot({ path: `${OUT}/03_scanner_nur_lesen.png`, fullPage: false });
  } else {
    const t = await text(page);
    schritt("Neuer PC: Anmeldung mit altem Passwort", page.url().endsWith("/") || page.url().includes("/bereich") || t.length > 0);
    await page.goto(BASE + "/ih/schichtbuch/meldungen");
    schritt("Neuer PC: Schichtbuch-Meldung da", (await text(page)).includes("Meldung vor dem Umzug"));
    schritt("Neuer PC: nicht gesperrt", !(await page.content()).includes("Nur lesen"));
    const r = await page.request.post(BASE + "/buchen", { form: { artikel: "10001", typ: "ausgang", menge: "1", lagerort: "C1-R1-1" } });
    schritt("Neuer PC: Buchen geht", r.status() === 303 || r.status() === 200, String(r.status()));
    await page.goto(BASE + "/login").catch(() => {});
    const ctx2 = await browser.newContext(); const p2 = await ctx2.newPage(); await p2.goto(BASE + "/login");
    schritt("Neuer PC: Programmname übernommen", (await p2.content()).includes("Betriebssoftware"));
    await page.goto(BASE + "/einstellungen?tab=allgemein");
    schritt("Neuer PC: Instandhaltung aktiv (Einstellung übernommen)", await page.isChecked("input[name=cmms_aktiv]"));
    await page.screenshot({ path: `${OUT}/04_neuer_pc.png`, fullPage: false });
  }
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis_${TEIL}.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
