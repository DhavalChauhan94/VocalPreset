# CLAUDE.md: VocalPreset

> A lean index for AI assistants. Details live in the focused docs below, so open the one that matches the task.
> Keep this file **under 150 lines**. New detail goes into the topic doc, not here.

| Doc | Read it when… |
|---|---|
| [README.md](README.md) | You need the one-screen overview (GitHub front page) |
| [SETUP.md](SETUP.md) | Installing, running, dev mode, ports, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Touching the API, engine pipeline, auto-tune, frontend, A/B audio graph |
| [PRESETS.md](PRESETS.md) | Adding an FL preset, decoding a plugin, mapping a new plugin |
| [HANDOVER.md](HANDOVER.md) | Current state, measurements, unverified values, known issues, next steps |

## What this is
A web app that makes a raw vocal sound mixed in one tap:
- **Input:** a dry vocal, a **sound** (a decoded FL Studio `.fst` mixer preset), a **part** (Lead, Backing or Ad-libs), and optionally a beat.
- **Engine:** Python, built on Spotify's pedalboard plus librosa.
- **API:** FastAPI on **:8080**.
- **UI:** React 18, Vite 6, Tailwind 4.1, three.js and Headless UI in `web/`, built into `web/dist` and served by FastAPI.

## Run
```bash
./start.sh                    # venv + deps + UI build + server → http://localhost:8080
cd web && npx vite            # UI hot reload on :5173 (proxies /api → :8080)
```

## Map
```
fst_reader.py   .fst → presets/<sound>.json   (FLhd/FLdt events; per-plugin blob decoders)
engine.py       load → pre_clean → run_chain (FL plugins) → part tweaks → mix/master
app.py          /api/sounds · /api/jobs (thread + progress) · /api/file · serves web/dist
match.py        our render vs FL Studio's render (per-band dB, LUFS, peak)
web/src/        App.jsx · components/{Orb,DotWaves,Pickers,Parts}.jsx · index.css (theme tokens)
presets/        decoded sounds, by part: lead/ backing/ adlib/ (+ fx/, not registered)   samples/  source .fst files
```

## Rules (non-negotiable)
1. **Never commit audio of a person.** Raw vocals stay git-ignored (`samples/*.mpeg|wav|mp3…`, `out/`).
2. **Don't hand-tune audio by ear.** Measure: LUFS/peak, the click count (see HANDOVER), and `match.py` against an FL render.
3. **Keep decoding and DSP separate.** Plugin layouts go in `fst_reader.py`, sound processing in `engine.py`. A new feature, e.g. cleanup, goes in a new module called from `process()`.
4. **Never use pedalboard's `Limiter` as a ceiling.** It's a JUCE maximiser that adds about 4 dB. Use `brickwall()` / `ceiling()`.
5. **Never pass a per-sample pitch array to `time_stretch`.** It clicks at every 1024-sample chunk. Use `_shift_by_notes()`, which applies a constant shift per note with crossfades.
6. **UI colours come from CSS variables** (`--bg --fg --mist --panel --line --pop`) through the Tailwind tokens `bg`, `fg`, `mist` and so on. Never hard-code white or black on neutral surfaces, or light mode breaks. `text-white` is fine only on ember/violet fills.
7. **The Web Audio graph binds to the `<audio>` elements once.** Keep both elements always mounted and change only `src`.
8. **Values marked "check" in PRESETS.md are unverified.** Don't present them as exact FL settings.
9. **Back up a file before a risky edit** (`cp -a f f.bak-$(date +%Y%m%d-%H%M%S)`). Backups are git-ignored.

## Conventions
- Audio inside the engine is `float32`, shape `(channels, samples)`, at 44.1 kHz. Use `load()` / `save()`.
- Loudness targets: -18 LUFS before the chain, -16 LUFS for vocal-only output, -14 LUFS for a mix with a beat, -1 dBFS ceiling.
- `engine.process(..., progress=cb)` reports `stage`, `plugin` (with its slot) and `meta` (key, bpm, lufs_raw). The UI's live pipeline depends on these.
- Adding a sound means: decode it into `presets/<id>.json`, then add an entry to `engine.SOUNDS`. The UI picks it up from `/api/sounds`.

## Verify after a change
```bash
.venv/bin/python fst_reader.py samples/nofalltypeshi.fst >/dev/null && echo decode-ok
.venv/bin/python engine.py <vocal> lead /tmp/t.wav --sound no_fall   # expect -16.0 LUFS, peak -1.0
cd web && npx vite build                                            # UI must build clean
```
Then open the UI, process a vocal, and check that Before/After switch while playing and that the plugin list advances.
