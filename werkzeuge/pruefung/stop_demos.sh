#!/usr/bin/env bash
# beendet alle Demo-Server (erkennbar an "-W ignore -m app.main")
for p in $(pgrep -f -- "-W ignore -m app[.]main"); do kill "$p"; done
