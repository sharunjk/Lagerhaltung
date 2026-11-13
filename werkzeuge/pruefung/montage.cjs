// 2.12.0 im Browser mit Demodaten: Set im Lager (anlegen, Teil entnehmen, Warnung), Stutzenübersicht (Import der nachgebildeten
// Vorlage), Montageprotokoll als Operator in zwei Schritten (Vorbelegung, Skizze anklicken, „#↓“, Abschluss), Druck und Excel.
// Aufruf: node montage.cjs <baseUrl> <ausgabe> <demo-vorlage.xlsx>
const { chromium, devices } = require("playwright");
const fs = require("fs");
const [BASE, OUT, VORLAGE] = process.argv.slice(2);
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
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  page.on("dialog", (d) => d.accept());
  await login(page, "admin", "Demo-Passwort-1");
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.check("input[name=cmms_aktiv]");
  await klick(page, "form[action='/einstellungen/allgemein'] button");
  await page.goto(BASE + "/einstellungen?tab=benutzer");
  await page.fill("form[action='/benutzer/speichern'] input[name=username]", "monteur1");
  await page.fill("form[action='/benutzer/speichern'] input[name=passwort]", "Test-Passwort-1");
  await page.selectOption("select[name=rolle]", "keine");
  await page.selectOption("select[name=rolle_ih]", "operator");
  await klick(page, "form[action='/benutzer/speichern'] button:has-text('Speichern')");

  // ---------------- 1. Set im Lager
  for (const [nr, bez] of [["20001", "Pulsationsdämpfer Demo"], ["20002", "Membran Demo"]]) {
    await page.goto(BASE + "/artikel/neu");
    await page.fill("input[name=nummer]", nr);
    await page.fill("input[name=bezeichnung]", bez);
    await klick(page, "button:has-text('Artikel anlegen')");
  }
  await page.goto(BASE + "/artikel/neu");
  await page.fill("input[name=nummer]", "20100");
  await page.fill("input[name=bezeichnung]", "Ersatzteilset Pumpenmodul Demo");
  await page.fill("input[name=platz]", "C3-R1-1");
  await page.fill("input[name=anfangsbestand]", "2");
  await page.uncheck("input[name=etikett]");
  schritt("Set-Bereich zunächst zugeklappt", !(await page.isVisible("input[name=set_teil]")));
  await page.check("input[name=ist_set]");
  await page.fill("input[name=set_teil] >> nth=0", "20001 – Pulsationsdämpfer Demo");
  await page.click("button:has-text('+ Weiteres Teil')");
  await page.fill("input[name=set_teil] >> nth=1", "20002");
  await page.fill("input[name=set_menge] >> nth=1", "2");
  await page.click("button:has-text('+ Weiteres Teil')");
  await page.fill("input[name=set_teil] >> nth=2", "10003");
  await page.fill("input[name=set_menge] >> nth=2", "4");
  await page.locator("#set").screenshot({ path: `${OUT}/01_set_formular.png` });
  await klick(page, "button:has-text('Artikel anlegen')");
  let t = await text(page);
  schritt("Set angelegt, Inhalt sichtbar", t.includes("Inhalt des Sets") && t.includes("Membran Demo") && t.includes("Vollständig"));
  await page.click("summary:has-text('Einzelnes Teil aus dem Set entnehmen')");
  await page.selectOption("select[name=teil]", "20002");
  await page.fill("#set input[name=menge]", "1");
  await page.fill("#set input[name=zweck]", "Pumpe P-101 Demo");
  await klick(page, "button:has-text('Teil entnehmen')");
  t = await text(page);
  schritt("Teil entnommen: Set unvollständig", t.includes("Set unvollständig") && t.includes("es fehlt: 1 × 20002"));
  await page.screenshot({ path: `${OUT}/02_set_unvollstaendig.png`, fullPage: false });
  await page.goto(BASE + "/buchen?artikel=20100&typ=ausgang");
  await page.waitForSelector("text=Set unvollständig");
  schritt("Buchen zeigt Warnung und Auswahl", (await page.content()).includes("Das entnommene Set ist das, in dem"));
  await page.screenshot({ path: `${OUT}/03_buchen_warnung.png`, fullPage: false });
  await page.goto(BASE + "/artikel/10003");
  schritt("Teil zeigt „Auch enthalten in Sets“", (await text(page)).includes("Auch enthalten in Sets"));
  const h = await (await browser.newContext({ ...devices["Pixel 5"] })).newPage();
  await login(h, "admin", "Demo-Passwort-1");
  await h.goto(BASE + "/m/artikel/20100");
  schritt("Scanner-App zeigt Warnung", (await h.content()).includes("Set unvollständig"));
  await h.screenshot({ path: `${OUT}/04_scanner_set.png`, fullPage: false });

  // ---------------- 2. Stutzenübersicht
  await page.goto(BASE + "/ih/montage/stutzen");
  schritt("Menü: Montageunterstützung mit Unterpunkten", (await page.textContent("aside")).includes("Stutzenübersicht"));
  await page.goto(BASE + "/ih/montage/stutzen-import");
  await page.setInputFiles("input[name=datei]", VORLAGE);
  await klick(page, "button:has-text('Importieren')");
  schritt("Import: 5 Stutzen", (await text(page)).includes("5 Stutzen neu angelegt"));
  await page.goto(BASE + "/ih/montage/stutzen");
  await page.screenshot({ path: `${OUT}/05_stutzenuebersicht.png`, fullPage: true });
  await page.click("a:has-text('DS 1')");
  await page.waitForLoadState();
  await page.click("a:has-text('Bearbeiten')");
  await page.waitForLoadState();
  await page.fill("input[name=schrauben_anzahl]", "8");
  await page.fill("input[name=schraube_typ]", "ISO 4014");
  await page.fill("input[name=schraube_werkstoff]", "A4-70");
  await klick(page, "button:has-text('Speichern')");
  schritt("Stutzen: Skizze mit 8 Löchern", (await page.locator("main aside svg circle").count()) === 10);
  await page.screenshot({ path: `${OUT}/06_stutzen_detail.png`, fullPage: false });

  // ---------------- 3. Montageprotokoll als Operator
  const op = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })).newPage();
  op.on("pageerror", (e) => fehler.push(e.message));
  op.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  op.on("dialog", (d) => d.accept());
  await login(op, "monteur1", "Test-Passwort-1");
  await op.goto(BASE + "/ih/montage/protokolle/neu");
  await op.fill("#stz", "DS 1 – Demo-Stutzen (Reaktor)");
  await op.dispatchEvent("#stz", "change");
  await op.waitForTimeout(200);
  schritt("Vorbelegung: 8 Zeilen, Soll 120, darunter #", (await op.locator("input[name^=s][name$=_soll_nm]").count()) === 8
    && (await op.inputValue("input[name=s0_soll_nm]")) === "120" && (await op.inputValue("input[name=s5_soll_nm]")) === "#");
  schritt("Vorbelegung Dichtungen mit Nenndicke", (await op.inputValue("input[name=d0_dichtungsart]")).startsWith("MCR") && (await op.inputValue("input[name=d0_nenndicke]")) === "3,2");
  await op.fill("input[name=anlage]", "Demo-Reaktor");
  await op.fill("input[name=monteur]", "M. Muster");
  await op.fill("input[name=pruefer]", "P. Prüfer");
  await op.fill("input[name=arbeitsauftrag]", "WO-DEMO-77");
  await op.fill("input[name=reinigung]", "Dichtflächen gereinigt");
  await op.screenshot({ path: `${OUT}/07_protokoll_vorher.png`, fullPage: true });
  await klick(op, "button:has-text('Zwischenspeichern')");
  schritt("Zwischengespeichert (Entwurf)", (await text(op)).includes("gespeichert") && op.url().match(/protokolle\/\d+$/));
  // nach der Montage: Reihenfolge über Kreuz anklicken, Ist-Drehmoment eintragen
  for (const loch of [1, 5, 3, 7, 2, 6, 4, 8]) await op.click(`[data-loch="${loch}"]`);
  schritt("Alle 8 Schrauben nummeriert", (await text(op)).includes("Alle 8 Schrauben nummeriert"));
  await op.fill("input[name=s0_ist_nm]", "118");
  await op.click("th:has-text('Ist [Nm]') button");
  await op.fill("input[name=s4_ist_nm]", "121");
  schritt("Kennzeichnung live (#-Werte aufgelöst)", (await op.textContent("section:has-text('Schrauben – Positionen') tbody")).includes("DS1-8-121 Nm")
    && (await op.textContent("section:has-text('Schrauben – Positionen') tbody")).includes("DS1-4-118 Nm"));
  await op.check("input[name=montage_abgeschlossen][value=ja]");
  await op.check("input[name=lecktest][value=bestanden]");
  await op.click("button:has-text('Jetzt')");
  await op.locator("section:has-text('Skizze / Reihenfolge')").screenshot({ path: `${OUT}/08_skizze_reihenfolge.png` });
  await op.screenshot({ path: `${OUT}/09_protokoll_nachher.png`, fullPage: true });
  await klick(op, "button:has-text('Abschließen')");
  t = await text(op);
  schritt("Abgeschlossen, nur noch Ansicht", t.includes("abgeschlossen") && !(await op.isVisible("button:has-text('Zwischenspeichern')")));
  await op.screenshot({ path: `${OUT}/10_protokoll_ansicht.png`, fullPage: true });
  const pid = op.url().match(/protokolle\/(\d+)/)[1];
  // Druck
  await op.goto(BASE + `/ih/montage/protokolle/${pid}/druck`);
  schritt("Druck: 8 Löcher, 8 Zeilen, Nummern", (await op.locator("svg circle[stroke-width='1']").count()) === 8 && (await op.content()).includes("POSITIONEN 1 BIS 8"));
  await op.emulateMedia({ media: "print" });
  await op.pdf({ path: `${OUT}/Montageprotokoll_Demo.pdf`, preferCSSPageSize: true, printBackground: true });
  await op.emulateMedia({ media: "screen" });
  await op.screenshot({ path: `${OUT}/11_druck.png`, fullPage: true });
  // Excel
  await op.goto(BASE + `/ih/montage/protokolle/${pid}`);
  const [dl] = await Promise.all([op.waitForEvent("download"), op.click("a:has-text('Excel')")]);
  await dl.saveAs(`${OUT}/Montageprotokoll_Demo.xlsx`);
  schritt("Excel heruntergeladen", fs.statSync(`${OUT}/Montageprotokoll_Demo.xlsx`).size > 5000);
  await op.goto(BASE + "/ih/montage/protokolle");
  schritt("Übersicht zeigt Protokoll", (await text(op)).includes("MP-") && (await text(op)).includes("Abgeschlossen"));
  await op.screenshot({ path: `${OUT}/12_protokolle.png`, fullPage: false });
  // Handy: Formular ohne seitliches Scrollen der Seite
  const hm = await (await browser.newContext({ ...devices["Pixel 5"] })).newPage();
  hm.on("pageerror", (e) => fehler.push(e.message));
  await login(hm, "monteur1", "Test-Passwort-1");
  await hm.goto(BASE + "/ih/m");
  schritt("App-Startseite: Kachel Montageprotokoll", (await hm.content()).includes("Montageprotokoll"));
  await hm.goto(BASE + "/ih/montage/protokolle/neu?stutzen=1");
  const breit = await hm.evaluate(() => document.documentElement.scrollWidth);
  schritt("Handy: kein seitliches Scrollen der Seite", breit <= 393 + 2, String(breit));
  await hm.screenshot({ path: `${OUT}/13_handy_protokoll.png`, fullPage: false });
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
