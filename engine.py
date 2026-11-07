"""Rebuild the decoded FL chain with Spotify's pedalboard and process a vocal.

Usage:
  python engine.py <vocal> <preset: lead|backing|adlib> <out.wav> [--beat beat.mp3]
"""
import argparse
import json
import os
import subprocess
import tempfile

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import librosa
from pedalboard import time_stretch
from pedalboard import (Compressor, Delay, Gain, HighpassFilter, HighShelfFilter,
                        LowpassFilter, LowShelfFilter, NoiseGate, PeakFilter,
                        Pedalboard, Phaser, Reverb)
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, sosfilt

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- io ----------

def load(path):
    """Any format ffmpeg reads (mp3, m4a, WhatsApp .mpeg/.opus, video) -> float32 stereo."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
        tmp = t.name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "2",
                    "-ar", str(SR), "-c:a", "pcm_f32le", tmp], check=True)
    x, _ = sf.read(tmp, dtype="float32", always_2d=True)
    os.unlink(tmp)
    return x.T.copy()                                  # (channels, samples)


def save(x, path):
    sf.write(path, x.T, SR, subtype="PCM_24")


def lufs(x):
    return pyln.Meter(SR).integrated_loudness(x.T.astype(np.float64))


def brickwall(x, ceil_db=-1.0, lookahead_ms=1.5, release_ms=80):
    """True-ceiling lookahead limiter (FL Limiter style), click-free.
    attack: min over +-L then a moving average of L -> every output gain <= the gain each
    sample needs, and the curve is smooth. release: one-pole recovery on a 32x-decimated
    envelope, upsampled linearly. (pedalboard's JUCE Limiter is a maximiser, unusable here.)"""
    c = 10 ** (ceil_db / 20)
    peak = np.abs(x).max(axis=0)
    need = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    L = max(2, int(SR * lookahead_ms / 1000))
    g_att = uniform_filter1d(minimum_filter1d(need, size=2 * L + 1), size=L + 1)
    D = 32
    env = g_att[::D].copy()
    rate = 1 - np.exp(-D / (SR * release_ms / 1000))
    out = np.empty_like(env); cur = 1.0
    for i, v in enumerate(env):                   # 200k steps for a 2.5 min song
        cur = v if v < cur else cur + (v - cur) * rate
        out[i] = cur
    g_rel = np.interp(np.arange(len(need)), np.arange(len(out)) * D, out)
    g = np.minimum(g_att, g_rel)
    return (x * g).astype(np.float32)


class Ceiling:
    def __init__(self, db, release_ms=80):
        self.db, self.rel = db, release_ms

    def __call__(self, x, sr=SR):
        return brickwall(x, self.db, release_ms=self.rel)


def ceiling(db, release_ms=80):
    return Ceiling(db, release_ms)


def to_lufs(x, target):
    cur = lufs(x)
    return x * (10 ** ((target - cur) / 20)) if np.isfinite(cur) else x

# ---------- FL plugin equivalents ----------

def bw_to_q(bw_oct):
    bw = max(bw_oct, 0.05)
    return float(np.sqrt(2 ** bw) / (2 ** bw - 1))


def peq2(params):
    fx = []
    for b in params["bands"]:
        if not b["active"]:
            continue
        f, g, q = min(b["freq_hz"], 20000.0), b["gain_db"], bw_to_q(b["bw_oct"])
        shape = b["shape"]
        if shape == "highpass":
            fx.append(HighpassFilter(cutoff_frequency_hz=f))
        elif shape == "lowpass":
            fx.append(LowpassFilter(cutoff_frequency_hz=f))
        elif shape == "lowshelf":
            fx.append(LowShelfFilter(cutoff_frequency_hz=f, gain_db=g, q=0.707))
        elif shape == "highshelf":
            fx.append(HighShelfFilter(cutoff_frequency_hz=f, gain_db=g, q=0.707))
        elif shape in ("peak", "bandpass", "notch"):
            fx.append(PeakFilter(cutoff_frequency_hz=f, gain_db=g, q=min(q, 30.0)))
    return fx


def limiter(p):
    fx = [Gain(p["input_gain_db"])]
    if p.get("gate_on"):
        fx.append(NoiseGate(threshold_db=-50))
    return fx, ceiling(p["ceiling_db"], 100)


def reeverb2(p, wet_scale=1.0):
    r = p["raw"]
    wet = min(1.0, r["wet"] / 128 * wet_scale)
    return [Reverb(room_size=min(r["size"] / 100, 1.0), damping=0.5,
                   wet_level=wet, dry_level=r["dry"] / 128,
                   width=1.0)]


def three_band(x, lo=200.0, hi=3000.0):
    """Linkwitz-Riley-ish split (2x 2nd-order Butterworth) for multiband compression."""
    s_lo = butter(2, lo, "low", fs=SR, output="sos")
    s_mid_hp = butter(2, lo, "high", fs=SR, output="sos")
    s_mid_lp = butter(2, hi, "low", fs=SR, output="sos")
    s_hi = butter(2, hi, "high", fs=SR, output="sos")
    low = sosfilt(s_lo, sosfilt(s_lo, x))
    mid = sosfilt(s_mid_lp, sosfilt(s_mid_lp, sosfilt(s_mid_hp, sosfilt(s_mid_hp, x))))
    high = sosfilt(s_hi, sosfilt(s_hi, x))
    return low.astype(np.float32), mid.astype(np.float32), high.astype(np.float32)


def soundgoodizer(x, p):
    """Soundgoodizer = fixed Maximus multiband preset. Mode A is the gentlest.
    Amount scales how hard each band is pushed into its compressor."""
    a = p["amount"]
    drive = 12 * a                                     # dB into the compressors
    low, mid, high = three_band(x)
    out = np.zeros_like(x)
    for band, ratio, att, rel in ((low, 3.0, 20, 200), (mid, 2.5, 10, 120),
                                  (high, 2.0, 5, 80)):
        pb = Pedalboard([Gain(drive), Compressor(threshold_db=-12, ratio=ratio,
                                                 attack_ms=att, release_ms=rel)])
        out += pb(band, SR)
    out = ceiling(-0.5, 60)(Pedalboard([Gain(-drive * 0.5)])(out, SR))
    return out


def phaser(p, mix):
    r = p["raw"]
    return Phaser(rate_hz=0.5, depth=0.5, centre_frequency_hz=1300,
                  feedback=min(r["feedback"] / 1000, 0.9), mix=mix)

# ---------- Pitcher (auto-tune) ----------
PC = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A",
                                   "A#", "B"])}


MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key(midi):
    """Krumhansl key profile vs. the singer's own note histogram (duration-weighted)."""
    pcs = np.round(midi[np.isfinite(midi)]).astype(int) % 12
    h = np.bincount(pcs, minlength=12).astype(float)
    best = max(((np.corrcoef(np.roll(prof, k), h)[0, 1], k, mode)
                for prof, mode in ((KS_MAJ, "major"), (KS_MIN, "minor")) for k in range(12)))
    _, root, mode = best
    names = list(PC)
    notes = [names[(root + i) % 12] for i in (MAJOR if mode == "major" else MINOR)]
    return f"{names[root]} {mode}", notes


def autotune(x, p, key="auto"):
    """Track pitch (pYIN), snap each voiced frame to the nearest note of the preset's scale,
    glide toward it at the Pitcher speed, then shift with Rubber Band (formants kept)."""
    sr2, hop = 22050, 256
    mono = librosa.resample(x.mean(axis=0), orig_sr=SR, target_sr=sr2)
    f0, voiced, _ = librosa.pyin(mono, fmin=65, fmax=1050, sr=sr2, frame_length=2048,
                                 hop_length=hop)
    midi = librosa.hz_to_midi(np.where(voiced, f0, np.nan))
    if key == "auto":
        key_name, notes = detect_key(midi)
    elif key == "preset":
        key_name, notes = "preset scale", p["scale_notes"]
    else:                                   # e.g. "A minor"
        root, mode = key.split()
        key_name = key
        notes = [list(PC)[(PC[root] + i) % 12] for i in (MAJOR if mode == "major" else MINOR)]
    autotune.last_key = key_name
    allowed = np.array(sorted(PC[n] for n in notes))
    pc = np.mod(midi, 12)
    # nearest allowed pitch class (wrap-around distance)
    d = (allowed[None, :] - pc[:, None] + 6) % 12 - 6
    shift = np.take_along_axis(d, np.nanargmin(np.abs(np.nan_to_num(d, nan=99)), axis=1)[:, None], 1)[:, 0]
    shift = np.where(np.isfinite(shift), shift, 0.0) * p.get("amount", 1.0)
    # glide: speed 0 = instant (robotic), higher = slower/natural. 0.31 -> ~40 ms
    tau = max(0.005, p.get("speed", 0.3) * 0.13)
    a = np.exp(-(hop / sr2) / tau)
    sm = np.zeros_like(shift)
    for i in range(1, len(shift)):
        sm[i] = a * sm[i - 1] + (1 - a) * shift[i]
    t_frames = np.arange(len(sm)) * hop / sr2
    per_sample = np.interp(np.arange(x.shape[1]) / SR, t_frames, sm)
    return _shift_by_notes(x, per_sample)


def _shift_by_notes(x, cents_curve_semis, step=0.1, min_run_s=0.06, pad_s=0.12, xf_s=0.02):
    """Rubber Band clicks when its pitch changes inside one call (it works in 1024-sample
    chunks). So: quantise the correction to 10-cent steps, merge tiny runs, shift each run
    with a CONSTANT amount (clean), and stitch runs with 20 ms equal-power crossfades."""
    n = x.shape[1]
    hop = 512
    q = np.round(cents_curve_semis[::hop] / step) * step
    # runs of equal quantised shift
    edges = np.flatnonzero(np.diff(q)) + 1
    starts = np.r_[0, edges]; ends = np.r_[edges, len(q)]
    runs = [[s_, e_, q[s_]] for s_, e_ in zip(starts, ends)]
    min_run = max(1, int(min_run_s * SR / hop))
    merged = []
    for r in runs:                     # fold short runs into the previous one
        if merged and (r[1] - r[0] < min_run or abs(r[2] - merged[-1][2]) < 1e-9):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    mono = x.mean(axis=0).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    wsum = np.zeros(n, dtype=np.float32)
    pad, xf = int(pad_s * SR), int(xf_s * SR)
    for s_, e_, shift in merged:
        a, b = s_ * hop, min(n, e_ * hop)
        lo, hi = max(0, a - pad), min(n, b + pad)
        seg = mono[lo:hi]
        if abs(shift) > 1e-6:
            seg = time_stretch(seg[None, :], SR, 1.0, float(shift), preserve_formants=True,
                               transient_mode="smooth")[0, : hi - lo]
            if len(seg) < hi - lo:
                seg = np.pad(seg, (0, hi - lo - len(seg)))
        # window: 1 inside [a,b], sine ramps of xf across each boundary
        w = np.zeros(hi - lo, dtype=np.float32)
        i0, i1 = max(0, a - lo - xf // 2), min(hi - lo, b - lo + xf // 2)
        w[i0:i1] = 1.0
        ramp = np.sin(np.linspace(0, np.pi / 2, xf, dtype=np.float32)) ** 2
        if a > 0:
            k = min(xf, i1 - i0); w[i0:i0 + k] = ramp[:k]
        if b < n:
            k = min(xf, i1 - i0); w[i1 - k:i1] = np.minimum(w[i1 - k:i1], ramp[::-1][-k:])
        out[lo:hi] += seg * w
        wsum[lo:hi] += w
    out = out / np.maximum(wsum, 1e-3)
    return np.repeat(out[None, :], 2, axis=0)


def delay3(p, bpm):
    beats = p["time_ticks"] / 384          # CHECK: 192 ticks read as an 1/8 note
    return Delay(delay_seconds=float(np.clip(60 / bpm * beats, 0.05, 2.0)),
                 feedback=min(p["feedback"], 0.8), mix=min(p["wet"], 1.0))


# ---------- cleanup FL can't do for the user ----------

def deess(x, freq=6000, thresh_db=-28, max_cut_db=8):
    hp = butter(2, freq, "high", fs=SR, output="sos")
    sib = sosfilt(hp, x)
    env = np.abs(sib).max(axis=0)
    win = int(SR * 0.005)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    env_db = 20 * np.log10(env + 1e-9)
    cut_db = np.clip(env_db - thresh_db, 0, max_cut_db)
    cut_db = uniform_filter1d(minimum_filter1d(-cut_db, int(SR * 0.004)) * -1, int(SR * 0.025))
    g = 10 ** (-cut_db / 20)
    return (x - sib + sib * g).astype(np.float32)


def pre_clean(x):
    x = x - x.mean(axis=1, keepdims=True)              # DC
    x = np.repeat(x.mean(axis=0, keepdims=True), 2, axis=0)  # dry vocal -> centered mono
    x = to_lufs(x, -18.0)                              # FL-style gain staging
    x = Pedalboard([HighpassFilter(70), NoiseGate(threshold_db=-55, ratio=2,
                                                  attack_ms=5, release_ms=220)])(x, SR)
    return deess(x)

# ---------- chain ----------

ROLE = {   # per-role tweaks layered on top of the decoded FL chain
    "lead":    {"wet": 1.0, "extra": [], "level_db": 0.0, "width": 0.0},
    "backing": {"wet": 1.8, "extra": [HighpassFilter(250), PeakFilter(3000, -3, 0.8),
                                      HighShelfFilter(9000, -2)], "level_db": -7.0,
                "width": 0.012},
    "adlib":   {"wet": 1.5, "extra": [HighpassFilter(300), PeakFilter(4500, 3, 0.7),
                                      Delay(delay_seconds=0.25, feedback=0.25, mix=0.18)],
                "level_db": -5.0, "width": 0.008},
}


def widen(x, ms):
    """Haas widening for backing/adlibs: delay one side a few ms."""
    if ms <= 0:
        return x
    d = int(SR * ms)
    y = x.copy()
    y[1, d:] = x[1, :-d]
    return y


def _noop(*a, **k):
    pass


def run_chain(x, preset, role="lead", bpm=140.0, key="auto", progress=_noop):
    r = ROLE[role]
    for slot in preset["chain"]:
        if not slot["enabled"]:
            continue
        progress("plugin", slot=slot["slot"], plugin=slot["plugin"])
        t, p = slot["type"], slot["params"]
        dry = x
        if t == "limiter":
            fx, lim = limiter(p)
            x = lim(Pedalboard(fx)(x, SR))
        elif t == "reeverb2":
            x = Pedalboard(reeverb2(p, r["wet"]))(x, SR)
        elif t == "soundgoodizer":
            x = soundgoodizer(x, p)
        elif t == "peq2":
            x = Pedalboard(peq2(p))(x, SR)
        elif t == "phaser":
            x = Pedalboard([phaser(p, 1.0)])(x, SR)
        elif t == "pitcher":
            x = autotune(x, p, key)
        elif t == "delay3":
            x = Pedalboard([delay3(p, bpm)])(x, SR)
        if slot["mix"] < 0.999:                       # FL mixer-slot mix knob
            x = dry * (1 - slot["mix"]) + x * slot["mix"]
    if r["extra"]:
        x = Pedalboard(r["extra"])(x, SR)
    return widen(x, r["width"])


def master(x, target_lufs):
    x = to_lufs(x, target_lufs)
    for _ in range(3):                                # limiting lowers LUFS; re-aim
        y = ceiling(-1.0)(x)
        miss = target_lufs - lufs(y)
        if abs(miss) < 0.2:
            break
        x = x * 10 ** (miss / 20)
    return y


SOUNDS = {   # display info for each decoded FL preset in presets/
    "studio_air": {"name": "Studio Air", "from": "untitled2.fst",
                   "blurb": "Clean, bright, roomy"},
    "no_fall": {"name": "No Fall", "from": "nofalltypeshi.fst",
                "blurb": "Auto-tuned, echo, wet"},
}


def load_sound(sound):
    if sound not in SOUNDS:
        raise ValueError(f"unknown sound {sound}")
    return json.load(open(os.path.join(HERE, "presets", f"{sound}.json")))


def process(vocal_path, role, out_path, beat_path=None, sound="studio_air", key="auto",
            progress=_noop):
    preset = load_sound(sound)
    beat, bpm = None, 140.0
    progress("stage", name="Reading audio")
    if beat_path:
        progress("stage", name="Finding the beat's tempo")
        beat = load(beat_path)
        tempo, _ = librosa.beat.beat_track(y=beat.mean(axis=0), sr=SR)
        bpm = float(np.atleast_1d(tempo)[0]) or 140.0
    autotune.last_key = None
    progress("stage", name="Cleaning: gain, gate, de-ess")
    raw = load(vocal_path)
    progress("meta", lufs_raw=round(float(lufs(raw)), 2), bpm=round(bpm, 1) if beat_path else None)
    v = run_chain(pre_clean(raw), preset, role, bpm, key, progress)
    progress("meta", key=autotune.last_key)
    progress("stage", name="Mixing & mastering" if beat is not None else "Mastering")
    v = v * preset.get("track", {}).get("volume", 1.0)   # FL mixer fader
    if beat is None:
        save(master(v, -16.0), out_path)
        return out_path
    beat = to_lufs(beat, -16.0)
    beat = Pedalboard([PeakFilter(3000, -2.0, 1.0)])(beat, SR)   # room for the voice
    v = to_lufs(v, -16.5 + ROLE[role]["level_db"])
    n = max(beat.shape[1], v.shape[1])
    mix = np.zeros((2, n), dtype=np.float32)
    mix[:, :beat.shape[1]] += beat
    mix[:, :v.shape[1]] += v
    save(master(mix, -14.0), out_path)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("vocal"); ap.add_argument("role", choices=list(ROLE))
    ap.add_argument("out"); ap.add_argument("--beat"); ap.add_argument("--sound", default="studio_air")
    a = ap.parse_args()
    process(a.vocal, a.role, a.out, a.beat, a.sound)
    y, _ = sf.read(a.out, always_2d=True)
    print(f"{a.out}: {y.shape[0]/SR:.1f}s  {lufs(y.T):.1f} LUFS  peak {20*np.log10(np.abs(y).max()):.1f} dBFS")
