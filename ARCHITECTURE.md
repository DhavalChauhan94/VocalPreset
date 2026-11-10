# Architecture

## Big picture
```
 Browser (React + three.js)                 FastAPI  (app.py, :8080)                    Audio engine (engine.py)
 ─────────────────────────                  ─────────────────────────                   ────────────────────────
 pick vocal / sound / part / key / beat ──► POST /api/jobs ──► thread ──────────────►  process():
                                             returns {id}                                load (ffmpeg → float32)
 poll every 350 ms  ◄────────────────────── GET /api/jobs/{id}  ◄── progress() ◄──────  pre_clean → run_chain(FL chain)
   stage, current plugin slot, key, bpm                                                  → mix with beat → master
 result: waveform peaks, LUFS, files  ◄──── GET /api/file/{id}.mp3 | .wav | _raw.mp3
                                            GET /api/sounds  (presets + their chains)
 serves web/dist (built UI) at "/"

 Offline:  FL Studio .fst ──► fst_reader.py ──► presets/<role>/<sound>.json  (read by engine.load_sound)
```

## Current flow: analyse → (auto-tune key) → fix
The UI no longer offers presets. The preset engine (`engine.process`, `/api/jobs`, `/api/sounds`, the `presets/` folder) stays for the future artist dashboard.

1. **Analyse.** `POST /api/takes` (`vocal`) keeps the upload at `out/jobs/{id}_in.ext`. Phantom then writes `analysis` (its report), `score` (0–100 studio readiness) and `plan` (the fix steps it would run).
2. **Key (only if auto-tune is on).** `POST /api/takes/{id}/key` → `keys.detect`. It calls the key-service (`KEY_SERVICE_URL`, Essentia 3-profile vote) and falls back to `engine.detect_key` (librosa) if that's down.
3. **Fix.** `POST /api/takes/{id}/fix` takes `{autotune: off|light|medium|heavy, key}`.
   - `fixer.plan` turns findings into steps, and `fixer.fix` applies them with pedalboard + librosa + engine helpers.
   - The output is re-analysed and stored as `analysis_after`, `score_after` and `fixed[]`.
   - Clipping and lossy files are never counted as fixed: the damage is baked in, so the score keeps their penalty.
4. **Polling.** `GET /api/jobs/{id}` reports status `analysing` → `analysed` → `fixing` → `done` (or `error`). It uses the same `stage`/`slot` fields the Pipeline UI already reads.

**Key detection (`keys.py`).** Essentia (the key-service) is made for full mixes. On dry vocals it got the 7 notes right only 62% of the time, and it picked C major for an F# minor take. Now:

1. **Vocal (primary).**
   - pYIN, then *held notes* (stable within ±30 c for ≥ 100 ms, weighted by duration). Slides and passing pitches are dropped.
   - The 7-note scale that covers the most held time is chosen.
   - The tonic among the candidate scales (within 4% fit) is picked from:
     - Krumhansl-Kessler and Albrecht-Shanahan profiles;
     - phrase-ending notes (the last held note before a ≥ 250 ms pause);
     - time on the note;
     - the longest notes.
   - Essentia on the vocal is only a +0.15 tie-break vote.
2. **Beat (optional, most accurate).** `POST /api/takes/{id}/key` accepts a `beat` file, stored in `out/takes`, never served.
   - The key-service reads the instrumental. Its key is used only if the vocal's held notes fit that scale within 10% of the best scale.
   - A wrong beat reading therefore can't override a clear vocal.
3. **Honest output.** `alternatives` (top 4) are shown as one-tap chips. `low_confidence` plus a plain warning appear when another 7-note set fits just as well (< 1% apart), because the melody never sings the note that separates them.

**Measured:**
- **Benchmark:** 96 synthetic sung melodies in all 24 keys, with ±35 c detune, vibrato, jitter, slides, noise, and phrases ending on the tonic only half the time. Set A is used for weights; held-out set B uses different seeds.
- **Results:** new detector 88% exact key / **96% right 7 notes** on held-out B. On set A: old detector 81% / 88%, Essentia on the vocal 46% / 62%.
- **Real take (Recording 261, user says F# minor):**
  - vocal alone → C# minor, flagged "fits C# minor and F# minor equally", with an F# minor chip;
  - with an F# minor beat → F# minor;
  - Heavy auto-tune in F# minor → 29% → 90% of voiced frames within 15 c.

**Studio chain (`fixer.py`), v2.** v1 measured right but sounded over-bright and thin ("laptop mix"). The chain is split into three stages so the Mix panel can re-render fast:

| Stage | Step | What it does |
|---|---|---|
| PREP (full strength; cached as `out/takes/{id}_prep.npy`) | clean | 24 dB/oct 75 Hz HPF + stationary spectral denoise → -18 LUFS |
| | hum | scipy notches at the hum frequency and its 2×/3×/4× (only when Phantom's salience ≥ 0.1) |
| | eq | measured resonance cuts (before auto-tune: tuned harmonics look like resonances) |
| | autotune | `tune.py` (WORLD below 5 kHz, voiced frames only) |
| POLISH (every move scaled by **Mix**) | bright | EQ toward the target + gentle even-harmonic exciter (0.12, >7 kHz) |
| | dynamics | 4:1 (10 ms) → 3:1 (15 ms) + 35% parallel "New York" compression + look-ahead peak control |
| | sibilance | dynamic cuts for 2.5–5 kHz (harshness) and 5.5–11 kHz (S/T), only when they stab out |
| | tone | tape-style asymmetric saturation (warmth) → iterative EQ to the target → rumble HPF again |
| | gate | gap expander (floor -32 dB) |
| SPACE | doubler | 14/21 ms modulated copies, panned L/R |
| | reverb | **convolution** with a synthetic stereo IR (per-band decay; Room/Plate/Hall) |
| | delay | ping-pong delay |
| | master | -12 LUFS, ≤ -1.2 dBTP (4×-oversampled peaks into `engine.brickwall`) |

- **Ducking:** reverb and delay both duck about 6 dB while the voice plays and bloom in the gaps.
- **TARGET v2** (dB vs 1 kHz, loud frames, marked **check**): `[-4, -5.5, -5, 0, -4, -9, -14, -19]` across 113 Hz–12.8 kHz. That's warm body and a top end 4–5 dB below v1.
- **Brightness/Warmth** tilt the target by up to ±6 / ±3 dB. `target_curve()` holds the tilt shapes.

**Mix rack (live).** The fix writes two level-matched mono stems (-16 LUFS, 24-bit FLAC, sample-accurate) plus the ducking curve (100 Hz), and the job carries `fixer.FX`:
- `{id}_s0.flac`: your cleaned/tuned voice;
- `{id}_s1.flac`: the polished voice.

`web/src/mixEngine.js` decodes the stems and rebuilds `fixer.mixdown()` + `space()` in Web Audio:
- the Mix crossfade s0↔s1;
- Warmth/Brightness shelves (biquads at Q 0.7071, the same as pedalboard's shelves on the server);
- the doubler (LFO-modulated DelayNodes);
- a 2nd-order Butterworth send into a ConvolverNode, using the server's own IRs from `/api/ir/{room|plate|hall}.wav` with normalization off;
- a feedback ping-pong echo;
- ducking via `setValueCurveAtTime` with the server's curve;
- a preview limiter.

**Every knob changes the audio graph directly, with no server call** (measured: Mix to 45% in 32 ms while playing).

**Download** = `POST /api/takes/{id}/mix` with the rack settings. The server runs `fixer.render(s0, s1, duck, s)` and writes the true-peak -12 LUFS master as `{id}_v{n}`; the newest export wins. It's skipped when the settings are unchanged.

The **Mix** knob is plain dry/wet between the two stems. Both have the same tuning and no latency between them, so there's no comb filtering.

**Measured on Recording 154 with v2:**
- Phantom score 68 → 98 (off/light), 92 (heavy), 82 (medium; mud and SNR sit right at Phantom's limits)
- 2–5 kHz harsh spikes 6.4 → 3.5–4.1 dB (v1: 4.0)
- new clicks +15 (off) to +49
- full fix about 8 s (off) / about 35 s (auto-tune); a Mix-panel re-render takes about 9 s on 83 s, including the MP3 encode

Unit tests: `PYTHONPATH=. .venv/Scripts/python -m pytest tests/`.

## Files
| Path | Role |
|---|---|
| `fst_reader.py` | Decodes an FL mixer-track preset (`.fst`) into a JSON plugin chain |
| `presets/<role>/*.json` | Decoded presets, one file per "sound", sorted by part: `lead/` (6), `backing/` (3), `adlib/` (3). `fx/` holds decoded effect presets that are not registered |
| `engine.py` | All DSP: loading, cleanup, each FL plugin's equivalent, auto-tune, mixing, mastering |
| `app.py` | FastAPI: job API, file downloads, serves the built UI |
| `fixer.py` | Rules-based fixer: `plan()` (findings → steps with plain-English why), `fix()`, `score()`, `fixed()` |
| `keys.py` | Key for auto-tune: key-service, with a librosa backup |
| `analysis.py` | Raw-take report from **Phantom** (FadeLab, AGPL, local). Called over MCP stdio before mixing; on Windows it runs inside WSL. Failure never blocks the mix |
| `match.py` | Compares our render with an FL Studio export (per-band tone, loudness, peak) |
| `web/` | React 18 + Vite 6 + Tailwind 4.1 + three.js + Headless UI |
| `samples/*.fst` | Source FL presets (raw vocals are git-ignored) |
| `out/` | Renders and job files (git-ignored) |

## The `.fst` format (what fst_reader.py understands)
`FLhd` header + `FLdt` event stream, the same layout as a `.flp` project. Each event is a 1-byte id followed by:
- **id < 64** → 1 byte · **< 128** → 2 bytes · **< 192** → 4 bytes · **≥ 192** → varint length + bytes

| Event | Meaning |
|---|---|
| 199 | FL version string (UTF-16) |
| 201 | Plugin name (UTF-16): starts a new slot |
| 213 | Plugin state blob: layout is per plugin, see [PRESETS.md](PRESETS.md) |
| 225 | Mixer params: 12-byte records `(u32 0, u32 id, i32 value)`. Per slot `n`: `base + (n<<16)` = enabled, `+1` = slot mix (12800 = 100%). `base + 0xC0` = track volume |

**Before the engine:** `app._run` asks Phantom for a `full_diagnostic` of the raw upload (`analysis.analyze`). The upload is first converted to a lossless float WAV, because Phantom can't decode WhatsApp/m4a/video. The report is stored on the job for the next step (a LangChain agent). It doesn't change the mix yet. Report format (a real example on a clipped file): `docs/phantom-sample.json`. Typical time: ~3 s for a short take, ~11 s for 3 minutes.

## Audio engine pipeline (`engine.process`)
1. **load**: ffmpeg → 44.1 kHz float32 stereo. Any format works, including video.
2. **pre_clean**:
   - remove DC offset, convert to centred mono
   - set the level to **-18 LUFS** (FL-style gain staging, so presets behave the same on quiet and loud recordings)
   - 70 Hz high-pass
   - gentle noise gate
   - de-esser (6 kHz band, gain smoothed over 25 ms)
3. **run_chain**: each enabled slot of the preset, in FL's order, mapped like this:

| FL plugin | Engine function | How |
|---|---|---|
| Fruity Parametric EQ 2 | `peq2` | pedalboard Peak/Shelf/HP/LP filters per active band |
| Fruity Limiter | `limiter` + `brickwall` | own lookahead limiter with a true ceiling (pedalboard's JUCE Limiter adds ~4 dB, so it's unusable here) |
| Soundgoodizer | `soundgoodizer` | 3-band split (200 Hz / 3 kHz), compressor per band, ceiling |
| Fruity Reeverb 2 | `reeverb2` | pedalboard Reverb (size, dry, wet; wet is scaled for each part) |
| Fruity Phaser | `phaser` | pedalboard Phaser; the slot mix comes from the mixer |
| Pitcher | `autotune` | see below |
| Fruity Delay 3 | `delay3` | pedalboard Delay, timed to the beat's BPM (default 140) |

4. **part tweaks** (`ROLE`): Backing and Ad-libs add their own filters, reverb amount, delay, and Haas widening.
5. **mix and master**:
   - **No beat:** master to **-16 LUFS**.
   - **With a beat:** beat at -16 LUFS with a 2 dB dip at 3 kHz to make room for the voice, vocal set relative to it, then mastered to **-14 LUFS**.
   - Either way the ceiling is **-1 dBFS**.

### Auto-tune (`autotune`, `_shift_by_notes`)
1. **Track the pitch:** pYIN on a 22.05 kHz mono copy, one reading every 11.6 ms.
2. **Pick the key:** `detect_key` compares the singer's note histogram with Krumhansl major/minor profiles. Alternatively the user picks a key, or uses the preset's own scale.
3. **Snap:** each voiced frame goes to the nearest note in the key, gliding toward it at the Pitcher speed.
4. **Shift (click-free):** the shift is rounded to 10-cent steps, and runs shorter than 60 ms are merged. Each run gets a **constant** Rubber Band pitch shift with formants preserved, and runs are joined with 20 ms equal-power crossfades.
   - Why: passing a per-sample pitch *array* to `pedalboard.time_stretch` clicks at every 1024-sample chunk, which doubled the clicks. This is the crackle bug that was fixed.

## API
| Method | Path | Body / result |
|---|---|---|
| GET | `/api/sounds` | `{sounds:[{id,role,name,blurb,from,chain[],skipped[],autotune}], parts:[…]}` |
| POST | `/api/jobs` | form: `vocal` (file), `part`, `sound`, `key` (`auto` / `preset` / `"A minor"`), optional `beat` → `{id}` |
| GET | `/api/jobs/{id}` | `status` (running/done/error), `stage`, `slot`, `elapsed`, `key`, `bpm`, `lufs_raw`, `lufs_out`, `peaks_before`, `peaks_after`, `mp3`, `wav`, `raw`, `seconds`, `analysis` (Phantom `full_diagnostic` of the raw take) or `analysis_error` |
| GET | `/api/file/{name}` | download (`{id}.mp3`, `{id}.wav` 24-bit, `{id}_raw.mp3` = Before) |

Jobs live in memory (`JOBS` dict), so they disappear on restart. Files stay in `out/jobs/`.

## Frontend (`web/src`)
| File | What it does |
|---|---|
| `App.jsx` | State machine: setup → processing → result. Job polling, the A/B audio graph, theme |
| `components/Orb.jsx` | three.js orb (simplex-noise shader) that reacts to an `AnalyserNode`, a particle ring, a colour for each plugin stage, and light/dark blending |
| `components/DotWaves.jsx` | Full-screen LED dot-matrix background (one fragment shader, behind the orb at `-z-20`). Red/orange/amber wave ribbons that always move; dots light up around the pointer, and a click or tap sends a ripple. It listens on `window` and stays `pointer-events: none`. It reuses `NOISE` from `Orb.jsx`. Light mode draws faint warm dots |
| `components/Pickers.jsx` | Headless UI dropdowns (`SoundPicker`, `KeyPicker`) and the `PartPicker` segmented control |
| `components/Parts.jsx` | `Dropzone`, `Pipeline` (the live plugin list), `Waveform` (canvas, click to seek) |
| `index.css` | Tailwind 4 `@theme inline` tokens. Colours are CSS variables (`--bg --fg --mist --panel --line --pop`), with dark as the default and `[data-theme=light]` as the override |

**A/B audio graph:**
- Two always-mounted `<audio>` elements (After and Before), each feeding a `GainNode`, both into one `AnalyserNode`, then the speakers.
- Both play in sync; switching just cross-fades the gains (15 ms), so there's no reload.
- "Level-match Before" sets the Before gain to `10^((lufs_out − lufs_raw)/20)`.
- The theme choice (`light` / `dark` / `system`) is stored in `localStorage` under the key `vp-theme`.
