# CLAUDE.md: VocalPreset

> A lean index for AI assistants. Details live in the focused docs below, so open the one that matches the task.
> Keep this file **under 150 lines**. New detail goes into the topic doc, not here.

| Doc | Read it when… |
|---|---|
| [SYSTEM-BRIEF.md](SYSTEM-BRIEF.md) | **Start here:** the whole system on one page (flow, fix chain, files, rules, open items) |
| [README.md](README.md) | You need the one-screen overview (GitHub front page) |
| [SETUP.md](SETUP.md) | Installing, running, dev mode, ports, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Touching the API, engine pipeline, auto-tune, frontend, A/B audio graph |
| [PRESETS.md](PRESETS.md) | Adding an FL preset, decoding a plugin, mapping a new plugin |
| [HANDOVER.md](HANDOVER.md) | Current state, measurements, unverified values, known issues, next steps |
| [CHANGELOG.md](CHANGELOG.md) | What changed, day by day (add an entry with every merge to main) |

## What this is
A web app that makes a raw vocal sound studio-finished in one tap:
- **Flow:** a dry vocal → Phantom analysis → pick a **sound** (Rap / Melodic rap / Singer-Pop, `fixer.STYLES`) → optional auto-tune (key from the vocal or a beat) → fix → live mix rack → MP3/WAV.
- **Kept for the artist dashboard, not in the UI:** the FL Studio preset engine (`fst_reader.py`, `engine.process`, `presets/`).
- **Engine:** Python, built on Spotify's pedalboard plus librosa.
- **API:** FastAPI on **:8080**.
- **UI:** React 18, Vite 6, Tailwind 4.1, three.js and Headless UI in `web/`, built into `web/dist` and served by FastAPI.

## Run
```bash
./start.sh  (Windows: start.bat)   # venv + deps + UI build + server → http://localhost:8080
cd web && npx vite            # UI hot reload on :5173 (proxies /api → :8080)
```

## Map
```
fst_reader.py   .fst → presets/<sound>.json   (FLhd/FLdt events; per-plugin blob decoders)
engine.py       load → pre_clean → run_chain (FL plugins) → part tweaks → mix/master
app.py          /api/takes (analyse → key → fix, the current UI) · legacy /api/jobs + /api/sounds · serves web/dist
fixer.py        STYLES (rap / melodic / pop: tone target, dynamics, space, auto-tune default) · studio chain: PREP (clean/hum/resonance/auto-tune, cached) → POLISH (scaled by Mix) → SPACE (doubler, ducked convolution reverb + ping-pong) → TP master · render() for Mix-panel tweaks
restore.py      AI restoration from upload: Roformer de-noise -> de-reverb (audio-separator; models/, optional, one take at a time)
pro.py          Airwindows Consolidated VST3 via pedalboard (Air3 / DeBess / Channel9; plugins/, optional, built-in DSP fallback)
ir/             Dragonfly Reverb room/plate/hall captured as IRs (tools/capture_irs.py): same file on server + browser
tune.py         auto-tune: WORLD vocoder <5 kHz on voiced frames, original air/consonants kept   keys.py  vocal held-note key detector (+ beat via key-service)
analysis.py     Phantom (WSL) full_diagnostic over MCP
match.py        our render vs FL Studio's render (per-band dB, LUFS, peak)
web/src/        App.jsx · mixEngine.js (live mixer) · components/{StylePicker,Report,Autotune,MixPanel,Knob,Orb,DotWaves,Pickers,Parts}.jsx · index.css (theme tokens)
presets/        decoded sounds, by part: lead/ backing/ adlib/ (+ fx/, not registered)   samples/  source .fst files
```

## Rules (non-negotiable)
1. **Never commit audio of a person.** Raw vocals stay git-ignored (`samples/*.mpeg|wav|mp3…`, `out/`).
2. **Don't hand-tune audio by ear.** Measure: LUFS/peak, the click count (see HANDOVER), and `match.py` against an FL render.
3. **Keep decoding and DSP separate.** Plugin layouts go in `fst_reader.py`, sound processing in `engine.py`. A new feature, e.g. cleanup, goes in a new module called from `process()`.
4. **Never use pedalboard's `Limiter` as a ceiling.** It's a JUCE maximiser that adds about 4 dB. Use `brickwall()` / `ceiling()`.
5. **Never pass a per-sample pitch array to `time_stretch`.** It clicks at every 1024-sample chunk. Use `_shift_by_notes()`, which applies a constant shift per note with crossfades.
6. **UI colours come from CSS variables** (`--bg --fg --mist --panel --line --pop`) through the Tailwind tokens `bg`, `fg`, `mist` and so on. Never hard-code white or black on neutral surfaces, or light mode breaks. `text-white` is fine only on ember/violet fills.
7. **The result player is `web/src/mixEngine.js`** (decoded stems, sample-accurate). It mirrors `fixer.space()`/`mixdown()` using the numbers in `fixer.FX` and the server's IRs (`/api/ir/`). Change both sides together, or the preview and the download drift apart.
8. **Values marked "check" in PRESETS.md are unverified.** Don't present them as exact FL settings.
9. **Back up a file before a risky edit** (`cp -a f f.bak-$(date +%Y%m%d-%H%M%S)`). Backups are git-ignored.

## Conventions
- Audio inside the engine is `float32`, shape `(channels, samples)`, at 44.1 kHz. Use `load()` / `save()`.
- Loudness targets: -18 LUFS before the chain, stems at -16 LUFS, the fixed vocal mastered to -12 LUFS / -1.2 dBTP (legacy preset engine: -16 vocal, -14 with a beat).
- `engine.process(..., progress=cb)` reports `stage`, `plugin` (with its slot) and `meta` (key, bpm, lufs_raw). The UI's live pipeline depends on these.
- Adding a sound means: decode it into `presets/<id>.json`, then add an entry to `engine.SOUNDS`. The UI picks it up from `/api/sounds`.

## Verify after a change
```bash
.venv/Scripts/python -m pytest tests                                # Windows; macOS/Linux: .venv/bin/python
cd web && npx vite build                                            # UI must build clean
```
Then open the UI, drop a real take, pick each sound, fix, turn knobs while it plays, and download both formats.
Legacy preset engine:
```bash
.venv/bin/python fst_reader.py samples/nofalltypeshi.fst >/dev/null && echo decode-ok
.venv/bin/python engine.py <vocal> lead /tmp/t.wav --sound no_fall   # expect -16.0 LUFS, peak -1.0
```
