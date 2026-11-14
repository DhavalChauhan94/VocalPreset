# VocalPreset: system brief for Claude Code

_State on 2026-11-14. Paste this into Claude Code at the start of a session. Details: CLAUDE.md (map + rules),
ARCHITECTURE.md (how it works), HANDOVER.md (status, numbers, open issues), CHANGELOG.md (what changed when)._

## What it is
A web app for small rappers and singers: upload a raw vocal (phone, laptop, WhatsApp voice note) and get back a
studio-finished vocal in one click. The bar: ANY recording must come out studio-ready. Quality is judged by blind
listening on real, bad takes. Meters (Phantom score, LUFS) only support the ears.

## Where the code is
- Everything is in `main` on GitHub (2026-11-14): the full flow (analyse, pick a sound, auto-tune, fix, live mixer,
  download/share) and the new sound engine that won the blind test 7 of 9 clips (AI restoration + Airwindows
  processors + Dragonfly reverb). Feature work happens on a branch first, then merges here.

## The flow
```
IN THE BROWSER (React, web/)              ON THE SERVER (FastAPI, app.py, port 8080)      USES (optional)
1 Upload a vocal  ─────── vocal ───────▶  Check the take        analysis.py               Phantom, in WSL Ubuntu
                  ◀─ report + score ────        │ then, in the background
                                          AI clean-up           restore.py                AI models + GPU
2 Pick a sound + auto-tune ── asks ────▶  Find the key          keys.py                   key-service, Docker in WSL
                           ◀── key ─────
3 Fix my vocal ── sound, tune, key ────▶  Fix and polish        fixer.py tune.py pro.py   Airwindows, Dragonfly IRs
4 Live mixer (8 knobs)  ◀── 2 stems + duck curve ── (fix waits for the AI clean-up if it isn't done)
5 Download / Share ── knob settings ───▶  Export                fixer.render  → MP3 320k / WAV 16-bit
```
- Nothing waits on a request: the server runs each take in a thread, and the browser polls `GET /api/jobs/{id}`.
- API: `POST /api/takes` (upload) → `/api/takes/{id}/key` → `/api/takes/{id}/fix` → `/api/takes/{id}/mix` (export).
- After the fix, Phantom checks the result again, so the page shows a before → after score.

## Inside the fix (fixer.py)
```
CLEAN IT (full strength)      TUNE IT (optional)    POLISH IT                     MIX KNOB        SPACE + LOUD
AI de-noise + de-reverb  ──▶  Auto-tune  ──┬──▶     Air (Airwindows Air3)    ──▶  blends the  ──▶ Double
rumble + hiss cut              (WORLD,     │        Compress (2 + parallel)       two stems,      Reverb (Dragonfly IR)
hum notches                    tune.py)    │        De-ess (Airwindows DeBess)    40% default     Echo (ducks under voice)
ringing cuts                               │        Colour (Airwindows Channel9)                  Master: -12 LUFS, -1.2 dBTP
                                           │        Gap gate
                                           └─ stem 1: your cleaned voice ─────▶ (stem 2: the polished voice)
```
- The browser gets both stems and mixes them live (`web/src/mixEngine.js`), so every knob is instant. The download
  re-renders the same settings on the server (`fixer.render`). These two must stay in step (rule 2 below).
- No Airwindows plugin installed? Built-in exciter, de-esser and saturation run instead. No models? The AI clean-up is
  skipped. The site always works.

## The three sounds (`fixer.STYLES`, picked first after upload)
| Sound | Feel | Auto-tune default | Space |
|---|---|---|---|
| Rap | dry, punchy, crushed | off | tiny room, slap echo, almost no width |
| Melodic rap | hard-tuned, floating | heavy | dark hall, 1/4-note echoes, wide wobbling doubles |
| Singer / Pop | smooth, polished (also R&B, lo-fi) | medium | bright plate, soft 1/8 echoes |

## Files (plain words)
| File | What it does |
|---|---|
| `app.py` | The API: uploads, jobs, downloads; serves the built UI |
| `analysis.py` | Asks Phantom (FadeLab) to check a take; runs in WSL Ubuntu over MCP |
| `restore.py` | AI clean-up: Roformer de-noise, then de-reverb (audio-separator). One take at a time |
| `keys.py` | Finds the key from sung notes; the beat via `key-service/` (Essentia, Docker) is most accurate |
| `fixer.py` | The studio chain, the three sounds, mixdown/render, scores |
| `tune.py` | Auto-tune with the WORLD vocoder (no glitches) |
| `pro.py` | Loads Airwindows Consolidated (VST3) through pedalboard |
| `ir/` | Dragonfly reverbs (room/plate/hall) captured as files; remake with `tools/capture_irs.py` |
| `web/src/` | React UI: `App.jsx`, `mixEngine.js` (live mixer), `components/` (StylePicker, Autotune, MixPanel, Report...) |
| `engine.py`, `fst_reader.py`, `presets/` | Old FL Studio preset engine: not in the UI, kept for a future artist dashboard |
| `models/`, `plugins/`, `out/` | Downloads and renders: git-ignored. `out/` is wiped at every server start |

## Run and test
- Windows: `start.bat` → http://localhost:8080 (macOS/Linux: `./start.sh`). The first start downloads the Airwindows
  plugin (13 MB, checksum-checked) and the AI models (~1.8 GB).
- NVIDIA GPU (makes the AI clean-up ~6x faster): `.venv\Scripts\python -m pip install --no-cache-dir "torch==2.14.1+cu130" --index-url https://download.pytorch.org/whl/cu130`
- Optional helpers: Phantom (WSL Ubuntu) and the key-service (Docker in WSL); see SETUP.md.
- Tests: `.venv/Scripts/python -m pytest tests` (36 pass) and `cd web && npx vite build` (must be clean).

## Rules
1. Never commit audio of a person. Raw vocals and `out/` stay git-ignored.
2. `fixer.space()`/`mixdown()` and `web/src/mixEngine.js` change together, or the preview and the download differ.
3. Judge sound by blind A/B on real bad takes (phone, laptop, WhatsApp). Never blame the recording.
4. Never use pedalboard's `Limiter` as a ceiling; use `engine.brickwall`.
5. Work on a branch; merge to `main` only when tests pass and the UI builds. Add a CHANGELOG entry.
6. Uploads are never served; only our own render names download (`_SERVABLE` in app.py).

## Open items
- The owner listens to 10 real phone, laptop and WhatsApp takes on the new engine (step 1 of the plan).
- The two AI models' licences aren't confirmed by their authors: check before a commercial launch.
- Hosting needs a GPU worker and a job queue; the AI clean-up runs one take at a time.
- The readiness score measures the full fix (Mix 100%), but the Mix knob starts at 40%.
- macOS: the Airwindows plugin is a manual install (`.dmg` → `plugins/`).
