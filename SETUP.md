# Setup

## Requirements
| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ (developed on 3.14) | python.org or `brew install python` |
| Node.js | 20+ (developed on 24) | nodejs.org or `brew install node` |
| ffmpeg | any recent version | `brew install ffmpeg` · `sudo apt install ffmpeg` · `winget install ffmpeg` |

ffmpeg reads every input format (mp3, wav, m4a, WhatsApp `.mpeg`/`.opus`, and the audio track of a video) and writes the MP3 downloads.

## Run it (one command)
```bash
./start.sh                 # http://localhost:8080
PORT=9000 ./start.sh       # pick another port if 8080 is taken
```
`start.sh` does four things:
1. creates `.venv` and runs `pip install -r requirements.txt`
2. runs `npm install` in `web/` (first time only)
3. builds the React app into `web/dist`
4. starts the FastAPI server, which serves both the API and the built page

To open it **on your phone**: put the phone on the same Wi-Fi and open `http://<your-computer-ip>:8080`. On a Mac, `ipconfig getifaddr en0` prints the IP.

## Manual steps (what start.sh does)
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd web && npm install && npx vite build && cd ..
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
```

## Dev mode (hot reload for the UI)
Run two terminals:
```bash
.venv/bin/uvicorn app:app --port 8080 --reload     # API
cd web && npx vite                                 # UI on http://localhost:5173
```
Vite forwards `/api/*` to `:8080` (see `web/vite.config.js`). After UI changes, run `npx vite build` again so `:8080` serves the new version.

## Test without the UI
```bash
.venv/bin/python fst_reader.py samples/nofalltypeshi.fst      # prints every decoded plugin
.venv/bin/python engine.py my_vocal.wav lead out.wav --sound studio_air
.venv/bin/python engine.py my_vocal.wav adlib out.wav --sound no_fall --beat beat.mp3
```
The repo ships **no vocal audio**, since the test vocal belongs to an artist. Use any dry vocal of your own.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `ffmpeg: command not found` / "Could not process audio" | Install ffmpeg and make sure it's on PATH |
| Page shows `{"detail":"Not Found"}` | `web/dist` wasn't built: run `cd web && npx vite build`, then restart the server |
| `Address already in use` | Something else uses 8080: `PORT=9000 ./start.sh`, or `lsof -i :8080` to find it |
| pip fails building `pedalboard`/`librosa` | Use Python 3.11–3.14 with wheels; upgrade pip: `.venv/bin/pip install -U pip` |
| npm warns `install-scripts … esbuild` | Harmless on npm 11; the build still works |
| No Fall takes ~15 s | Expected: pitch tracking for auto-tune is the slow part. Studio Air takes ~3 s |
| Before button silent | Re-process: Before plays a server-made MP3 of the upload (`<job>_raw.mp3`) |
