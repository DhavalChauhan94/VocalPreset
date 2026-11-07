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

if [ ! -d web/node_modules ]; then (cd web && npm install --no-audit --no-fund); fi
(cd web && npx vite build)

echo "VocalPreset -> http://localhost:${PORT}"
exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "${PORT}"
