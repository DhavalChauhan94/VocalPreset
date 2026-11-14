# Handover

_Last updated: 2026-11-14. Prototype, runs locally, not deployed. What changed, day by day, is in [CHANGELOG.md](CHANGELOG.md)._

## What works today
- **Analysis:** Phantom (FadeLab) runs about 20 checks on every upload and produces a studio-readiness score (0–100) and an animated plain-English report. If Phantom isn't installed, the fix still runs with a generic polish.
- **Vocal sounds:**
  - **Rap**, **Melodic rap** and **Singer / Pop** (`fixer.STYLES`), picked first after upload.
  - Each one shapes compression, gate, tone, saturation and space, and sets an auto-tune default.
  - The numbers and their sources are in ARCHITECTURE.md.
- **Auto-tune:**
  - Light, Medium or Heavy, using the WORLD vocoder below 5 kHz, with the original air and consonants kept.
  - Key from the sung notes, or from the beat (most accurate).
  - When two keys fit equally well, the UI says so and offers one-tap choices.
- **AI restoration** (`restore.py`): Roformer de-noise → de-reverb from upload, so phone and bedroom takes start booth-dry (optional; GPU strongly recommended).
- **Fix:**
  - cleanup (denoise, hum notches, resonance cuts) → polish with Airwindows Air3 / DeBess / Channel9 (`pro.py`) → space (doubler, Dragonfly reverb IRs, ping-pong echo, both ducked under the voice);
  - master to -12 LUFS with true peaks ≤ -1.2 dBTP;
  - then re-analysed, with a before → after score.
- **Mix rack:** 8 knobs (Mix, starting at 40%, Reverb, Echo, Repeats, Width, Wobble, Brightness, Warmth) plus reverb and echo types. Everything is mixed live in the browser, so every change is instant. Downloads re-render on the server with the same numbers.
- **Downloads:**
  - MP3 320k (ID3v2.3) and 16-bit WAV, named `<upload> - <Style> mix`;
  - a **Share MP3** button using the Web Share API.
- **Security:**
  - uploads are kept private and never served;
  - strict download names;
  - ffmpeg decodes are whitelisted and capped;
  - request size is limited;
  - server paths are never sent to the browser.
- **Housekeeping:** leftover renders and uploads from earlier runs are deleted when the server starts.

## Measured results
**Vocal sounds on two real takes** (`Recording (154)`, `Recording (261)`). Every row hits -12 LUFS with true peak ≤ -1.09 dBTP and tone within 1.8 dB of the style's target:

| Take | Rap | Melodic | Pop |
|---|---|---|---|
| 154 (noisy room), readiness | 68 → 98 | 68 → 98 | 68 → 98 |
| 261 (sung melody), readiness | 67 → 88* | 67 → 100 | 67 → 100 |
| reverb level vs dry (dB) | -27.7 | -11.5 | -15.1 |
| width (dB) | -28 | -12 | -15 |

\* Rap leaves auto-tune off, so Phantom reads the held notes' harmonics as a resonance. Read as F# minor notes, the flag goes away.

**Key detection:**
- **Benchmark:** 96% right 7 notes / 88% exact key on 96 held-out synthetic melodies.
- **Recording 261** (F# minor): on its own it reads "C# minor or F# minor" with an F# minor chip; with the beat it reads F# minor at 0.87 confidence.
- **Heavy auto-tune** on 261 takes the voice from 29% to 90% of frames within 15 cents.

**Speed:**
- fix: ~10 s without auto-tune, ~35–45 s with it;
- a mix export: ~9 s;
- the page's first load: 284 kB of JS, with three.js loading after the page shows.

**New engine vs the blind-test winner (D):**
- 154 in a room: 0.03 dB, correlation 1.000. 154 worst case: 0.07 dB, correlation 0.995.
- 261 (heavy auto-tune): within 0.89 dB, loudness envelope 0.998. The waveform differs because the WORLD vocoder rebuilds phase from pitch.
- Phantom doesn't track the owner's ear here (D on 154_worst scored 70 against today's 76, but won), so the ears decide.

## Known issues
- **Before a commercial launch, check the two AI models' licences.** Their original authors haven't confirmed them: a mirror says MIT, and the same author's sibling de-reverb model is GPL-3. Running them on our own server is fine; redistributing or selling access needs the licence confirmed.
- **Restoration needs a GPU to feel fast.** On this RTX 3050 it's ~1.2–1.8× the take's length; on CPU it's ~7×. It runs one take at a time, because two at once ran a 16 GB PC out of memory. Hosting needs a GPU worker and a queue.
- **Disk:** the models (1.8 GB), CUDA torch (~4 GB) and renders add up. The dev PC was at 99% full on 2026-11-13.
- **Mac:** the Airwindows plugin is a manual install (`.dmg` → `plugins/`). Without it the built-in processors run.
- **Sound quality:** the next round of listening should be on the new engine. Judge on real phone, laptop and WhatsApp takes, blind, against a pro reference.
- **The readiness score measures the full fix (Mix 100%), but the default Mix is 40%.** At 40%, take 154 measures 70 instead of 98 because the polish is only partly applied. Decide whether the score should describe the 40% download.
- **A WAV longer than about 1.5 minutes is over WhatsApp's 16 MB audio limit.** It has to go as a Document; the MP3 sends as audio.
- **The Share button** only appears over HTTPS or on localhost, not when a phone opens the PC's LAN address.
- **Jobs live in memory:** a restart forgets every take, and its files are deleted at the next start. Within a run there's no time limit yet (`shortcut:` in `app.py`).
- **One process with threads:** fine locally. Before public hosting it needs a job queue, storage with a time limit, and auth.
- **Phantom runs in WSL Ubuntu on Windows** (see SETUP.md). The key-service runs as a Docker container in WSL, and `start.ps1` keeps WSL awake while the site runs.

## Not verified
- The style tone targets are measured on two takes only. They're marked **check** in `fixer.py`.
- The FL preset decodes are marked **check** in [PRESETS.md](PRESETS.md). The preset engine isn't in the UI right now.

## Next steps
1. **Sound quality:** more real takes in each style, A/B against reference tracks, and a fix for the score-versus-40% question above.
2. **More vocal sounds** later (the owner said "we can add more later"). Adding one means a new entry in `fixer.STYLES` plus `VOCAL_STYLES` in `web/src/components/StylePicker.jsx`.
3. **Artist dashboard and profiles:** the FL presets (`presets/`, `engine.py`, `/api/sounds`) are kept for this.
4. **Hosting:** job queue, storage limits, HTTPS, accounts.

## Ground rules
- **Never commit a raw vocal.** Artists' recordings are private, and `.gitignore` blocks audio in `samples/` and all of `out/`.
- **`fixer.space()`/`mixdown()` and `web/src/mixEngine.js` must change together,** or the preview and the download drift apart.
- **Measure before claiming a sound is better:** Phantom score, LUFS, true peak, clicks, and the tone error against the style target.
- **Feature work happens on a branch.** Merge into `main` once tests pass and the UI builds.
