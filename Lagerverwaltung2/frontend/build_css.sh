#!/bin/sh
cd "$(dirname "$0")" && npx tailwindcss -i input.css -o ../app/static/app.css --minify
