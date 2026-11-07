"""Compare our render with FL Studio's own export of the same vocal through the preset.
Usage: python match.py ours.wav fl_reference.wav   -> per-band tonal difference (dB)."""
import sys
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy.signal import welch

EDGES = [20, 80, 200, 500, 1000, 2500, 5000, 10000, 16000]


def profile(path):
    x, sr = sf.read(path, always_2d=True)
    m = x.mean(1)
    f, P = welch(m, sr, nperseg=8192)
    tot = P[(f >= 20) & (f < 16000)].sum()
    bands = [10 * np.log10(P[(f >= a) & (f < b)].sum() / tot) for a, b in zip(EDGES, EDGES[1:])]
    return bands, pyln.Meter(sr).integrated_loudness(x), 20 * np.log10(np.abs(x).max())


a, b = profile(sys.argv[1]), profile(sys.argv[2])
print(f"{'band Hz':>12} {'ours':>7} {'FL':>7} {'diff':>6}")
worst = 0
for (lo, hi), x, y in zip(zip(EDGES, EDGES[1:]), a[0], b[0]):
    worst = max(worst, abs(x - y))
    print(f"{lo:>5}-{hi:<6} {x:7.1f} {y:7.1f} {x - y:+6.1f}")
print(f"loudness ours {a[1]:.1f} LUFS / FL {b[1]:.1f}   peak {a[2]:.1f} / {b[2]:.1f} dBFS")
print("MATCH" if worst <= 1.0 else f"worst band off by {worst:.1f} dB -> tune engine.py")
