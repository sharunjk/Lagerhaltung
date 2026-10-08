#!/usr/bin/env bash
# Erzeugt docs/<name>.pdf aus docs/<name>.md (pandoc + Chromium headless, A4).
# Aufruf aus dem Repository-Wurzelordner:  werkzeuge/docs_pdf.sh [Lagerverwaltung2/docs/Datei.md ...]
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}"
CHROME="${CHROME:-chromium}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
files=("$@"); [ ${#files[@]} -eq 0 ] && files=(Lagerverwaltung2/docs/*.md)
for md in "${files[@]}"; do
  name="$(basename "$md" .md)"; titel="$(head -1 "$md" | sed 's/^# //')"
  pandoc "$md" --standalone --from gfm --to html5 --css werkzeuge/pdf.css --embed-resources \
    --metadata title="$titel" --metadata lang=de -o "$tmp/$name.html"
  "$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer --print-to-pdf="$(dirname "$md")/$name.pdf" "file://$tmp/$name.html" 2>/dev/null
  echo "$(dirname "$md")/$name.pdf"
done
