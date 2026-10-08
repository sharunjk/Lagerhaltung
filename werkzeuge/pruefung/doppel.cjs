const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const BASE = process.argv[2], DB = process.argv[3];
const n = () => +execFileSync("python3", ["-c", "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute(\"select count(*) from bewegungen where typ='ausgang'\").fetchone()[0])", DB]).toString();
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 360, height: 720 }, isMobile: true, hasTouch: true });
  const p = await ctx.newPage();
  await p.goto(BASE + "/login"); await p.fill("input[name=username]", "lager"); await p.fill("input[name=passwort]", "geheim1");
  await Promise.all([p.waitForNavigation(), p.click("form button")]);
  await p.goto(BASE + "/m/buchen?typ=ausgang&artikel=10003", { waitUntil: "networkidle" });
  const vorher = n();
  await p.route("**/m/ping", async (r) => { await new Promise((x) => setTimeout(x, 400)); r.continue(); });  // langsames WLAN
  await p.click("form[data-offline] button.btn-primary");
  await p.click("form[data-offline] button.btn-primary", { force: true }).catch(() => {});
  await p.waitForTimeout(2500);
  console.log(`Doppel-Tipp bei langsamem WLAN: ${n() - vorher} Entnahme(n) gebucht`);
  await b.close();
})();
