/* Offline-Warteschlange für die Scanner-Ansicht.
   Buchungen ohne Verbindung werden im Gerät (IndexedDB) gespeichert und automatisch übertragen,
   sobald der Lager-PC wieder erreichbar ist. Jede Buchung hat eine eindeutige ID – doppelte
   Übertragung ist ausgeschlossen. */
(function () {
  const LV = (window.LV = window.LV || {});
  const DB = "lager-offline", STORE = "queue", KAT = "katalog";

  function open() {
    return new Promise((ok, err) => {
      const r = indexedDB.open(DB, 2);
      r.onupgradeneeded = () => {
        const db = r.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "uuid" });
        if (!db.objectStoreNames.contains(KAT)) db.createObjectStore(KAT);
      };
      r.onsuccess = () => ok(r.result);
      r.onerror = () => err(r.error);
    });
  }
  async function tx(store, mode, fn) {
    const db = await open();
    return new Promise((ok, err) => {
      const t = db.transaction(store, mode), s = t.objectStore(store);
      let res;
      Promise.resolve(fn(s)).then((v) => (res = v));
      t.oncomplete = () => ok(res);
      t.onerror = () => err(t.error);
    });
  }
  const req = (r) => new Promise((ok, err) => { r.onsuccess = () => ok(r.result); r.onerror = () => err(r.error); });

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "x" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  LV.queue = {
    async add(item) {
      item.uuid = uuid();
      item.erfasst = new Date().toISOString();
      item.status = "offen";
      await tx(STORE, "readwrite", (s) => s.put(item));
      LV.queue.badge();
      return item;
    },
    async alle() { return (await tx(STORE, "readonly", (s) => req(s.getAll()))) || []; },
    async loeschen(id) { await tx(STORE, "readwrite", (s) => s.delete(id)); LV.queue.badge(); },
    // Kopie speichern: Alpine-Proxys lassen sich nicht in IndexedDB ablegen ("could not be cloned")
    async setzen(item) { await tx(STORE, "readwrite", (s) => s.put(JSON.parse(JSON.stringify(item)))); },
    async badge() {
      const el = document.getElementById("offline-badge");
      if (!el) return;
      const a = await LV.queue.alle();
      const offen = a.filter((x) => x.status === "offen").length, fehler = a.filter((x) => x.status === "fehler").length;
      el.classList.toggle("hidden", !(offen || fehler));
      el.textContent = fehler ? `${fehler} Fehler` : `${offen} wartet`;
      el.className = el.className.replace(/bg-\S+/g, "") + (fehler ? " bg-crit" : " bg-warn");
    },
    laeuft: false,
    async sync() {
      if (LV.queue.laeuft) return;
      const offen = (await LV.queue.alle()).filter((x) => x.status === "offen");
      if (!offen.length) return LV.queue.badge();
      LV.queue.laeuft = true;
      try {
        const r = await fetch("/m/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items: offen }), credentials: "same-origin" });
        if (r.status === 401) { LV.meldung("Zum Übertragen der gespeicherten Buchungen bitte neu anmelden.", false); return; }
        if (r.status === 403) { LV.meldung("Ihre Rolle darf nicht buchen – gespeicherte Buchungen bitte verwerfen oder anders anmelden.", false); return; }
        if (!r.ok) { LV.meldung(`Übertragung fehlgeschlagen (Fehler ${r.status}) – wird später erneut versucht.`, false); return; }
        const erg = await r.json();
        let ok = 0, fehl = 0;
        for (const it of offen) {
          const e = erg[it.uuid];
          if (!e) continue;
          if (e.ok) { await LV.queue.loeschen(it.uuid); ok++; }
          else { it.status = "fehler"; it.fehler = e.meldung; await LV.queue.setzen(it); fehl++; }
        }
        if (ok) LV.meldung(`${ok} offline erfasste Buchung(en) übertragen.`, true);
        if (fehl) LV.meldung(`${fehl} Buchung(en) konnten nicht übertragen werden – unter „Offline“ prüfen.`, false);
        document.dispatchEvent(new CustomEvent("lv-sync"));
      } catch (e) { /* weiterhin offline */ }
      finally { LV.queue.laeuft = false; LV.queue.badge(); }
    },
  };

  LV.katalog = {
    async laden() {
      try {
        const r = await fetch("/m/katalog.json", { credentials: "same-origin" });
        if (!r.ok) return false;
        const d = await r.json();
        await tx(KAT, "readwrite", (s) => s.put(d, "daten"));
        return true;
      } catch (e) { return false; }
    },
    async daten() { return (await tx(KAT, "readonly", (s) => req(s.get("daten")))) || null; },
  };

  LV.meldung = function (text, ok) {
    let box = document.getElementById("lv-toast");
    if (!box) {
      box = document.createElement("div");
      box.id = "lv-toast";
      box.className = "fixed left-3 right-3 bottom-20 z-40 rounded-lg px-4 py-3 text-white font-semibold shadow-lg";
      document.body.appendChild(box);
    }
    box.textContent = text;
    box.style.background = ok ? "rgb(var(--ok))" : "rgb(var(--crit))";
    box.style.display = "block";
    LV.ton && LV.ton(ok);
    clearTimeout(box._t);
    box._t = setTimeout(() => (box.style.display = "none"), 4000);
  };

  LV.status = async function () {
    if (!navigator.onLine) return { ok: false, angemeldet: false };
    try {
      const c = new AbortController();
      const t = setTimeout(() => c.abort(), 2500);
      const r = await fetch("/m/ping", { cache: "no-store", signal: c.signal, credentials: "same-origin" });
      clearTimeout(t);
      if (!r.ok) return { ok: false, angemeldet: false };
      const d = await r.json().catch(() => ({}));
      return { ok: true, angemeldet: !!d.angemeldet };
    } catch (e) { return { ok: false, angemeldet: false }; }
  };
  LV.erreichbar = async function () { return (await LV.status()).ok; };

  // Formulare mit data-offline: ohne Verbindung in die Warteschlange statt absenden
  document.addEventListener("submit", async (e) => {
    const f = e.target;
    if (!f.matches("form[data-offline]") || f.dataset.geprueft) return;
    e.preventDefault();
    const st = await LV.status();
    if (st.ok && st.angemeldet) { f.dataset.geprueft = "1"; f.submit(); return; }
    // Ohne Verbindung oder mit abgelaufener Anmeldung: Buchung im Gerät behalten statt sie zu verlieren
    const d = Object.fromEntries(new FormData(f).entries());
    await LV.queue.add(d);
    if (st.ok) {
      LV.meldung("Anmeldung abgelaufen – Buchung im Gerät gespeichert. Bitte neu anmelden, dann wird sie übertragen.", true);
      setTimeout(() => { location.href = "/login?weiter=" + encodeURIComponent("/m/offline?typ=" + (d.typ || "ausgang")); }, 1800);
      return;
    }
    LV.meldung("Keine Verbindung – Buchung gespeichert, wird automatisch übertragen.", true);
    setTimeout(() => { location.href = "/m/offline?typ=" + encodeURIComponent(d.typ || "ausgang"); }, 1200);
  });

  window.addEventListener("online", () => LV.queue.sync());
  document.addEventListener("DOMContentLoaded", () => {
    LV.queue.badge();
    LV.queue.sync();
    setInterval(() => LV.queue.sync(), 30000);
    // Katalog für den Offline-Modus höchstens alle 10 Minuten auffrischen
    try {
      const t = +localStorage.getItem("lv-katalog-zeit") || 0;
      if (Date.now() - t > 600000) LV.katalog.laden().then((ok) => ok && localStorage.setItem("lv-katalog-zeit", String(Date.now())));
    } catch (e) {}
    if ("serviceWorker" in navigator && window.isSecureContext) {
      navigator.serviceWorker.register("/m/sw.js", { scope: "/m" }).then(() => navigator.serviceWorker.ready)
        .then(() => fetch("/m/offline", { credentials: "same-origin" })).catch(() => {});  // Offline-Seite vorhalten
    }
  });
})();

/* App-Installation anbieten (Chrome: „App installieren“) */
(function () {
  const LV = window.LV;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    LV._installEvent = e;
    const b = document.getElementById("installieren");
    if (b) b.classList.remove("hidden");
  });
  LV.installieren = async function () {
    if (!LV._installEvent) return;
    LV._installEvent.prompt();
    await LV._installEvent.userChoice;
    LV._installEvent = null;
    const b = document.getElementById("installieren");
    if (b) b.classList.add("hidden");
  };
})();
