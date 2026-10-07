#!/usr/bin/env bash
# Erzeugt docs/pdf/<name>.pdf aus docs/<name>.md (pandoc + Chromium headless).
# Aufruf: tools/docs_to_pdf.sh [docs/datei.md ...]   (ohne Argumente: alle docs/*.md)
set -euo pipefail
cd "$(dirname "$0")/.."
CHROME="${CHROME:-$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}"
CHROME="${CHROME:-chromium}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
files=("$@")
[ ${#files[@]} -eq 0 ] && files=(docs/*.md)
for md in "${files[@]}"; do
  name="$(basename "$md" .md)"
  pandoc "$md" --standalone --from markdown --to html5 --css tools/pdf.css \
    --embed-resources --metadata lang=de -o "$tmp/$name.html"
  "$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="docs/pdf/$name.pdf" "file://$tmp/$name.html" 2>/dev/null
  echo "docs/pdf/$name.pdf"
done
