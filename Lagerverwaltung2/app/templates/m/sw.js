/* Service Worker der Scanner-App: hält die Offline-Erfassung und alle Dateien auf dem Gerät vor. */
const CACHE = "lager-{{ version }}";
const DATEIEN = ["/static/app.css?v={{ version }}", "/static/js/scan.js?v={{ version }}", "/static/js/offline.js?v={{ version }}",
  "/static/vendor/alpine.min.js", "/static/vendor/zxing.min.js", "/static/icon-192.png", "/static/icon-512.png",
  "/static/fonts/barlow-latin-400-normal.woff2", "/static/fonts/barlow-latin-500-normal.woff2", "/static/fonts/barlow-latin-600-normal.woff2",
  "/static/fonts/barlow-semi-condensed-latin-600-normal.woff2", "/static/fonts/barlow-semi-condensed-latin-700-normal.woff2"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(DATEIEN.map((u) => c.add(new Request(u, { credentials: "same-origin" })).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.method !== "GET") return;
  const url = new URL(r.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(r).then((hit) => hit || fetch(r).then((res) => { const k = res.clone(); caches.open(CACHE).then((c) => c.put(r, k)); return res; })));
    return;
  }
  if (url.pathname === "/m/offline") {
    // immer frisch holen, aber eine angemeldete Fassung für den Offline-Fall aufheben
    e.respondWith(fetch(r).then((res) => {
      if (res.ok && !res.redirected) { const k = res.clone(); caches.open(CACHE).then((c) => c.put("/m/offline", k)); }
      return res;
    }).catch(() => caches.match("/m/offline")));
    return;
  }
  if (r.mode === "navigate" && url.pathname.startsWith("/m")) {
    e.respondWith(fetch(r).catch(() => caches.match("/m/offline").then((hit) => hit || new Response(
      "<meta name=viewport content='width=device-width'><p style='font:18px sans-serif;padding:20px'>Keine Verbindung zum Lager-PC. Die Offline-Erfassung ist auf diesem Gerät noch nicht eingerichtet – einmal mit Verbindung die Scanner-Ansicht öffnen.</p>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } }))));
  }
});
