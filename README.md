# VocalPreset

**Raw vocal in, mixed vocal out.** Upload a dry vocal, pick a sound and a part (Lead, Backing or Ad-libs), optionally add the beat, and get back a mixed vocal or a mastered song in seconds. No mixing skills needed.

Each "sound" is a real **FL Studio mixer preset (`.fst`)**. We decode the preset file, read every plugin's settings, and rebuild the chain in Python with Spotify's [pedalboard](https://github.com/spotify/pedalboard). FL Studio is not needed to run it.

## Features
- **2 sounds from real FL presets:**
  - **Studio Air**: Limiter → Reeverb 2 → Soundgoodizer → 3× Parametric EQ 2 → Phaser
  - **No Fall**: 2× Parametric EQ 2 → Pitcher (auto-tune) → Limiter → Reeverb 2 → Delay 3
- **Parts:** Lead, Backing (wider, softer, wetter) and Ad-libs (brighter, with echo)
- **Auto-tune** that corrects notes up and down, with automatic key detection or a key you pick
- **Cleanup the FL chain doesn't do:** gain staging, noise gate and de-esser
- **Optional beat:** detects the beat's tempo, mixes the vocal in, and masters the song to -14 LUFS
- **Web app** (React, Tailwind, three.js):
  - live progress through the plugin chain
  - instant Before/After switching with level-matched comparison
  - waveform you can scrub
  - light and dark themes
  - works on phones

## Quick start
```bash
git clone https://github.com/DhavalChauhan94/VocalPreset.git
cd VocalPreset
./start.sh            # → http://localhost:8080
```
You need Python 3.11+, Node.js 20+ and ffmpeg. See **[SETUP.md](SETUP.md)** for details and troubleshooting.

## Docs
| File | What's in it |
|---|---|
| [SETUP.md](SETUP.md) | Install, run, dev mode, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it works: API, audio engine, frontend, the `.fst` format |
| [PRESETS.md](PRESETS.md) | How to add a new FL preset and how each plugin is mapped |
| [HANDOVER.md](HANDOVER.md) | Current state, what's verified, known issues, next steps |
| [CLAUDE.md](CLAUDE.md) | Short guide for AI coding assistants working in this repo |

## Command line
```bash
.venv/bin/python fst_reader.py samples/untitled2.fst presets/lead/studio_air.json   # decode a preset
.venv/bin/python engine.py my_vocal.mp3 lead out.wav --sound no_fall [--beat beat.mp3]
.venv/bin/python match.py out.wav fl_export.wav    # compare with FL Studio's own render
```

## Status
This is a working prototype. Some plugin settings are best-effort decodes; [HANDOVER.md](HANDOVER.md) lists exactly which ones.
