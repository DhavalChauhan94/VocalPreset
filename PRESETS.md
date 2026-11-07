# Presets: adding an FL Studio sound

## Add a new sound (about 5 minutes)
1. In FL Studio, build the vocal chain on **one mixer track**. Then open the track's menu → **File → Save mixer track state as…** to get a `.fst` file.
2. Copy it into `samples/`, then decode it:
   ```bash
   .venv/bin/python fst_reader.py samples/my_preset.fst presets/my_sound.json
   ```
   It prints every plugin with its decoded values. Check that each plugin is recognised (not `unknown`).
3. Register it in `engine.py` → `SOUNDS`:
   ```python
   "my_sound": {"name": "My Sound", "from": "my_preset.fst", "blurb": "Short description"},
   ```
4. Restart the server. The new sound appears in the dropdown, with its plugin chain shown.

**Supported plugins:**
- Fruity Parametric EQ 2
- Fruity Limiter
- Soundgoodizer
- Fruity Reeverb 2
- Fruity Phaser
- Pitcher
- Fruity Delay 3

Any other plugin decodes as `unknown` and is **skipped** by the engine. To support a new one:
1. Write a `decode_<plugin>` function in `fst_reader.py` and add it to `DECODERS`.
2. Write the matching DSP function in `engine.py` and call it from `run_chain`.

## How each plugin's state blob is read
Confidence levels:
- **high**: proven from the data itself, for example the untouched default copy FL stores next to the live values.
- **check**: the scale or order is assumed. Confirm it against the plugin window in FL.

### Fruity Parametric EQ 2 (int32 array, version 8)
| ints | Meaning | Confidence |
|---|---|---|
| `[1..7]` | Band gain, in 0.01 dB (±1800 = ±18 dB) | high |
| `[8..14]` | Band frequency, 0..65535 on a log scale, assumed **20 Hz–20 kHz** | **check** |
| `[15..21]` | Band width, 0..65535. Mapped to octaves as `x/65536·3.6`, so the default of 25412 ≈ 1.4 oct | **check** |
| `[22..28]` | Shape: 0 off, 1 LP, 2 BP, 3 HP, 4 notch, 5 low shelf, 6 peak, 7 high shelf | high (FL's default 5,6,6,6,6,6,7 matches) |
| `[44..64]` | Untouched default copy of the bands | high |

### Fruity Limiter (int32, version 7)
- Levels are linear amplitude ×1000 (1000 = 0 dB).
- `[1..18]` are the live values and `[19..36]` are FL's defaults, so diffing them shows exactly what the user changed.
- `[3]` = ceiling (e.g. 854 → -1.37 dB) · `[9]` = compressor threshold (1000 = off) · `[16]` = gate gain (1000 = off)

### Soundgoodizer (int32 ×3)
`(?, mode 0..3 = A..D, amount 0..1000)`, the same layout as PyFLP. Confidence: high.

### Fruity Reeverb 2 (int32, version 10001)
`high_cut, low_cut, predelay, size(0-100), diffusion, mod, mod_speed, bass_mult, crossover, ?, dry(/128), er(/128), wet(/128), ?, sep`. The order follows the manual. Confidence: **check**.

### Fruity Phaser (int32, version 1)
`sweep, min_depth, max_depth, freq_range, stereo, stages, feedback, dry_wet, out_gain`. Confidence: **check**. The slot mix comes from the mixer (event 225), and that part is high confidence.

### Pitcher (float32 chunk starting `SSLF`)
- floats `[3]` speed, `[4]` amount, `[5]` fine, `[6]` gender. Confidence: **check**.
- **Scale:** 12 on/off bytes (C..B) just before the last 4 bytes. Confidence: high.

### Fruity Delay 3 (int32)
`[5]` time in ticks, read as `ticks/384` beats (192 → an 1/8 note) · `[15]/10000` feedback · `[17]/10000` wet. Confidence: **check**.

## Verifying a decode against FL (recommended)
1. In FL, render a dry vocal through the preset and save it as `fl.wav`.
2. Render the same vocal here: `engine.py vocal.wav lead ours.wav --sound <id>`.
3. Run `python match.py ours.wav fl.wav`. It prints the per-band tonal difference; aim for ≤ 1 dB in every band.
4. Fix the **check** mappings above until the bands match, then mark them high in this file.
