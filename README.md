# VocalPreset

**Bedroom take in, studio-finished vocal out.** Drop a dry vocal: a phone recording, a WhatsApp voice note or a video. VocalPreset checks it like an engineer would, explains what's off in plain words, and fixes it in one click. You pick the sound (**Rap**, **Melodic rap** or **Singer / Pop**) and can add auto-tune in the right key.

> **What's new?** See **[CHANGELOG.md](CHANGELOG.md)**. For the current state, the measurements and what's next, see **[HANDOVER.md](HANDOVER.md)**.

## How it works
1. **Analyse.** [Phantom](https://fadelab.net) (FadeLab) runs about 20 checks: noise, hum, ringing frequencies, harshness, sibilance, loudness, clipping and more. You get a studio-readiness score (0–100) and a plain-English report.
2. **Pick your sound.** Each sound has its own compression, tone, space and auto-tune default. The settings come from mix engineers' own accounts of mainstream records ([sources](ARCHITECTURE.md#vocal-styles-fixerstyles-rap--melodic-rap--singer--pop)).

   | | Sounds like | Auto-tune |
   |---|---|---|
   | **Rap** | dry and punchy: heavy compression, grit, no reverb wash | off (Light centres the pitch) |
   | **Melodic rap** | hard-tuned and floating: dark hall, 1/4-note echoes, wobbling doubles | Heavy |
   | **Singer / Pop** | smooth and polished: bright plate, soft echoes. Also suits R&B and lo-fi | Medium |
3. **Auto-tune (optional).** Choose Light, Medium or Heavy. The key is read from your sung notes, or from your beat if you add it (the most accurate option), and shown on a piano. One tap changes it.
4. **Fix.** The fix runs in four stages:
   - cleanup: denoise, hum notches, resonance cuts;
   - auto-tune (WORLD vocoder, glitch-free);
   - studio polish;
   - reverb, echo and doubles.

   It's mastered to -12 LUFS with true peaks under -1.2 dBTP, then re-checked, so you see the before → after score.
5. **Mix rack.** Eight knobs: Mix (starts at 40%), Reverb, Echo, Repeats, Width, Wobble, Brightness and Warmth, plus reverb and echo types. Every change is instant because the mix plays live in the browser.
6. **Download or share.** Get an MP3 (320k) or a 16-bit WAV, named after your file, e.g. `Recording (154) - Rap mix.mp3`. **Share MP3** sends it straight to WhatsApp and other apps.

## Quick start
```bash
git clone https://github.com/DhavalChauhan94/VocalPreset.git
cd VocalPreset
start.bat          # Windows  → http://localhost:8080
./start.sh         # macOS / Linux
```
You need Python 3.11+, Node.js 20+ and ffmpeg. Phantom analysis and the key-service are optional: without them the site still runs, using a generic polish and the built-in key detector. See **[SETUP.md](SETUP.md)**.

## Docs
| File | What's in it |
|---|---|
| [SYSTEM-BRIEF.md](SYSTEM-BRIEF.md) | The whole system on one page, with diagrams: give it to Claude Code first |
| [CHANGELOG.md](CHANGELOG.md) | What changed, day by day |
| [HANDOVER.md](HANDOVER.md) | Current state, measured results, known issues, next steps |
| [SETUP.md](SETUP.md) | Install, run, Phantom and key-service setup, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | API, the studio chain, vocal styles (with sources), auto-tune, key detection, the live mixer |
| [PRESETS.md](PRESETS.md) | The FL Studio preset decoder (kept for the artist dashboard) |
| [CLAUDE.md](CLAUDE.md) | Short map and rules for AI coding assistants |

## Main files
| | |
|---|---|
| `app.py` | FastAPI: `/api/takes` (analyse → key → fix → mix export), downloads, serves the UI |
| `fixer.py` | The studio chain and the three vocal styles (`STYLES`) |
| `tune.py` / `keys.py` | Auto-tune / key detection |
| `analysis.py` | Phantom analysis over MCP (runs in WSL on Windows) |
| `web/src/` | React UI. `mixEngine.js` is the live in-browser mixer |
| `key-service/` | Essentia key-detection microservice (Docker, optional) |
| `engine.py`, `fst_reader.py`, `presets/` | The FL Studio preset engine: not in the UI now, kept for the artist dashboard |

## Tests
```bash
.venv/Scripts/python -m pytest tests    # Windows (macOS/Linux: .venv/bin/python); needs: pip install pytest httpx
cd web && npx vite build                # the UI must build clean
```

## Status
A working prototype that runs locally and isn't deployed yet. The next focus is sound quality. [HANDOVER.md](HANDOVER.md) lists what's measured, what isn't verified, and the open issues.
