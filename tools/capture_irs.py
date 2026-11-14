"""Regenerate ir/{room,plate,hall}.wav: the impulse responses of Dragonfly Reverb (GPL-3, michaelwillis.github.io/
dragonfly-reverb), which beat our synthetic reverb in the owner's blind A/B (2026-11-13). Captured once so the server
render and the browser's ConvolverNode play the identical reverb, with no plugin needed at runtime. Plate is exact;
Room/Hall freeze Dragonfly's slow tail modulation (within 1 dB per band above 160 Hz).

    python tools/capture_irs.py "<folder with Dragonfly{Room,Plate,Hall}Reverb.vst3>"
"""
import os
import sys

import numpy as np
import pedalboard as pb
import soundfile as sf

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ir")
# Dragonfly settings used in the blind test: wet only (fixer.space adds the dry voice and sets the level)
REV = {"room": ("Room", dict(dry_level=0.0, early_level=30.0, late_level=100.0, size_m=10.0, decay_s=0.7, predelay_ms=8.0)),
       "plate": ("Plate", dict(dry_level=0.0, wet_level=100.0, decay_s=1.8, predelay_ms=25.0, low_cut_hz=200.0, high_cut_hz=12000.0)),
       "hall": ("Hall", dict(dry_level=0.0, early_level=20.0, late_level=100.0, size_m=30.0, decay_s=2.6, predelay_ms=35.0, high_cut_hz=7600.0))}

# Trim to the level the owner heard in the blind test (Dragonfly's wet was RMS-matched to our old synthetic reverb on
# real vocals); unit energy alone came out this much too loud. Measured on takes 154 and 261.
LEVEL_DB = {"room": -0.3, "plate": -2.2, "hall": -1.55}


def plugin_path(folder, kind):
    bundle = os.path.join(folder, f"Dragonfly{kind}Reverb.vst3")
    inner = os.path.join(bundle, "Contents", "x86_64-win", f"Dragonfly{kind}Reverb.vst3")   # Windows loads the inner DLL
    return inner if os.path.isfile(inner) else bundle


def capture(folder, style):
    kind, settings = REV[style]
    p = pb.load_plugin(plugin_path(folder, kind))
    for k, v in settings.items():
        setattr(p, k, v)
    imp = np.zeros((2, 8 * SR), np.float32)
    imp[:, 0] = 1.0                                           # a centred source: the send is the (near-mono) voice
    ir = p(imp, SR).astype(np.float64)
    env = np.abs(ir).max(0)
    n = int(np.nonzero(env > env.max() * 10 ** (-90 / 20))[0][-1]) + 1   # trim the tail below -90 dB
    ir = ir[:, :n] * np.r_[np.ones(n - 441), np.linspace(1, 0, 441)]       # 10 ms fade: no click at the cut
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))      # unit energy per channel, like the old synthetic IRs
    return (ir * 10 ** (LEVEL_DB[style] / 20)).astype(np.float32)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for style in REV:
        ir = capture(sys.argv[1], style)
        sf.write(os.path.join(OUT, f"{style}.wav"), ir.T, SR, subtype="FLOAT")
        print(f"{style}: {ir.shape[1] / SR:.2f} s")
