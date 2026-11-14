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
**On Windows**, double-click `start.bat` or run it from the project folder. It runs `start.ps1`, which does the same four steps using `.venv\Scripts`:
```powershell
.\start.bat                # http://localhost:8080 (this PC only)
.\start.bat -Port 9000     # another port
.\start.bat -Lan           # also reachable from a phone on the same Wi-Fi
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

## Raw-take analysis (Phantom, optional)
Each upload is analysed by [Phantom](https://fadelab.net) before mixing (`analysis.py`). If Phantom is missing, the mix still runs and the job shows `analysis_error`.

Phantom doesn't support Windows, so on Windows it runs in WSL. Do this once:
1. In an **admin** PowerShell: `wsl --install -d Ubuntu`, then reboot and create the Ubuntu user.
2. In Ubuntu:
   ```bash
   sudo apt update && sudo apt install -y ffmpeg
   curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
   PHANTOM_NO_TELEMETRY=1 uv tool install phantom-audio --python 3.13   # core only, ~50 MB
   phantom doctor
   ```
3. Back in Windows, check it: `.venv\Scripts\python analysis.py some_vocal.wav` prints the JSON report.

We don't use `curl https://fadelab.net/install | bash`: piped like that, it installs every extra (~2.5 GB of PyTorch), sends install telemetry and adds a Claude Code plugin. On Linux or macOS, skip WSL and set `PHANTOM_CMD=phantom-mcp` (that's already the default off Windows). `PHANTOM_TIMEOUT` (default 120 s) caps how long a job waits for the analysis.

## Key service for auto-tune (optional, in WSL)
`key-service/` detects a song's key from the **beat** someone adds in the auto-tune card. Without it, the app still works: `keys.py` uses its own vocal-based detector.
Build and start it once inside Ubuntu (WSL):
```bash
sudo apt install -y docker.io && sudo systemctl enable --now docker
cd /mnt/c/<path-to>/VocalPreset/key-service
docker build -t key-service:1.0 .
docker run -d --restart unless-stopped --name keysvc -p 8001:8001 key-service:1.0
curl localhost:8001/health      # {"status":"ok"}
```
`start.bat` keeps a WSL session open while the site runs, so the container stays up. Details and tests: `key-service/README.md`.

## Sound engine extras (installed by the start scripts)
The winning sound from the blind A/B (2026-11-13) needs two downloads. Both are optional: without them the site still
runs, just without that part.
| What | Where | Without it |
|---|---|---|
| **AI restoration models** (Roformer de-noise + de-reverb, ~1.8 GB) | `models/`, fetched by `python restore.py --download` | takes skip restoration |
| **Airwindows Consolidated** VST3 (Air3, DeBess, Channel9) | `plugins/`, a pinned, SHA-256-checked download (Windows, Linux) | built-in exciter / de-esser / saturation |

On macOS, install the `.dmg` from [airwin2rack releases](https://github.com/baconpaul/airwin2rack/releases) and copy
`Airwindows Consolidated.vst3` into `plugins/`.
The reverbs are Dragonfly's, captured as impulse responses in `ir/` (in git), so no reverb plugin is needed.
To change them: install [Dragonfly Reverb](https://michaelwillis.github.io/dragonfly-reverb/) and run
`python tools/capture_irs.py "<folder with the Dragonfly .vst3 files>"`.

**NVIDIA GPU (strongly recommended for restoration):** `requirements.txt` installs CPU torch, where restoration takes
about 7x the take's length. With an NVIDIA card, swap in the CUDA build once:
```powershell
.venv\Scripts\python -m pip install --no-cache-dir "torch==2.14.1+cu130" --index-url https://download.pytorch.org/whl/cu130
```
Restoration then runs on the GPU automatically (check: `python -c "import torch; print(torch.cuda.is_available())"`).
Restoration starts the moment a take is uploaded, one take at a time (two at once ran a 16 GB PC out of memory).

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
