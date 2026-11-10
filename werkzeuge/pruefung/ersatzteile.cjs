// 2.7.0: Ersatzteil fest einer Tag-Nr. zuordnen (Artikelformular mit Auswahlliste), Anlage zeigt Bestand und Lagerort,
// eigene Kampagne für ein Bauteil anlegen (Tätigkeit, Rhythmus), Bauteil ergänzen, Auftrag anlegen, freigeben,
// Ersatzteil für den Auftrag entnehmen. Läuft mit den erfundenen Demodaten (demo_start.sh).
// Aufruf: node ersatzteile.cjs <baseUrl> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const [BASE, OUT] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };
const klick = (page, sel) => Promise.all([page.waitForNavigation(), page.click(sel)]);
const text = async (page, sel = "main") => (await page.textContent(sel)) || "";
async function anlage(page, code, klasse) {
  await page.goto(BASE + "/ih/anlagen/neu");
  await page.fill("input[name=code]", code);
  await page.selectOption("select[name=art]", "platz");
  await page.fill("input[name=bezeichnung]", `Demo ${code}`);
  if (klasse) await page.fill("input[name=bauteilklasse]", klasse);
  await klick(page, "button:has-text('Anlegen')");
  return page.url().match(/\/ih\/anlagen\/(\d+)/)[1];
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") fehler.push(m.text()); });
  page.on("dialog", (d) => d.accept());
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", "admin");
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await klick(page, "form button");
  await page.goto(BASE + "/einstellungen?tab=allgemein");
  await page.check("input[name=cmms_aktiv]");
  await klick(page, "form[action='/einstellungen/allgemein'] button");
  const a1 = await anlage(page, "VV 1040 80", "Absperrarmatur");
  const a2 = await anlage(page, "VV 1040 81", "Absperrarmatur");
  schritt("Zwei Bauteile von Hand angelegt", !!a1 && !!a2);

  // 1. Artikel 10001 der Tag-Nr. zuordnen – Auswahlliste, Enter übernimmt
  await page.goto(BASE + "/artikel/10001/bearbeiten");
  schritt("Artikelformular: Abschnitt Tag-Nr.", (await text(page)).includes("Ersatzteil für Tag-Nr."));
  const opt = await page.locator("datalist#ih_tags option").count();
  schritt("Auswahlliste enthält die Tag-Nummern", opt === 2, String(opt));
  const feld = page.locator("input[list=ih_tags]");
  await feld.fill("VV 1040 80 – Demo VV 1040 80");
  await feld.press("Enter");
  await feld.fill("VV 1040 81");
  await page.click("button:has-text('Hinzufügen')");
  const chips = await page.locator("input[type=hidden][name=tag]").evaluateAll((e) => e.map((x) => x.value));
  schritt("Zwei Tag-Nr. als Chips", chips.join("|") === "VV 1040 80|VV 1040 81", chips.join("|"));
  await page.locator("input[type=hidden][name=tag]").nth(1).locator("xpath=..").locator("button").click();
  await page.screenshot({ path: `${OUT}/01_artikel_tag_nr.png`, fullPage: false, clip: { x: 0, y: 0, width: 1440, height: 900 } });
  await klick(page, "button:has-text('Änderungen speichern')");
  const det = await text(page);
  schritt("Artikel zeigt die Zuordnung", det.includes("Ersatzteil für Tag-Nr.") && det.includes("VV 1040 80") && !det.includes("VV 1040 81"));

  // 2. Anlage zeigt Ersatzteil mit Bestand und Lagerort
  await page.goto(BASE + `/ih/anlagen/${a1}`);
  const an = await text(page, "#ersatzteile");
  schritt("Anlage: Ersatzteil mit Bestand und Orten", an.includes("10001") && an.includes("C1-R1-1") && an.includes("Bestand 4"), an.replace(/\s+/g, " ").slice(0, 120));
  await page.screenshot({ path: `${OUT}/02_anlage_ersatzteile.png`, fullPage: true });

  // 3. Eigene Kampagne von der Anlage aus
  await klick(page, "a:has-text('Eigene Wartung anlegen')");
  const vor = await page.locator("input[type=hidden][name=tag]").evaluateAll((e) => e.map((x) => x.value));
  schritt("Kampagne neu: Bauteil vorbelegt", vor.join() === "VV 1040 80", vor.join());
  await page.selectOption("select[name=massnahme]", "W");
  await page.fill("textarea[name=taetigkeit]", "Spindel fetten, Stopfbuchse nachziehen, Leichtgängigkeit prüfen");
  await page.fill("input[name=hinweis]", "Nur drucklos arbeiten");
  await page.fill("input[name=intervall_monate]", "6");
  await page.check("input[name=rhythmus][value=ab_erledigung]");
  await page.screenshot({ path: `${OUT}/03_kampagne_neu.png`, fullPage: true });
  await klick(page, "button:has-text('Kampagne anlegen')");
  const kp = await text(page);
  schritt("Kampagne angelegt", kp.includes("eigene Kampagne") && kp.includes("Spindel fetten") && kp.includes("ab der letzten Durchführung"));
  await page.fill("#bauteile input[name=tag]", "VV 1040 81");
  await klick(page, "#bauteile button:has-text('Hinzufügen')");
  schritt("Bauteil ergänzt", (await text(page, "#bauteile")).includes("Bauteile (2)"));
  await page.screenshot({ path: `${OUT}/04_kampagne.png`, fullPage: true });
  // Pflichtfelder: ohne Tätigkeit wird nichts angelegt
  await page.goto(BASE + "/ih/wartung/kampagne/neu");
  await page.locator("input[list=ih_tags]").fill("VV 1040 81");
  await page.locator("input[list=ih_tags]").press("Enter");
  await page.locator("textarea[name=taetigkeit]").evaluate((e) => e.removeAttribute("required"));
  await klick(page, "button:has-text('Kampagne anlegen')");
  schritt("Ohne Tätigkeit: Fehlermeldung, Eingaben bleiben", (await text(page)).includes("was zu tun ist")
    && (await page.locator("input[type=hidden][name=tag]").count()) === 1);
  await page.goto(BASE + "/ih/wartung");
  schritt("Wartungsplan zeigt die eigene Kampagne", (await text(page)).includes("E-W-VV 1040 80"));

  // 4. Auftrag anlegen, freigeben, Ersatzteil entnehmen
  await Promise.all([page.waitForNavigation(), page.locator("tbody tr", { hasText: "E-W-VV 1040 80" }).locator("a.font-semibold").click()]);
  await klick(page, "button:has-text('Auftrag anlegen')");
  schritt("Auftrag angelegt", page.url().includes("/ih/auftraege/"));
  await klick(page, "button:has-text('Freigeben')");
  const auf = await text(page);
  schritt("Auftrag zeigt Tätigkeit und Hinweis", auf.includes("Spindel fetten") && auf.includes("Nur drucklos"));
  await page.locator("#ersatzteile select[name=platz]").first().selectOption("C1-R1-3");
  await klick(page, "#ersatzteile button:has-text('Entnehmen')");
  const m = (await page.locator(".flash-ok").first().textContent().catch(() => "")).trim();
  schritt("Entnahme gebucht", m.includes("Entnommen: 1 × 10001 von C1-R1-3"), m);
  schritt("Materialkosten am Auftrag", (await text(page, "#ersatzteile")).includes("Material bisher 12,50"));
  await page.screenshot({ path: `${OUT}/05_auftrag_entnahme.png`, fullPage: true });
  await page.goto(BASE + "/artikel/10001");
  schritt("Buchung im Lager sichtbar", (await text(page)).includes("Auftrag A-"));

  // 5. Handy-Breite
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [pfad, name] of [["/ih/wartung/kampagne/neu", "06_kampagne_neu_handy"], [`/ih/anlagen/${a1}`, "07_anlage_handy"]]) {
    await page.goto(BASE + pfad);
    const breit = await page.evaluate(() => document.documentElement.scrollWidth);
    schritt(`Handy ohne seitliches Scrollen ${pfad}`, breit <= 400, String(breit));
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  }
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
