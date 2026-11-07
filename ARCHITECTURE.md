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

 Offline:  FL Studio .fst ──► fst_reader.py ──► presets/<sound>.json  (read by engine.load_sound)
```

## Files
| Path | Role |
|---|---|
| `fst_reader.py` | Decodes an FL mixer-track preset (`.fst`) into a JSON plugin chain |
| `presets/*.json` | Decoded presets: one file per "sound" (`studio_air`, `no_fall`) |
| `engine.py` | All DSP: loading, cleanup, each FL plugin's equivalent, auto-tune, mixing, mastering |
| `app.py` | FastAPI: job API, file downloads, serves the built UI |
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
| GET | `/api/sounds` | `{sounds:[{id,name,blurb,from,chain[],autotune}], parts:[…]}` |
| POST | `/api/jobs` | form: `vocal` (file), `part`, `sound`, `key` (`auto` / `preset` / `"A minor"`), optional `beat` → `{id}` |
| GET | `/api/jobs/{id}` | `status` (running/done/error), `stage`, `slot`, `elapsed`, `key`, `bpm`, `lufs_raw`, `lufs_out`, `peaks_before`, `peaks_after`, `mp3`, `wav`, `raw`, `seconds` |
| GET | `/api/file/{name}` | download (`{id}.mp3`, `{id}.wav` 24-bit, `{id}_raw.mp3` = Before) |

Jobs live in memory (`JOBS` dict), so they disappear on restart. Files stay in `out/jobs/`.

## Frontend (`web/src`)
| File | What it does |
|---|---|
| `App.jsx` | State machine: setup → processing → result. Job polling, the A/B audio graph, theme |
| `components/Orb.jsx` | three.js orb (simplex-noise shader) that reacts to an `AnalyserNode`, a particle ring, a colour for each plugin stage, and light/dark blending |
| `components/Pickers.jsx` | Headless UI dropdowns (`SoundPicker`, `KeyPicker`) and the `PartPicker` segmented control |
| `components/Parts.jsx` | `Dropzone`, `Pipeline` (the live plugin list), `Waveform` (canvas, click to seek) |
| `index.css` | Tailwind 4 `@theme inline` tokens. Colours are CSS variables (`--bg --fg --mist --panel --line --pop`), with dark as the default and `[data-theme=light]` as the override |

**A/B audio graph:**
- Two always-mounted `<audio>` elements (After and Before), each feeding a `GainNode`, both into one `AnalyserNode`, then the speakers.
- Both play in sync; switching just cross-fades the gains (15 ms), so there's no reload.
- "Level-match Before" sets the Before gain to `10^((lufs_out − lufs_raw)/20)`.
- The theme choice (`light` / `dark` / `system`) is stored in `localStorage` under the key `vp-theme`.
