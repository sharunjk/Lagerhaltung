// 2.4.0: Artikel anlegen mit Fotos (PC + Scanner), direkt am Lagerplatz, Lieferant als Freitext, Etiketten-Schriftgröße.
// Aufruf: node anlegen.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.argv[2], OUT = process.argv[3];
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const UA = "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
// kleines, gültiges PNG (rotes Quadrat) als „Foto“
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR4nGP8z8BAEmAiTfmohlENQ0kDAD4/AR/0ZZ5ZAAAAAElFTkSuQmCC", "base64");
const foto = (name) => ({ name, mimeType: "image/png", buffer: PNG });
async function login(page, url = "/login") {
  await page.goto(BASE + url);
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
}
async function waehlen(page, knopf, dateien) {
  const [fc] = await Promise.all([page.waitForEvent("filechooser"), page.click(knopf)]);
  await fc.setFiles(dateien);
  return fc;
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  // ---------------------------------------------------------------- PC
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  await login(page);
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R2-1", { waitUntil: "networkidle" });
  await Promise.all([page.waitForNavigation(), page.click("text=Artikel hier anlegen")]);
  schritt("PC: Lagerplatz vorbelegt", (await page.inputValue("input[name=platz]")) === "C1-R2-1", page.url());
  await page.fill("input[name=bezeichnung]", "Gleitringdichtung 35 mm, Kohle/SiC, für Kreiselpumpe KSB Etanorm");
  await page.fill("input[name=anfangsbestand]", "3");
  // Lieferant: Vorschlagsliste enthält vorhandene
  const opts = await page.locator("datalist#lieferanten option").evaluateAll((os) => os.map((o) => o.value));
  schritt("PC: Lieferanten-Vorschläge", opts.includes("Muster Armaturen GmbH") && opts.includes("Prüftechnik Süd"), opts.join(", "));
  await page.fill("input[name=lieferant]", "Dichtungstechnik Ost GmbH");
  const fc = await waehlen(page, "text=Fotos / Dateien auswählen", [foto("vorne.png"), foto("seite.png")]);
  schritt("PC: Auswahl mehrerer Dateien", fc.isMultiple());
  await page.waitForTimeout(200);
  schritt("PC: Vorschau der Fotos", (await page.locator("#lv-fotos img").count()) === 2);
  await page.uncheck("input[name=etikett]");
  await page.screenshot({ path: `${OUT}/pc_neu.png`, fullPage: true });
  await Promise.all([page.waitForNavigation(), page.click("button:has-text('Artikel anlegen')")]);
  const nr = page.url().split("/artikel/")[1].split("?")[0];
  const txt = await page.textContent("main");
  schritt("PC: angelegt mit 2 Fotos", txt.includes("2 Foto(s)/Datei(en) gespeichert") && (await page.locator("#anhaenge img").count()) >= 2, nr);
  schritt("PC: Bestand am Platz", txt.includes("C1-R2-1"));
  await page.goto(BASE + "/lieferanten", { waitUntil: "networkidle" });
  schritt("PC: neuer Lieferant angelegt", (await page.textContent("main")).includes("Dichtungstechnik Ost GmbH"));
  // Etiketten-Schrift: Vorschau am Artikel
  await page.goto(BASE + "/artikel/" + nr, { waitUntil: "networkidle" });
  const zeilenAuto = await page.locator("#etikett-vorschau text").count();
  await page.selectOption("select[name=schrift]", "gross");
  await page.waitForTimeout(500);
  const zeilenGross = await page.locator("#etikett-vorschau text").count();
  schritt("PC: Etikett automatisch zweizeilig, groß einzeilig", zeilenAuto === 3 && zeilenGross === 2, `${zeilenAuto}/${zeilenGross}`);
  await page.selectOption("select[name=schrift]", "auto");
  await page.waitForTimeout(500);
  await page.locator("aside section").first().screenshot({ path: `${OUT}/pc_etikett_auto.png` });
  await Promise.all([page.waitForNavigation(), page.click("aside button:has-text('Drucken')")]);
  schritt("PC: Druck mit Schriftwahl", (await page.textContent("main")).includes("druck"), "");
  await page.goto(BASE + "/einstellungen?tab=drucker", { waitUntil: "networkidle" });
  await page.selectOption("select[name=schrift]", "klein");
  await Promise.all([page.waitForNavigation(), page.click("button[value=speichern]")]);
  schritt("PC: Schrift in Einstellungen gespeichert", (await page.inputValue("select[name=schrift]")) === "klein");
  await page.screenshot({ path: `${OUT}/pc_drucker.png`, fullPage: true });
  await page.selectOption("select[name=schrift]", "auto");
  await Promise.all([page.waitForNavigation(), page.click("button[value=speichern]")]);
  // Box: Artikel hier anlegen
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R1-1", { waitUntil: "networkidle" });
  await page.fill("#boxanzahl", "2");
  await Promise.all([page.waitForNavigation(), page.click("#boxen button:has-text('Anlegen')")]);
  await page.goto(BASE + "/lagerplaetze/ansicht?code=C1-R1-1-B2", { waitUntil: "networkidle" });
  await Promise.all([page.waitForNavigation(), page.click("text=Artikel hier anlegen")]);
  schritt("PC: Box vorbelegt", (await page.inputValue("input[name=platz]")) === "C1-R1-1-B2");
  // Bearbeiten: Lieferant vorbelegt
  await page.goto(BASE + "/artikel/" + nr + "/bearbeiten", { waitUntil: "networkidle" });
  schritt("PC: Bearbeiten zeigt Lieferant", (await page.inputValue("input[name=lieferant]")) === "Dichtungstechnik Ost GmbH");
  await ctx.close();

  // ---------------------------------------------------------------- Scanner / Handy
  const mctx = await browser.newContext({ viewport: { width: 360, height: 720 }, userAgent: UA, isMobile: true, hasTouch: true });
  const m = await mctx.newPage();
  m.on("pageerror", (e) => fehler.push("mobil: " + e.message));
  await login(m, "/m/login");
  await m.goto(BASE + "/m/platz?code=C1-R2-1", { waitUntil: "networkidle" });
  await Promise.all([m.waitForNavigation(), m.click("text=Neuer Artikel hier")]);
  schritt("Handy: Lagerplatz vorbelegt", (await m.inputValue("input[name=platz]")) === "C1-R2-1");
  await m.fill("input[name=bezeichnung]", "Näherungsschalter M18");
  await m.fill("input[name=lieferant]", "prüftechnik süd");
  let k = await waehlen(m, "text=Foto aufnehmen", [foto("kamera.png")]);
  const capture = await k.element().evaluate((e) => e.getAttribute("capture"));
  schritt("Handy: Kamera-Knopf öffnet Kamera", capture === "environment" && !k.isMultiple(), capture);
  k = await waehlen(m, "text=Aus Galerie", [foto("g1.png"), foto("g2.png")]);
  schritt("Handy: Galerie mit Mehrfachauswahl", k.isMultiple() && !(await k.element().evaluate((e) => e.hasAttribute("capture"))));
  await m.waitForTimeout(200);
  schritt("Handy: 3 Vorschaubilder", (await m.locator("#lv-fotos img").count()) === 3);
  await m.locator("#lv-fotos button[title=Entfernen]").first().click();
  schritt("Handy: Foto entfernen", (await m.locator("#lv-fotos img").count()) === 2);
  await m.uncheck("input[name=etikett]");
  await m.screenshot({ path: `${OUT}/handy_neu.png`, fullPage: true });
  await Promise.all([m.waitForNavigation(), m.click("button:has-text('Artikel anlegen')")]);
  const mt = await m.textContent("body");
  schritt("Handy: angelegt mit 2 Fotos", mt.includes("2 Foto(s) gespeichert"), m.url());
  await m.screenshot({ path: `${OUT}/handy_artikel.png`, fullPage: true });
  schritt("Handy: Artikelseite mit Kamera und Galerie", (await m.locator("text=Aus Galerie").count()) === 1 && (await m.locator("text=Foto aufnehmen").count()) === 1);
  await mctx.close();
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
