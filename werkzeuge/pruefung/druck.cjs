const { chromium } = require("playwright");
const BASE = process.argv[2], OUT = process.argv[3];
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext()).newPage();
  await p.goto(BASE + "/login"); await p.fill("input[name=username]", "lesen"); await p.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([p.waitForNavigation(), p.click("form button")]);
  for (const f of ["45x23", "60x20"]) {
    await p.goto(`${BASE}/etiketten/druckansicht?nr=10001&nr=10005&nr=10008&format=${f}`, { waitUntil: "networkidle" });
    await p.emulateMedia({ media: "print" });
    await p.pdf({ path: `${OUT}/druck_${f}.pdf`, preferCSSPageSize: true, printBackground: true });
    await p.emulateMedia({ media: "screen" });
  }
  await b.close();
})();
