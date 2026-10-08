const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const BASE = process.argv[2], DB = process.argv[3];
const n = () => +execFileSync("python3", ["-c", "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute(\"select count(*) from bewegungen where typ='ausgang'\").fetchone()[0])", DB]).toString();
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext()).newPage();
  await p.goto(BASE + "/login"); await p.fill("input[name=username]", "lager"); await p.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([p.waitForNavigation(), p.click("form button")]);
  await p.goto(BASE + "/buchen?artikel=10003&typ=ausgang", { waitUntil: "networkidle" });
  await p.fill("form[action='/buchen'] input[name=menge]", "1");
  const vorher = n();
  await p.dblclick("form[action='/buchen'] button.btn-primary");
  await p.waitForTimeout(2500);
  console.log(`Doppelklick am PC: ${n() - vorher} Entnahme(n) gebucht`);
  await b.close();
})();
