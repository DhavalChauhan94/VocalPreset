"""Auto-tune for the fix flow: WORLD vocoder pitch correction, band-split with the original take.

Why WORLD and not the alternatives (measured on a real 83 s take, see HANDOVER/ARCHITECTURE):
- engine.autotune (Rubber Band per note chunk) barely tuned (median 19 cents off) and warbled.
- Praat PSOLA tuned well but added ~350 audible clicks.
- WORLD tunes to ~1 cent. It is used only below 5 kHz and only on voiced audio; consonants and the
  original air above 5 kHz stay untouched, which brings new clicks down to the raw take's level.
"""
import numpy as np
import pyworld as pw
from scipy.ndimage import binary_dilation, uniform_filter1d
from scipy.signal import butter, sosfiltfilt

import engine

SR = engine.SR
FRAME_MS = 5.0
SPLIT_HZ = 5000.0
# amount: how far toward the note (1 = all the way). retune_ms: glide time (0 = instant, robotic).
LEVELS = {"light": {"amount": 0.8, "retune_ms": 120.0},
          "medium": {"amount": 1.0, "retune_ms": 35.0},
          "heavy": {"amount": 1.0, "retune_ms": 0.0}}


def scale_pcs(key):
    root, mode = key.split()
    return {(engine.PC[root] + i) % 12 for i in (engine.MAJOR if mode == "major" else engine.MINOR)}


def target_f0(f0, pcs, amount, retune_ms):
    """Snap each voiced frame toward the nearest scale note. Hysteresis keeps a note until the
    singer is clearly nearer another one (no flip-flopping between two notes). The correction,
    not the pitch, is smoothed, so vibrato survives on slower settings."""
    out, prev, c = f0.copy(), None, None
    k = 1 - np.exp(-FRAME_MS / retune_ms) if retune_ms > 0 else 1.0
    for i, f in enumerate(f0):
        if f <= 0:                                   # unvoiced: reset, so the next phrase starts clean
            prev = c = None
            continue
        m = 69 + 12 * np.log2(f / 440)
        if prev is None or abs(m - prev) >= 0.75:
            prev = min((n for n in range(int(m) - 2, int(m) + 3) if n % 12 in pcs), key=lambda n: abs(n - m))
        want = (prev - m) * amount
        c = want if c is None else c + (want - c) * k
        out[i] = 440 * 2 ** ((m + c - 69) / 12)
    return out


def autotune(x, level, key="auto"):
    """x: (channels, samples) float32. Returns the same shape. Sets autotune.last_key."""
    mono = x.mean(axis=0).astype(np.float64)
    f0, t = pw.harvest(mono, SR, f0_floor=60.0, f0_ceil=700.0, frame_period=FRAME_MS)
    if not key or key == "auto":
        key, _ = engine.detect_key(np.where(f0 > 0, 69 + 12 * np.log2(np.maximum(f0, 1e-9) / 440), np.nan))
    autotune.last_key = key
    sp = pw.cheaptrick(mono, f0, t, SR)
    ap = pw.d4c(mono, f0, t, SR)
    p = LEVELS[level]
    tuned = pw.synthesize(target_f0(f0, scale_pcs(key), p["amount"], p["retune_ms"]), sp, ap, SR, FRAME_MS)[: len(mono)]
    tuned = np.pad(tuned, (0, len(mono) - len(tuned)))
    lo = butter(4, SPLIT_HZ, "low", fs=SR, output="sos")
    hi = butter(4, SPLIT_HZ, "high", fs=SR, output="sos")
    tuned = sosfiltfilt(lo, tuned) + sosfiltfilt(hi, mono)          # tuned body, original air
    voiced = binary_dilation(f0 > 0, iterations=3)
    mask = np.repeat(voiced.astype(float), int(SR * FRAME_MS / 1000))[: len(mono)]
    mask = uniform_filter1d(np.pad(mask, (0, len(mono) - len(mask)), mode="edge"), int(SR * 0.012))
    y = mask * tuned + (1 - mask) * mono                              # consonants/breaths stay original
    return np.repeat(y[None].astype(np.float32), x.shape[0], axis=0)


autotune.last_key = None
