/* Service Worker der Instandhaltungs-App: hält Dateien vor; ohne Verbindung Hinweis aufs Papierformular. */
const CACHE = "ih-{{ version }}";
const DATEIEN = ["/static/app.css?v={{ version }}", "/static/vendor/alpine.min.js", "/static/vendor/htmx.min.js", "/static/icon-ih-192.png",
  "/static/fonts/barlow-latin-400-normal.woff2", "/static/fonts/barlow-latin-500-normal.woff2", "/static/fonts/barlow-latin-600-normal.woff2",
  "/static/fonts/barlow-semi-condensed-latin-600-normal.woff2", "/static/fonts/barlow-semi-condensed-latin-700-normal.woff2"];
const OFFLINE = `<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Keine Verbindung</title>
<body style="font:17px/1.45 Arial,sans-serif;padding:22px;max-width:560px;margin:auto;color:#18222e">
<h1 style="font-size:22px">Keine Verbindung zum Server</h1>
<p>Die Instandhaltung ist gerade nicht erreichbar (WLAN weg oder Lager-PC aus).</p>
<ol><li>Ereignisse auf dem <b>Papierformular Schichtbuch</b> notieren (liegt bei der Schichtleitung; PDF im Programmordner unter <i>docs</i>).</li>
<li>Uhrzeit immer mit aufschreiben.</li>
<li>Sobald die Verbindung wieder da ist: <b>Schichtbuch → Nachtragen</b>.</li></ol>
<p><button onclick="location.reload()" style="font-size:17px;padding:10px 18px">Erneut versuchen</button></p></body>`;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(DATEIEN.map((u) => c.add(new Request(u, { credentials: "same-origin" })).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("ih-") && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.method !== "GET") return;
  const url = new URL(r.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(r).then((hit) => hit || fetch(r)));
    return;
  }
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).catch(() => new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } })));
  }
});
