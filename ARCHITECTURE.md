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

**Studio chain (`fixer.py`).** It's driven by measurement: Phantom findings, plus the take's own long-term spectrum compared against `TARGET`. The steps run in this order:

| Step | What it does |
|---|---|
| clean | 85 Hz HPF + stationary spectral denoise (20 dB when Phantom flags noise/SNR, else 10) → -18 LUFS working level |
| hum | scipy notches at the hum frequency and its 2×/3×/4× |
| eq | measures narrow resonances (1/3-oct prominence ≥ 5 dB, 150 Hz–8 kHz) and cuts up to 5 of them. Runs **before** auto-tune, because tuned harmonics look like resonances |
| autotune | `tune.py`: WORLD vocoder, used only below 5 kHz and only on voiced audio; the original air and consonants are kept |
| bright | EQ pass toward TARGET + harmonic exciter (new >5 kHz harmonics from the 2.5 kHz+ band) |
| dynamics | 4:1 (10 ms attack) → 3:1 (15 ms) → look-ahead peak limiter. Faster attacks clicked on tuned pulses |
| sibilance | split-band de-esser: cuts 5.5–11 kHz only when it is unusually loud relative to the voice |
| tone | iterative EQ to TARGET (within 1 dB, max 4 passes). It runs last because compressors reshape the balance |
| gate | 1:4 downward expander for the gaps (compression lifts the noise there) |
| space | plate reverb (30 ms pre-delay) + 1/8 echo on a 400 Hz–9 kHz send |
| master | true-peak limiter (4× oversampled envelope into `engine.brickwall`) → -12 LUFS, ≤ -1.2 dBTP |

- **`TARGET`** (dB vs 1 kHz, loud frames) is `[-8, -5, -2, 0, -2, -5, -9, -14]` across 113 Hz–12.8 kHz. Marked **check**: confirm it against real studio vocals with `match.py`.
- **After-analysis** runs on the vocal mastered **without** reverb, because Phantom reads reverb tails as noise.
- **Filtered from scores and the UI** (`fixer.visible`):
  - inter-sample peaks when the true peak is ≤ -1 dBTP;
  - "resonances" that are ≥ 70% harmonics of the auto-tune key's notes.

**Measured on a real 83 s laptop-mic take (Recording 154):**
- Phantom score 68 → 86 (no auto-tune) / 98 (light)
- 7 kHz band -28.7 → -8.3 dB vs 1 kHz
- gaps -48 → -76 dBFS
- clicks (>6 kHz burst detector) +29 without auto-tune, +48 with heavy
- heavy auto-tune puts 91% of voiced frames within 15 cents (raw 19%)
- processing about 7 s without auto-tune, about 38 s with it (WORLD analysis is most of it)

**Auto-tune options tried on that take:**
- `engine.autotune` (Rubber Band per note chunk): 19 c median off-note, warbly.
- Praat PSOLA: tuned well but added about 350 clicks.
- WORLD full-band: added clicks/buzz at low pitch.
- WORLD below 5 kHz + original above (`tune.py`): about 1 c median off-note, with clicks at the raw take's level.

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
