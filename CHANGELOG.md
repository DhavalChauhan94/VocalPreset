# Changelog

The newest entries come first. Each entry lists what changed for users, then what changed under the hood.

## 2026-11-12: Merged into `main`
- **All the work from the `ui-redesign` → `phantom-analysis` → `vocal-fixer` branches is now in `main`.**
- **Faster first load:** three.js, which draws the backdrop, now loads after the page appears. The page's own JavaScript went from 763 kB to 284 kB (95 kB gzipped).
- **No more disk build-up:** renders and uploaded copies left over from earlier runs are deleted when the server starts, because nothing can reach them after a restart. Before this, `out/` had grown to 1.8 GB in three days.
- **Clean-up:** removed dead code (`fixer.target_curve`, an unused UI component and unused imports). Rewrote README and HANDOVER, and added this changelog.

## 2026-11-11: Three vocal sounds and downloads that share anywhere
- **Pick your sound**, shown first after upload: **Rap**, **Melodic rap** and **Singer / Pop**.
  - Each card is animated: punchy bars, echo trails, a smooth line with sparkle.
  - Each sound sets its own compression, gate, tone target, saturation, reverb, echo, width and wobble.
  - Each sets an auto-tune default: Rap off, Melodic Heavy, Pop Medium.
  - The numbers come from engineers' own accounts (Sound On Sound *Inside Track*, Antares). The sources are listed in ARCHITECTURE.md.
- **Measured on two real takes** (Recording 154 and 261), at -12 LUFS with true peaks safe:

  | Take | Rap | Melodic | Pop |
  |---|---|---|---|
  | 154 | 68 → 98 | 68 → 98 | 68 → 98 |
  | 261 | 67 → 88 | 67 → 100 | 67 → 100 |

  Rap is the driest and densest, melodic the wettest and widest.
- **Mix rack:** new **Repeats** (echo feedback) and **Wobble** (chorus-style movement on the double) knobs. **Mix starts at 40%**, the amount that sounded best on first listen.
- **Downloads:**
  - WAV is now 16-bit / 44.1 kHz with dither, the universal format. It was 24-bit.
  - MP3 now has ID3v2.3 tags and a title.
  - Files are named after the upload, e.g. `Recording (154) - Rap mix.mp3`.
  - A new **Share MP3** button uses the phone or desktop share sheet.
  - The page explains that WhatsApp caps audio at 16 MB, so a long WAV goes as a Document.
- **Under the hood:** `POST /api/takes/{id}/fix` now takes `style`, and `/mix` accepts `feedback` and `mod`. Job JSON no longer includes the beat's server path. New tests: `tests/test_downloads.py` and style tests.

## 2026-11-10: Analyse → auto-tune → fix
- **New flow, replacing preset picking:** analyse with Phantom → animated plain-English report → optional auto-tune (Light / Medium / Heavy) with key detection → **Fix my vocal**. The presets stay in the code for the future artist dashboard.
- **Studio chain (`fixer.py`):** denoise, hum notches, measured resonance cuts, then polish (EQ to a vocal target, exciter, two compressors plus parallel compression, de-essing, saturation, gap gate), then space (doubler, convolution reverb and ping-pong echo, both ducked under the voice). It ends with a true-peak master.
- **Auto-tune (`tune.py`):** the WORLD vocoder below 5 kHz on voiced frames, which removed the glitches.
- **Key detection (`keys.py`):** reads held sung notes and can use the beat. It is honest when two keys fit equally well.
- **Live mix rack:** real knobs, and every change is instant because the mix runs in the browser (`mixEngine.js`).
- **Security:**
  - uploads are never served, and download names are strict;
  - every ffmpeg decode is whitelisted and capped;
  - request size is limited.
- Windows one-click start (`start.bat`), `SETUP.md`, and the key-service now lives in the repo.

## 2026-11-09: UI redesign
- Animated LED dot-wave background, a chrome headline ("Bedroom take. Studio finish.") and a hardware-style faceplate panel.
- Light mode is now white and sky blue.
- 12 FL vocal presets were added, sorted into lead, backing and ad-libs.

## 2026-11-07: First version
- FL Studio `.fst` mixer presets were rebuilt in Python (pedalboard), with a React web app.
