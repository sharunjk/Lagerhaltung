// Newsletter-Grafiken aus den Rohbildern. Aufruf: node grafiken.cjs <rohOrdner> <fontOrdner> <ausgabe>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const [ROH, FONTS, OUT] = process.argv.slice(2);
fs.mkdirSync(OUT, { recursive: true });
const bild = (n) => "data:image/png;base64," + fs.readFileSync(path.join(ROH, n)).toString("base64");
const font = (n) => "data:font/woff2;base64," + fs.readFileSync(path.join(FONTS, n)).toString("base64");

const css = `
@font-face{font-family:Barlow;font-weight:400;src:url(${font("barlow-latin-400-normal.woff2")})}
@font-face{font-family:Barlow;font-weight:500;src:url(${font("barlow-latin-500-normal.woff2")})}
@font-face{font-family:Barlow;font-weight:600;src:url(${font("barlow-latin-600-normal.woff2")})}
@font-face{font-family:Cond;font-weight:600;src:url(${font("barlow-semi-condensed-latin-600-normal.woff2")})}
@font-face{font-family:Cond;font-weight:700;src:url(${font("barlow-semi-condensed-latin-700-normal.woff2")})}
*{box-sizing:border-box;margin:0}
body{width:1600px;height:900px;overflow:hidden;font-family:Barlow,sans-serif;color:#18222e;
  background:radial-gradient(1200px 700px at 85% 10%,#ffffff 0%,#eef1f3 55%,#e3e8ec 100%)}
body.dunkel{color:#fff;background:radial-gradient(1100px 700px at 80% 0%,#2a3d50 0%,#1c2a38 55%,#131d27 100%)}
.tag{display:inline-block;background:#ffc72c;color:#18180f;font-family:Cond;font-weight:700;font-size:22px;letter-spacing:.04em;
  padding:4px 12px;border-radius:4px;box-shadow:inset 0 -3px 0 rgba(0,0,0,.14);text-transform:uppercase}
.tag.wein{background:#801632;color:#fff}
h1{font-family:Cond;font-weight:700;font-size:64px;line-height:1.02;letter-spacing:-.005em;margin-top:22px}
p.unter{font-size:26px;line-height:1.38;color:#4b5866;margin-top:18px;max-width:520px}
body.dunkel p.unter{color:#c7d2dc}
.fenster{position:absolute;border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 40px 80px -20px rgba(16,28,40,.45),0 0 0 1px rgba(16,28,40,.08)}
.fenster .leiste{height:34px;background:#1c2a38;display:flex;align-items:center;gap:8px;padding:0 14px}
.fenster .leiste i{width:12px;height:12px;border-radius:50%;background:#3d5164;display:block}
.fenster .leiste span{margin-left:12px;color:#9fb0c0;font-size:14px}
.fenster img{display:block;width:100%}
.handy{position:absolute;width:300px;border-radius:38px;background:#11161c;padding:14px 12px 18px;box-shadow:0 40px 70px -18px rgba(10,16,24,.55),inset 0 0 0 2px #2b333c}
.handy:before{content:"";display:block;width:70px;height:6px;border-radius:3px;background:#2b333c;margin:0 auto 10px}
.handy img{display:block;width:100%;border-radius:18px}
.handy .marke{color:#8fa0b0;font-family:Cond;font-weight:700;font-size:13px;letter-spacing:.2em;text-align:center;margin-top:10px}
.etikett{position:absolute;background:#fff;border-radius:6px;padding:10px;box-shadow:0 18px 40px -12px rgba(16,28,40,.45)}
.etikett img{display:block}
.fuss{position:absolute;left:80px;bottom:46px;font-size:18px;color:#7a8794;display:flex;align-items:center;gap:10px}
body.dunkel .fuss{color:#8fa0b0}
.fuss b{font-family:Cond;font-weight:700;color:inherit;letter-spacing:.04em}
.punkte{margin-top:28px;display:grid;gap:14px;font-size:24px;max-width:520px}
.punkte div{display:flex;gap:12px;align-items:flex-start}
.punkte div:before{content:"";flex:none;width:10px;height:10px;border-radius:2px;background:#ffc72c;margin-top:12px}
`;
const fuss = `<div class="fuss"><b>LAGERVERWALTUNG</b> · CAPHENIA</div>`;
const seiten = {
  "00_titelbild": `<body class="dunkel">
    <div style="position:absolute;left:80px;top:150px;width:620px">
      <span class="tag">Neu im Lager</span>
      <h1 style="font-size:84px">Unser Lager<br>wird digital.</h1>
      <p class="unter" style="font-size:28px;max-width:560px">Ersatzteile finden, scannen, buchen und rechtzeitig nachbestellen – am PC und direkt am Regal mit dem Handscanner.</p>
    </div>
    <div class="fenster" style="left:640px;top:120px;width:900px;transform:rotate(-1.5deg)"><div class="leiste"><i></i><i></i><i></i><span>Lagerverwaltung</span></div><img src="${bild("pc_uebersicht.png")}"></div>
    <div class="handy" style="left:1290px;top:300px;width:250px;transform:rotate(3deg)"><img src="${bild("m_entnahme.png")}"><div class="marke">HANDSCANNER</div></div>
    ${fuss}</body>`,
  "01_uebersicht": `<body>
    <div style="position:absolute;left:80px;top:110px;width:500px">
      <span class="tag">Übersicht</span>
      <h1>Alles auf<br>einen Blick</h1>
      <p class="unter">Was fehlt, was kommt, was gerade gebucht wurde – live, für alle mit Zugang.</p>
      <div class="punkte"><div>Artikel unter Mindestbestand sofort sichtbar</div><div>Letzte Buchungen aktualisieren sich selbst</div><div>Bestellvorschlag mit einem Klick</div></div>
    </div>
    <div class="fenster" style="left:620px;top:90px;width:920px"><div class="leiste"><i></i><i></i><i></i><span>Lagerverwaltung – Übersicht</span></div><img src="${bild("pc_uebersicht.png")}"></div>
    ${fuss}</body>`,
  "02_scanner_app": `<body class="dunkel">
    <div style="position:absolute;left:80px;top:120px;width:470px">
      <span class="tag">Handscanner</span>
      <h1>Scannen<br>statt suchen</h1>
      <p class="unter">Teil scannen, Platz scannen, Menge eingeben – fertig. Jede Buchung trägt den Namen dessen, der sie gemacht hat.</p>
      <div class="punkte" style="color:#e4ebf1"><div>Läuft auf dem Zebra-Handscanner und jedem Smartphone</div><div>Funktioniert auch ohne WLAN – wird später übertragen</div></div>
    </div>
    <div class="handy" style="left:600px;top:110px"><img src="${bild("m_start.png")}"><div class="marke">START</div></div>
    <div class="handy" style="left:930px;top:70px"><img src="${bild("m_entnahme.png")}"><div class="marke">ENTNAHME</div></div>
    <div class="handy" style="left:1260px;top:110px"><img src="${bild("m_platz.png")}"><div class="marke">LAGERPLATZ</div></div>
    ${fuss}</body>`,
  "03_lagerplaetze": `<body>
    <div style="position:absolute;left:80px;top:110px;width:500px">
      <span class="tag">Lagerplätze</span>
      <h1>Jedes Fach<br>hat seinen Platz</h1>
      <p class="unter">Container, Regal, Ebene – übersichtlich sortiert. Ein Klick zeigt, was dort liegt.</p>
      <div class="punkte"><div><span><b style="background:#ffc72c;padding:1px 8px;border-radius:3px;font-family:Cond">Gelb</b> – hier liegt etwas</span></div>
        <div><span><b style="background:#801632;color:#fff;padding:1px 8px;border-radius:3px;font-family:Cond">Weinrot</b> – hier muss nachbestellt werden</span></div></div>
    </div>
    <div class="fenster" style="left:620px;top:90px;width:920px"><div class="leiste"><i></i><i></i><i></i><span>Lagerverwaltung – Lagerplätze</span></div><img src="${bild("pc_lagerplaetze.png")}"></div>
    ${fuss}</body>`,
  "04_sichtlagerboxen": `<body>
    <div style="position:absolute;left:80px;top:110px;width:500px">
      <span class="tag">Neu</span>
      <h1>Sichtlager&shy;boxen mit eigenem Etikett</h1>
      <p class="unter">Kleinteile wie Schrauben, Muttern und <span style="white-space:nowrap">O-Ringe</span> bekommen eigene Boxen im Regalfach – jede mit Barcode und Inhalt.</p>
    </div>
    <div class="fenster" style="left:620px;top:90px;width:920px"><div class="leiste"><i></i><i></i><i></i><span>Lagerplatz C1-R2-3 – Sichtlagerboxen</span></div><img src="${bild("pc_boxen.png")}"></div>
    <div class="etikett" style="left:150px;top:560px;transform:rotate(-4deg)"><img src="${bild("etikett_3.png")}" style="width:250px"></div>
    <div class="etikett" style="left:330px;top:640px;transform:rotate(3deg)"><img src="${bild("etikett_4.png")}" style="width:250px"></div>
    ${fuss}</body>`,
  "05_etiketten": `<body class="dunkel">
    <div style="position:absolute;left:80px;top:130px;width:520px">
      <span class="tag">Etiketten</span>
      <h1>Etikett drucken,<br>aufkleben, scannen</h1>
      <p class="unter">Artikel- und Platz-Etiketten kommen direkt aus dem Etikettendrucker im Lager – mit Barcode, den jeder Scanner lesen kann.</p>
    </div>
    ${[["etikett_1.png", 690, 80, -4], ["etikett_2.png", 1150, 110, 3], ["etikett_5.png", 720, 360, 2], ["etikett_6.png", 1170, 380, -3], ["etikett_3.png", 930, 630, -1]]
      .map(([n, x, y, r]) => `<div class="etikett" style="left:${x}px;top:${y}px;transform:rotate(${r}deg)"><img src="${bild(n)}" style="width:340px"></div>`).join("")}
    ${fuss}</body>`,
};
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2 });
  for (const [name, body] of Object.entries(seiten)) {
    await page.setContent(`<!doctype html><html lang="de"><head><meta charset="utf-8"><style>${css}</style></head>${body}</html>`, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    // kleinere Fassung für E-Mail-Newsletter (geringere Dateigröße)
    await page.screenshot({ path: path.join(OUT, `${name}.jpg`), type: "jpeg", quality: 86 });
  }
  await browser.close();
})();
