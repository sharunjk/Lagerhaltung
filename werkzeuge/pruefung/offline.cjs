// Offline-Szenario der Scanner-App. Aufruf: node offline.cjs <baseUrl> <dbPfad> <ausgabeOrdner>
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const BASE = process.argv[2], DB = process.argv[3], OUT = process.argv[4];
fs.mkdirSync(OUT, { recursive: true });
const sql = (q) => execFileSync("python3", ["-c", `import sqlite3,sys,json;c=sqlite3.connect(sys.argv[1]);print(json.dumps(c.execute(sys.argv[2]).fetchall()))`, DB, q]).toString().trim();
const UA = "Mozilla/5.0 (Linux; Android 11; TC21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";
const log = [];
const schritt = (name, ok, info = "") => { log.push({ name, ok, info }); console.log(`${ok ? "OK  " : "FAIL"} ${name} ${info}`); };

async function login(page, user = "lager") {
  await page.goto(BASE + "/login");
  await page.fill("input[name=username]", user);
  await page.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([page.waitForNavigation(), page.click("form button")]);
}
// wie ein Handscanner: Artikel scannen + Enter, Platz scannen + Enter, Menge eintippen
async function scanne(page, menge) {
  await page.focus("#o_artikel");
  await page.keyboard.type("10003\n", { delay: 5 });
  await page.waitForTimeout(150);
  await page.keyboard.type("C1-R2-1\n", { delay: 5 });
  await page.waitForTimeout(50);
  await page.fill("input[x-ref=menge]", menge);
  await page.click("form button.btn-primary");
}
async function queue(page) {
  return page.evaluate(async () => (await LV.queue.alle()).map((x) => ({ uuid: x.uuid, status: x.status, fehler: x.fehler, artikel: x.artikel, menge: x.menge })));
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 360, height: 720 }, userAgent: UA, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  page.on("dialog", (d) => d.accept());
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  await login(page);
  await page.goto(BASE + "/m/offline", { waitUntil: "networkidle" });
  await page.waitForTimeout(2000); // SW installieren, Katalog laden
  await page.goto(BASE + "/m/offline", { waitUntil: "networkidle" }); // vom SW kontrolliert -> Offline-Seite im Cache
  await page.waitForTimeout(800);
  const vorher = +JSON.parse(sql("select count(*) from bewegungen"))[0][0];
  const b10003 = JSON.parse(sql("select menge from bestand where artikel_id=(select id from artikel where nummer='10003')"))[0][0];

  // 1) Offline erfassen
  await ctx.setOffline(true);
  await scanne(page, "2");
  await page.waitForTimeout(600);
  let q = await queue(page);
  schritt("Offline-Buchung in Warteschlange", q.length === 1 && q[0].status === "offen", JSON.stringify(q));
  // 2) Neu laden ohne Verbindung
  const r = await page.reload({ waitUntil: "domcontentloaded" }).catch((e) => e);
  await page.waitForTimeout(800);
  const titel = await page.textContent("body").catch(() => "");
  schritt("Offline-Seite lädt ohne Verbindung aus dem Cache", titel.includes("Offline erfassen") || titel.includes("Warteschlange"), r && r.status ? `HTTP ${r.status()}` : String(r).slice(0, 80));
  q = await queue(page);
  schritt("Warteschlange nach Neuladen erhalten", q.length === 1, JSON.stringify(q));
  await page.screenshot({ path: `${OUT}/offline_wartet.png`, fullPage: true });
  // 3) Verbindung wieder da
  await ctx.setOffline(false);
  await page.evaluate(() => LV.queue.sync());
  await page.waitForTimeout(800);
  const nachher = +JSON.parse(sql("select count(*) from bewegungen"))[0][0];
  const neu = JSON.parse(sql(`select typ, menge, quelle, text from bewegungen where id > (select max(id) - ${nachher - vorher} from bewegungen)`));
  schritt("Genau eine Buchung auf dem Server", nachher - vorher === 1, JSON.stringify(neu));
  schritt("Kennzeichnung offline", neu.length === 1 && neu[0][2] === "offline" && String(neu[0][3]).includes("offline erfasst"), JSON.stringify(neu[0] || []));
  const b10003n = JSON.parse(sql("select menge from bestand where artikel_id=(select id from artikel where nummer='10003')"))[0][0];
  schritt("Bestand korrekt verringert", Math.abs(b10003 - 2 - b10003n) < 1e-9, `${b10003} -> ${b10003n}`);
  q = await queue(page);
  schritt("Warteschlange leer", q.length === 0, JSON.stringify(q));
  // 4) Doppelte UUID
  const dopp = await page.evaluate(async () => {
    const item = { uuid: "test-uuid-doppelt-1", typ: "eingang", artikel: "10003", lagerort: "C1-R2-1", menge: "1", erfasst: new Date().toISOString() };
    const a = await (await fetch("/m/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: [item] }) })).json();
    const b = await (await fetch("/m/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: [item, item] }) })).json();
    return { a, b };
  });
  const n2 = +JSON.parse(sql("select count(*) from bewegungen"))[0][0];
  schritt("Doppelte UUID ergibt keine Doppelbuchung", n2 === nachher + 1 && dopp.b["test-uuid-doppelt-1"].doppelt === true, JSON.stringify(dopp));
  // 5) Fehlerfall: zu wenig Bestand
  await ctx.setOffline(true);
  await scanne(page, "9999");
  await page.waitForTimeout(500);
  await ctx.setOffline(false);
  await page.evaluate(() => LV.queue.sync());
  await page.waitForTimeout(800);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent("lv-sync")));
  await page.waitForTimeout(300);
  q = await queue(page);
  const rot = await page.locator("li .text-crit").count();
  schritt("Fehlerfall: rot in der Warteschlange", q.length === 1 && q[0].status === "fehler" && rot >= 1, JSON.stringify(q));
  await page.screenshot({ path: `${OUT}/offline_fehler.png`, fullPage: true });
  await page.locator("button:has-text(\"Erneut senden\"):visible").first().click();
  await page.waitForTimeout(800);
  q = await queue(page);
  schritt("Erneut senden: bleibt Fehler, keine Buchung", q.length === 1 && q[0].status === "fehler" && +JSON.parse(sql("select count(*) from bewegungen"))[0][0] === n2, JSON.stringify(q));
  await page.locator("button:has-text(\"Verwerfen\"):visible").first().click();
  await page.waitForTimeout(500);
  q = await queue(page);
  schritt("Verwerfen entfernt die Buchung", q.length === 0, JSON.stringify(q));
  // 6) Sitzung abgelaufen während offline
  await ctx.setOffline(true);
  await scanne(page, "1");
  await page.waitForTimeout(500);
  await ctx.clearCookies();
  await ctx.setOffline(false);
  await page.evaluate(() => LV.queue.sync());
  await page.waitForTimeout(800);
  const toast = await page.textContent("#lv-toast").catch(() => "");
  q = await queue(page);
  schritt("Abgelaufene Sitzung: verständliche Meldung", /anmelden/i.test(toast), toast);
  schritt("Abgelaufene Sitzung: Buchung bleibt erhalten", q.length === 1 && q[0].status === "offen", JSON.stringify(q));
  await login(page);
  await page.goto(BASE + "/m/offline", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  q = await queue(page);
  const n3 = +JSON.parse(sql("select count(*) from bewegungen"))[0][0];
  schritt("Nach neuer Anmeldung übertragen", q.length === 0 && n3 === n2 + 1, `queue=${q.length} bewegungen +${n3 - n2}`);
  // 7) Online, aber Sitzung abgelaufen: normales Buchungsformular (data-offline)
  await page.goto(BASE + "/m/buchen?typ=ausgang&artikel=10003", { waitUntil: "networkidle" });
  await ctx.clearCookies();
  await page.fill("input[name=menge]", "1");
  await Promise.all([page.waitForNavigation({ timeout: 5000 }).catch(() => null), page.click("form[data-offline] button.btn-primary")]);
  await page.waitForTimeout(1500);
  const urlNach = page.url();
  await page.waitForTimeout(1500);
  const umgeleitet = page.url().includes("/login");
  await login(page);  // landet über weiter= auf /m/offline und überträgt
  await page.waitForTimeout(2000);
  const n4 = +JSON.parse(sql("select count(*) from bewegungen"))[0][0];
  q = await queue(page).catch(() => "?");
  schritt("Online + Sitzung abgelaufen: Buchung geht nicht verloren", n4 === n3 + 1, `url=${urlNach} -> Login=${umgeleitet}, danach ${page.url()} queue=${JSON.stringify(q)} bewegungen +${n4 - n3}`);
  schritt("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  fs.writeFileSync(`${OUT}/offline.json`, JSON.stringify(log, null, 1));
  await browser.close();
})();
