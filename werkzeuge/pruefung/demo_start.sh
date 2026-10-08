#!/usr/bin/env bash
# Aufruf: demo_start.sh <name> <http-port> <https-port>  – startet die App mit Demo-Daten im Hintergrund
set -e
S=${PRUEF_TMP:-/tmp/lv_pruefung}; mkdir -p "$S"
APP=${APP:-$(cd "$(dirname "$0")/../../Lagerverwaltung2" && pwd)}
H=$S/demo_$1; rm -rf "$H"; mkdir -p "$H/daten"
cat > "$H/config.toml" <<CFG
[server]
host = "127.0.0.1"
port = $2
https_port = $3
[drucker]
modus = "datei"
[backup]
aktiv = false
CFG
LV_HOME="$H" ${PYTHON:-python3} -W ignore "$(dirname "$0")/demo_seed.py" $APP >/dev/null
cd $APP && LV_HOME="$H" nohup ${PYTHON:-python3} -W ignore -m app.main > "$H/server.out" 2>&1 &
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:$2/m/ping && break; sleep 0.25; done
echo "läuft: http://127.0.0.1:$2  (LV_HOME=$H)"
