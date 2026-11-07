# Handover

_Last updated: 2026-11-07. Prototype stage, runs locally. Not deployed anywhere._

## What works today
- **2 sounds** decoded from real FL presets:
  - **Studio Air** (`untitled2.fst`, 7 plugins)
  - **No Fall** (`nofalltypeshi.fst`, 6 plugins, including Pitcher auto-tune)
- **3 parts:** Lead, Backing, Ad-libs, each layering its own changes on top of the FL chain.
- **Auto-tune** with automatic key detection. Users can override with any of 24 keys or the preset's own scale.
- **Optional beat:** detects its BPM (this sets the delay time), mixes the vocal in, masters to -14 LUFS.
- **Web UI:**
  - live plugin-by-plugin progress
  - synced Before/After with level matching
  - waveform you can scrub
  - MP3 and 24-bit WAV downloads
  - light, dark and system themes
  - phone-friendly layout, plus a two-column layout on desktop

## Measured results (on the artist's 2:23 WhatsApp vocal)
| Check | Result |
|---|---|
| Output loudness / peak | -16.0 LUFS / -1.0 dBFS, every sound and part |
| Clicks per minute (raw = 671) | Studio Air 607 / 334 / 389 · No Fall 577 / 239 / 260 (lead / backing / adlib) |
| Auto-tune accuracy (detected key) | Notes within 10 cents went from 14% to 35% |
| Render time | Studio Air ~3 s · No Fall ~15 s (pYIN pitch tracking is the slow part) |

## Not verified yet: the most important open item
Several plugin values are **best-effort decodes**, marked **check** in [PRESETS.md](PRESETS.md):
- the Parametric EQ 2 Hz scale and band width
- the Reeverb 2 field order and units
- the Phaser fields
- Pitcher speed
- Delay 3 time

**How to close it:**
1. Get the same raw vocal rendered **by FL Studio** through each preset.
2. Run `match.py` against our render.
3. Tune until every band is within ≤ 1 dB.

Screenshots of each plugin window from FL also help.

## Known issues and caveats
- **Studio Air's EQ 3, band 1 is +18 dB (the maximum) at about 67 Hz.** That's a large bass boost on a vocal and possibly a mistake in the original preset. Ask the producer.
- **Key detection:** on the test vocal, 60 s read as C minor and the full song as G# major (they share 6 of 7 notes). Users can override it.
- **Timing:** the delay is synced to 140 BPM when there's no beat.
- **Jobs are in memory:** a restart loses job status, but files stay in `out/jobs/`. There's no cleanup of old files yet.
- **Processing is single-process threads:** fine locally, but needs a job queue before public hosting.
- **The UI bundle is about 700 kB,** mostly three.js. Not code-split yet.

## Planned next (designed, not built)
Clean-up features, each toggleable on the result screen with instant A/B:
1. **Breath and background-noise removal:** a noise profile learned from the gaps (`noisereduce`), and breaths turned down rather than cut. Strength: light, medium or strong.
2. **Word-by-word volume rider:** per-word loudness pulled toward a target within ±3, ±6 or ±9 dB, applied before the FL chain.
3. **Timing correction:** phrase starts nudged toward a 1/16 grid taken from the beat (or a BPM the user enters), at 0–100% strength. Phrase-level only, so there's no stretching damage.

Planned approach: a new `cleanup.py`, called once before `run_chain`. Cache the pitch analysis so each variant renders in 3–5 s, and show what changed on the waveform (breath marks, rider curve, arrows on moved phrases).

**Open decisions for the owner:**
- pre-render all variants vs render each when toggled
- BPM box vs disabling timing when there's no beat
- which features are on by default

Other ideas: pitch-correction strength slider, more FL presets, user accounts, hosting.

## Ground rules
- This repo is **standalone**. Keep it out of any other company or monorepo folder.
- **Never commit a raw vocal.** Artists' recordings are private; `.gitignore` blocks audio in `samples/`.
- Keep FL decoding (`fst_reader.py`) separate from the DSP (`engine.py`). New features go in new modules where possible.
- Measure before claiming "sounds like FL": use `match.py`, click counts and LUFS, not guesses.
