#!/usr/bin/env bash
# One-command start: creates the venv, installs deps, builds the web app, runs on :8080.
#   ./start.sh            -> http://localhost:8080
#   PORT=9000 ./start.sh  -> another port
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8080}"

command -v ffmpeg >/dev/null || { echo "ffmpeg missing: brew install ffmpeg (mac) / apt install ffmpeg"; exit 1; }
command -v node   >/dev/null || { echo "Node.js 20+ missing: https://nodejs.org"; exit 1; }

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

# Pro processors (pro.py): Airwindows Consolidated VST3 (Linux build, checksum-verified). macOS: install the .dmg from
# github.com/baconpaul/airwin2rack/releases and copy "Airwindows Consolidated.vst3" into plugins/. Optional.
if [ "$(uname)" = Linux ] && [ ! -d "plugins/Airwindows Consolidated.vst3" ]; then
  zip=$(mktemp); tmp=$(mktemp -d)
  if curl -fsSL -o "$zip" https://github.com/baconpaul/airwin2rack/releases/download/DAWPlugin/AirwindowsConsolidated-2026-11-08-316a048-Linux.zip      && echo "39966721d4c5f275d211211fd956c061d282776876788795730e804f78634eac  $zip" | sha256sum -c --quiet      && unzip -q "$zip" -d "$tmp"; then
    mkdir -p plugins && find "$tmp" -maxdepth 2 -name "Airwindows Consolidated.vst3" -exec mv {} plugins/ \;
  else echo "Airwindows not installed: the fix uses its built-in processors"; fi
  rm -rf "$zip" "$tmp"
fi

# AI restoration models (restore.py, ~1.8 GB, first start only). Optional.
[ -f models/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt ] || .venv/bin/python restore.py --download   || echo "Model download failed: takes skip AI restoration"

if [ ! -d web/node_modules ]; then (cd web && npm install --no-audit --no-fund); fi
(cd web && npx vite build)

echo "VocalPreset -> http://localhost:${PORT}"
exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "${PORT}"
