const { chromium } = require("playwright");
const BASE = process.argv[2];
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 360, height: 720 }, isMobile: true });
  const p = await ctx.newPage();
  await p.goto(BASE + "/login"); await p.fill("input[name=username]", "lager"); await p.fill("input[name=passwort]", "Demo-Passwort-1");
  await Promise.all([p.waitForNavigation(), p.click("form button")]);
  const arts = []; for (let i = 9; i < 40; i++) arts.push([String(10000 + i), `C2-R${i % 9 + 1}-${i % 5}`]);
  let letzte = 0;
  for (let n = 0; n < arts.length; n++) {
    const [nr, platz] = arts[n];
    const r = await p.request.post(BASE + "/m/korb/neu", { form: { artikel: nr, lagerort: platz, menge: "1" }, headers: { origin: BASE }, maxRedirects: 0 });
    const ck = (await ctx.cookies()).find((c) => c.name === "lager_session");
    await p.goto(BASE + "/m/korb");
    const pos = await p.locator("form[action^='/m/korb/entfernen']").count();
    const angemeldet = !p.url().includes("/login");
    console.log(`nach ${n + 1} Positionen: Liste zeigt ${pos}, Cookie im Browser ${ck ? ck.value.length : "FEHLT"} Zeichen, angemeldet=${angemeldet}, Set-Cookie-Länge=${(r.headers()["set-cookie"] || "").length}`);
    if (pos === letzte && n > 0) { console.log("-> Position ging verloren (Browser hat zu großes Cookie verworfen)"); break; }
    letzte = pos;
  }
  await b.close();
})();
