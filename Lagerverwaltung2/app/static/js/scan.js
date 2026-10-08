/* Scanner-Ansicht: Kamera-Scan (BarcodeDetector oder ZXing) und Rückmeldung (Ton, Vibration). */
(function () {
  const LV = (window.LV = window.LV || {});

  LV.ton = function (ok) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = ok ? 1320 : 220; g.gain.value = 0.08;
      o.start(); o.stop(ctx.currentTime + (ok ? 0.12 : 0.35));
    } catch (e) {}
    try { navigator.vibrate && navigator.vibrate(ok ? 60 : [120, 60, 120]); } catch (e) {}
  };

  let stream = null, reader = null, laeuft = false;

  function schliessen() {
    laeuft = false;
    const ov = document.getElementById("kamera");
    if (ov) ov.classList.add("hidden");
    if (reader) { try { reader.reset(); } catch (e) {} reader = null; }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  }
  LV.kameraZu = schliessen;

  function treffer(text, ziel) {
    schliessen();
    LV.ton(true);
    const feld = document.getElementById(ziel);
    if (!feld) return;
    feld.value = text.trim();
    feld.dispatchEvent(new Event("input", { bubbles: true }));
    const f = feld.form;
    if (feld.dataset.weiter) { const n = document.getElementById(feld.dataset.weiter); if (n) { n.focus(); n.select && n.select(); return; } }
    if (f) { f.requestSubmit ? f.requestSubmit() : f.submit(); }
  }

  LV.kamera = async function (ziel) {
    const ov = document.getElementById("kamera"), video = document.getElementById("kamera-video"), info = document.getElementById("kamera-info");
    ov.classList.remove("hidden");
    if (!window.isSecureContext) {
      const port = document.body.dataset.httpsPort;
      const url = port ? `https://${location.hostname}:${port}${location.pathname}${location.search}` : "";
      info.textContent = "Die Kamera funktioniert im Browser nur über eine sichere Verbindung.";
      if (url) {
        const a = document.createElement("a");
        a.className = "underline font-semibold"; a.href = url; a.textContent = "Sichere Adresse öffnen";
        info.append(document.createElement("br"), a, " (Zertifikatswarnung einmal bestätigen)");
      }
      return;
    }
    info.textContent = "Barcode ins Bild halten …";
    laeuft = true;
    try {
      if ("BarcodeDetector" in window) {
        const det = new BarcodeDetector({ formats: ["code_128", "qr_code", "ean_13", "ean_8", "code_39", "data_matrix"] });
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.srcObject = stream; await video.play();
        const schleife = async () => {
          if (!laeuft) return;
          try { const c = await det.detect(video); if (c.length) return treffer(c[0].rawValue, ziel); } catch (e) {}
          requestAnimationFrame(schleife);
        };
        schleife();
      } else if (window.ZXing) {
        reader = new ZXing.BrowserMultiFormatReader();
        await reader.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (res) => { if (res && laeuft) treffer(res.getText(), ziel); });
      } else {
        info.textContent = "Dieser Browser unterstützt keinen Kamera-Scan. Bitte Chrome verwenden.";
      }
    } catch (e) {
      info.textContent = "Kamera nicht verfügbar: " + (e && e.message ? e.message : e);
    }
  };

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") schliessen(); });
  document.addEventListener("DOMContentLoaded", () => {
    const f = document.querySelector("[data-flash]");
    if (f) LV.ton(f.dataset.flash === "ok");
  });
})();

/* Scan ohne aktives Eingabefeld (z. B. Zebra-Scantaste auf einer Infoseite): direkt zum Artikel bzw. Platz. */
(function () {
  let buf = "", last = 0;
  document.addEventListener("keydown", function (e) {
    const t = e.target, inFeld = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
    if (inFeld || e.ctrlKey || e.altKey || e.metaKey) return;
    const jetzt = Date.now();
    if (jetzt - last > 80) buf = "";
    last = jetzt;
    if (e.key === "Enter" && buf.length >= 2) { e.preventDefault(); location.href = "/scan?m=1&code=" + encodeURIComponent(buf); buf = ""; return; }
    if (e.key && e.key.length === 1) buf += e.key;
  });
})();
