// 2.13.0 im Browser mit Demodaten: EX-Handys (PIN verdeckt, Augensymbol + eigenes Passwort), Schicht beginnen mit Vertretung,
// Schicht übernehmen, Aufgaben (anlegen, Team-Dashboard, erledigen), Schicht beenden mit EX-Handy-Übergabe, Meine Einstellungen
// (Startseite), Montageprotokoll mit Lage der Dichtung (i/m/ä). Aufruf: node schichtbuch_2130.cjs <baseUrl> <ausgabe>
const { chromium, devices } = require("playwright");
const fs = require("fs");
const [BASE, OUT] = process.argv.slice(2);
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
async function benutzer(page, name, rolle) {
  await page.goto(BASE + "/einstellungen?tab=benutzer");
  await page.fill("form[action='/benutzer/speichern'] input[name=username]", name);
  await page.fill("form[action='/benutzer/speichern'] input[name=passwort]", "Test-Passwort-1");
  await page.selectOption("select[name=rolle]", "keine");
  await page.selectOption("select[name=rolle_ih]", rolle);
  await klick(page, "form[action='/benutzer/speichern'] button:has-text('Speichern')");
}
(async () => {
  const browser = await chromium.launch();
  const fehler = [];
  const neu = async (opt = { viewport: { width: 1440, height: 900 } }) => {
    const p = await (await browser.newContext(opt)).newPage();
    p.on("pageerror", (e) => fehler.push(e.message));
    p.on("console", (m) => { if (m.type() === "error" && !m.text().includes("403")) fehler.push(m.text()); });
    p.on("dialog", (d) => d.accept());
    return p;
  };
  const admin = await neu();
  await login(admin, "admin", "Demo-Passwort-1");
  await admin.goto(BASE + "/einstellungen?tab=allgemein");
  await admin.check("input[name=cmms_aktiv]");
  await klick(admin, "form[action='/einstellungen/allgemein'] button");
  await benutzer(admin, "schichtf1", "schichtfuehrer");
  await benutzer(admin, "operator1", "operator");

  // ---------------- EX-Handys einrichten (Schichtführer)
  const sf = await neu();
  await login(sf, "schichtf1", "Test-Passwort-1");
  await sf.goto(BASE + "/ih/schichtbuch");
  await sf.goto(BASE + "/ih/schichtbuch/handys");
  for (const [n, nr, pin] of [["EX-Handy 1", "+49 151 000001", "1234"], ["EX-Handy 2", "+49 151 000002", "5678"]]) {
    await sf.fill("form:has(button:has-text('Hinzufügen')) input[name=name]", n);
    await sf.fill("form:has(button:has-text('Hinzufügen')) input[name=nummer]", nr);
    await sf.fill("form:has(button:has-text('Hinzufügen')) input[name=pin]", pin);
    await klick(sf, "button:has-text('Hinzufügen')");
    await sf.goto(BASE + "/ih/schichtbuch/handys?bearbeiten=1");
  }
  await sf.goto(BASE + "/ih/schichtbuch/handys");
  let t = await text(sf);
  schritt("Zwei EX-Handys, Nummern sichtbar, PIN verdeckt", t.includes("+49 151 000001") && t.includes("+49 151 000002") && !t.includes("1234") && t.includes("••••"));
  await sf.screenshot({ path: `${OUT}/01_handys_verdeckt.png`, fullPage: false });

  // ---------------- PIN anzeigen als Operator: Auge -> Passwort
  const op = await neu();
  await login(op, "operator1", "Test-Passwort-1");
  await op.goto(BASE + "/ih/schichtbuch/handys");
  const dd = op.locator("section:has-text('EX-Handy 1') dd").first();
  await dd.locator("button[aria-label='PIN anzeigen']").click();
  await dd.locator("input[type=password]").fill("falsch");
  await dd.locator("button:has-text('Anzeigen')").click();
  await op.waitForTimeout(400);
  schritt("Falsches Passwort: PIN bleibt verdeckt", (await dd.textContent()).includes("Passwort ist falsch") && !(await dd.textContent()).includes("1234"));
  await dd.locator("input[type=password]").fill("Test-Passwort-1");
  await dd.locator("button:has-text('Anzeigen')").click();
  await op.waitForTimeout(400);
  schritt("Richtiges Passwort: PIN 1234 sichtbar", (await dd.textContent()).includes("1234"));
  await op.screenshot({ path: `${OUT}/02_pin_angezeigt.png`, fullPage: false });
  await dd.locator("button[aria-label='PIN verbergen']").click();
  schritt("PIN wieder verborgen", !(await dd.textContent()).includes("1234"));

  // ---------------- Schicht beginnen mit Vertretung
  await sf.goto(BASE + "/ih/schichtbuch");
  if (await sf.isVisible("form[action='/ih/schichtbuch/beginnen'] >> nth=0")) {
    const f = sf.locator("form[action='/ih/schichtbuch/beginnen']").first();
    await f.locator("input[name=schichtfuehrer]").fill("Sven Schicht");
    await f.locator("input[name=vertretung]").check();
    await f.locator("input[name=vertretung_fuer]").fill("Max Muster");
    await Promise.all([sf.waitForNavigation(), f.locator("button").last().click()]);
  }
  t = await text(sf);
  schritt("Schicht läuft, Vertretung angezeigt", t.includes("Schicht läuft") && t.includes("Vertretung für Max Muster"));
  // Schicht übernehmen (anderer Schichtführer)
  await sf.click("summary:has-text('Schicht übernehmen')");
  const u = sf.locator("form[action='/ih/schichtbuch/schicht-uebernehmen']");
  await u.locator("input[name=schichtfuehrer]").fill("Roberto Demo");
  await u.locator("input[name=grund]").fill("Übernahme Demo");
  await Promise.all([sf.waitForNavigation(), u.locator("button:has-text('Übernehmen')").click()]);
  t = await text(sf);
  schritt("Schicht übernommen und protokolliert", t.includes("Roberto Demo") && t.includes("Übernommen") && t.includes("Übernahme Demo"));

  // ---------------- Aufgaben
  await sf.goto(BASE + "/ih/schichtbuch/aufgaben/neu");
  await sf.fill("input[name=titel]", "Filter am Kompressor bestellen");
  await sf.selectOption("select[name=team_id]", { label: "Team Grün" });
  await sf.selectOption("select[name=prioritaet]", "hoch");
  await klick(sf, "button:has-text('Aufgabe anlegen')");
  await sf.goto(BASE + "/ih/schichtbuch/aufgaben/neu");
  await sf.fill("input[name=titel]", "Werkstatt aufräumen");
  await sf.fill("input[name=wiederholen_tage]", "7");
  await sf.fill("input[name=faellig]", new Date().toISOString().slice(0, 10));
  await klick(sf, "button:has-text('Aufgabe anlegen')");
  schritt("Aufgabenliste mit 2 Aufgaben", (await sf.locator("tbody tr").count()) === 2);
  await sf.screenshot({ path: `${OUT}/03_aufgaben.png`, fullPage: false });
  await sf.goto(BASE + "/ih/schichtbuch?team=1");
  const auf = await sf.textContent("#aufgaben");
  schritt("Dashboard Team Grün zeigt beide Aufgaben", auf.includes("Filter am Kompressor bestellen") && auf.includes("Werkstatt aufräumen"));
  await sf.goto(BASE + "/ih/schichtbuch?team=2");
  schritt("Dashboard Team Blau nur die Aufgabe für alle", !(await sf.textContent("#aufgaben")).includes("Filter am Kompressor") && (await sf.textContent("#aufgaben")).includes("Werkstatt"));
  await klick(sf, "#aufgaben li:has-text('Werkstatt') button:has-text('Erledigt')");
  schritt("Wiederkehrende Aufgabe erledigt, neu angelegt", (await text(sf)).includes("Nächste Wiederholung"));
  await sf.screenshot({ path: `${OUT}/04_dashboard.png`, fullPage: true });

  // ---------------- Schicht beenden mit EX-Handy
  await sf.goto(BASE + "/ih/schichtbuch/beenden");
  await sf.check("#ex-handy input[name=handy] >> nth=0");
  await sf.fill("#ex-handy input[name^=handy_an_] >> nth=0", "Nachtschicht Demo");
  await sf.locator("#ex-handy").screenshot({ path: `${OUT}/05_beenden_handy.png` });
  await klick(sf, "button:has-text('Schicht beenden und übergeben')");
  await sf.goto(BASE + "/ih/schichtbuch/handys");
  schritt("Handy bei der Übergabe weitergegeben", (await text(sf)).includes("zurzeit bei Nachtschicht Demo"));

  // ---------------- Meine Einstellungen: Operator -> Schichtbuch als Startseite
  await op.goto(BASE + "/mein");
  schritt("Abgespeckte Einstellungen (keine Rollenvorgaben)", !(await text(op)).includes("Startseite je Rolle") && (await text(op)).includes("Startseite nach dem Anmelden"));
  await op.selectOption("select[name=startseite]", "schichtbuch");
  await op.check("input[name=monteur_vorbelegen]");
  await op.screenshot({ path: `${OUT}/06_mein.png`, fullPage: true });
  await klick(op, "button:has-text('Speichern')");
  const op2 = await neu();
  await login(op2, "operator1", "Test-Passwort-1");
  schritt("Nach dem Anmelden direkt im Schichtbuch", op2.url().endsWith("/ih/schichtbuch"), op2.url());
  await admin.goto(BASE + "/mein");
  schritt("Admin: Startseite je Rolle sichtbar", (await text(admin)).includes("Startseite je Rolle"));

  // ---------------- Montageprotokoll: Lage i/m/ä
  await op2.goto(BASE + "/ih/montage/protokolle/neu");
  await op2.fill("#stz", "Demo-Stutzen frei");
  await op2.dispatchEvent("#stz", "change");
  await op2.fill("#n", "4");
  await op2.dispatchEvent("#n", "change");
  await op2.fill("input[name=d0_dichtungsart]", "MCR Ø100");
  await op2.check("input[aria-label='Dichtung 1 innerste']");
  await op2.fill("input[name=d1_dichtungsart]", "MCR Ø80");
  await op2.check("input[aria-label='Dichtung 2 äußerste']");
  await op2.check("input[aria-label='Dichtung 1 mittlere']");  // wechselt: nur eine Lage je Dichtung
  schritt("Monteur vorbelegt", (await op2.inputValue("input[name=monteur]")).length > 0);
  schritt("Lage: nur ein Haken je Dichtung", !(await op2.isChecked("input[aria-label='Dichtung 1 innerste']")) && await op2.isChecked("input[aria-label='Dichtung 1 mittlere']"));
  await op2.locator("section:has-text('Dichtungen') table").first().screenshot({ path: `${OUT}/07_lage.png` });
  await klick(op2, "button:has-text('Zwischenspeichern')");
  const pid = op2.url().match(/protokolle\/(\d+)/)[1];
  await op2.goto(BASE + `/ih/montage/protokolle/${pid}/druck`);
  const dr = await op2.content();
  schritt("Druck: Dichtung 1 · m, Dichtung 2 · ä", dr.includes("Dichtung 1 · m") && dr.includes("Dichtung 2 · ä"));
  await op2.screenshot({ path: `${OUT}/08_druck_lage.png`, fullPage: false });
  // Handy: Handyseite ohne seitliches Scrollen
  const h = await neu({ ...devices["Pixel 5"] });
  await login(h, "operator1", "Test-Passwort-1");
  for (const pfad of ["/ih/schichtbuch/handys", "/ih/schichtbuch/aufgaben", "/mein", "/ih/schichtbuch"]) {
    await h.goto(BASE + pfad);
    const breit = await h.evaluate(() => document.documentElement.scrollWidth);
    schritt(`Handy ohne seitliches Scrollen ${pfad}`, breit <= 393 + 2, String(breit));
  }
  await h.goto(BASE + "/ih/schichtbuch/handys");
  await h.screenshot({ path: `${OUT}/09_handy_handys.png`, fullPage: false });
  await browser.close();
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/ergebnis.json`, JSON.stringify(log, null, 1));
  process.exit(log.every((s) => s.ok) ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
