"""Studio vocal chain driven by measurement: Phantom findings + the take's own spectrum -> fix steps.

plan()  pure: report -> ordered steps (plain-English label + why for the UI).
fix()   applies them. Tone is matched to TARGET by measuring the take, not by fixed EQ moves.
score() 0-100 "studio readiness" from a Phantom report.

Chain order (dynamics before the final tone match, since compressors reshape the balance):
PREP (always full, cached per take): clean (HPF + spectral denoise) -> hum notches -> resonance cuts -> auto-tune.
POLISH (scaled by the Mix amount): rough tone + gentle exciter -> serial + parallel compression + peak control
-> dynamic harshness/de-ess -> tape saturation + final tone match -> gap expander.
SPACE: doubler + ducked convolution reverb + ducked ping-pong delay -> true-peak master.
Tuned on a real 83 s laptop-mic take: score 61 -> 84, 7 kHz -28.7 -> -8.8 dB vs 1 kHz, gaps
-48 -> -69 dBFS, -12 LUFS at -1.2 dBTP. TARGET is a first reference curve ("check"): confirm it
against real studio vocals with match.py before treating it as final.
"""
import numpy as np
import librosa
from pedalboard import Compressor, Delay, HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard
from scipy.ndimage import uniform_filter, uniform_filter1d
from scipy.signal import butter, fftconvolve, iirnotch, resample_poly, sosfilt, sosfiltfilt, tf2sos

import engine
import tune

SR = engine.SR
TARGET_LUFS = -12.0
CEILING_DBTP = -1.2
AUTOTUNE = tune.LEVELS
# Long-term spectrum of a produced lead vocal, dB vs the 1 kHz band, loud frames only ("check").
# v1 was [-8,-5,-2,0,-2,-5,-9,-14]: measured right but sounded thin and over-bright ("laptop mix"), so v2 keeps
# the body (113/226 Hz) and sits the top 4-5 dB lower, like released vocals; Brightness/Warmth tilt it per user.
BANDS = [(80, 160), (160, 320), (320, 640), (640, 1280), (1280, 2560), (2560, 5120), (5120, 10240), (10240, 16000)]
CENTERS = [113, 226, 453, 905, 1810, 3620, 7240, 12800]
TARGET = [-4.0, -5.5, -5.0, 0.0, -4.0, -9.0, -14.0, -19.0]
_PENALTY = {"dealbreaker": 30, "significant": 12, "moderate": 6, "minor": 2}
# Damage baked into the recording: re-analysis stops flagging it once peaks are limited, but it is still audible.
UNFIXABLE = {"clipping", "lossy_codec"}


# ---------- report helpers ----------

def _problems(report):
    """Phantom problems by type. Inter-sample peaks only count when the true peak is actually unsafe
    (above -1 dBTP); Phantom also flags small, harmless overshoots."""
    rep = report or {}
    tp = rep.get("loudness", {}).get("true_peak_dbtp")
    out = {}
    for p in (rep.get("problems") or {}).get("problems", []):
        if p["type"] == "inter_sample_peak" and tp is not None and tp <= -1.0:
            continue
        if p["type"] == "hum" and p.get("details", {}).get("primary_salience", 1.0) < 0.1:
            continue   # Phantom's own confidence says it's noise-level, not mains hum
        out[p["type"]] = p
    return out


def _step(id_, label, why, fixes=(), **params):
    return {"id": id_, "label": label, "why": why, "fixes": list(fixes), "params": params}


def plan(report, autotune="off", key=None):
    pr = _problems(report)
    noisy = "noise_floor" in pr or "snr" in pr
    s = [_step("clean", "Clean up the recording",
               "Cuts rumble and removes the steady background hiss under your voice." if noisy
               else "Cuts rumble below the voice and sets a healthy working level.",
               ("dc_offset", "noise_floor", "snr"), denoise_db=20.0 if noisy else 10.0)]
    if "hum" in pr:
        d = pr["hum"].get("details", {})
        base = d.get("primary_frequency_hz") or 50.0
        # mains hum always brings harmonics (2x, 3x, 4x), even when only the fundamental is reported
        freqs = sorted({round(f, 1) for f in [*(d.get("frequencies_hz") or []), *(base * k for k in (1, 2, 3, 4))]
                        if f < 1000})
        s.append(_step("hum", "Remove electrical hum",
                       f"A steady {base:.0f} Hz buzz was found; we cut it and its echoes very narrowly.",
                       ("hum",), freqs=freqs))
    n_res = len(pr.get("resonant_peak", {}).get("details", {}).get("resonances", []))
    s.append(_step("eq", "Tame ringing and boxy spots",
                   f"{n_res} narrow ringing tone(s) were found; we measure them and cut each one."
                   if n_res else "We measure narrow ringing tones in your voice and cut any that stick out.",
                   ("resonant_peak",)))
    # after the resonance cuts: a tuned voice holds steady notes whose harmonics look like resonances
    if autotune in AUTOTUNE:
        s.append(_step("autotune", f"Auto-tune ({autotune})",
                       f"Pulls each note onto the nearest note of {key or 'the detected key'}, smoothly.",
                       (), level=autotune, key=key or "auto"))
    s.append(_step("bright", "Clarity and smooth air",
                   "Opens up the top of your voice with smooth, silky air instead of harsh fizz."))
    s.append(_step("dynamics", "Thick, up-front vocal",
                   "Two compressors plus a parallel 'New York' blend: every word sits forward, full and never squashed."))
    s.append(_step("sibilance", "Tame harshness and S sounds",
                   "Harsh upper-mids and sharp 'S'/'T' sounds are turned down only at the moments they stab out.",
                   ("sibilance", "harshness")))
    s.append(_step("tone", "Warmth and studio balance",
                   "Adds tape-style warmth, then shapes your voice to a pro vocal's balance: full body, clear mids, smooth top.",
                   ("mud",)))
    s.append(_step("gate", "Silence the gaps", "Turns down background noise between phrases.", ("noise_floor", "snr")))
    if "clipping" in pr or "lossy_codec" in pr:
        s.append(_step("note", "Damage we can't fully undo",
                       "Distorted (clipped) or heavily compressed audio has lost detail for good. "
                       "We'll smooth it, but re-recording gives the best result.", ("clipping", "lossy_codec")))
    s.append(_step("space", "Studio space",
                   "A smooth plate reverb and ping-pong echo that duck while you sing and bloom in the gaps, plus a subtle double for width."))
    s.append(_step("master", "Loud and streaming-safe",
                   f"Masters to {TARGET_LUFS:.0f} LUFS with true peaks under {CEILING_DBTP} dB: loud, and never crackles.",
                   ("inter_sample_peak",)))
    return s


# ---------- user settings (the "Shape your mix" panel) ----------
# mix scales everything (0 = your cleaned, tuned voice only; 1 = full studio chain). The rest are 0..1
# except brightness/warmth (-1..1, 0 = our balance). Defaults are the one-click result.
DEFAULTS = {"mix": 1.0, "reverb": 0.35, "reverb_style": "plate", "delay": 0.2, "delay_style": "eighth",
            "width": 0.45, "brightness": 0.0, "warmth": 0.0}
POLISH_AT = {"mix": 1.0, "brightness": 0.0, "warmth": 0.3}   # how the polished stem is always made
REVERB_STYLES = {"room": (0.7, 0.008), "plate": (1.8, 0.025), "hall": (2.9, 0.04)}   # RT60 s, pre-delay s
DELAY_STYLES = {"slap": 0.11, "eighth": 0.214, "quarter": 0.428}                     # seconds (1/8, 1/4 at ~140 bpm)


def settings(raw=None):
    """Validated settings: unknown keys dropped, numbers clamped, styles checked."""
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k not in DEFAULTS or v is None:
            continue
        if k == "reverb_style":
            s[k] = v if v in REVERB_STYLES else s[k]
        elif k == "delay_style":
            s[k] = v if v in DELAY_STYLES else s[k]
        else:
            lo = -1.0 if k in ("brightness", "warmth") else 0.0
            s[k] = float(min(1.0, max(lo, float(v))))
    return s


# ---------- DSP (mono float32 arrays unless noted) ----------

def _pb(fx, y):
    return Pedalboard(fx)(y[None], SR)[0] if fx else y


_RUMBLE = butter(4, 75, "high", fs=SR, output="sos")   # 24 dB/oct: keeps the chest, kills room rumble/mains


def derumble(y):
    return sosfilt(_RUMBLE, y).astype(np.float32)


def _loud_frames(y, n):
    fr = y[: len(y) // n * n].reshape(-1, n)
    e = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    return fr[e > np.percentile(e, 55)]


def band_spectrum(y):
    n = 4096
    P = (np.abs(np.fft.rfft(_loud_frames(y, n) * np.hanning(n), axis=1)) ** 2).mean(0)
    f = np.fft.rfftfreq(n, 1 / SR)
    b = np.array([10 * np.log10(P[(f >= lo) & (f < hi)].mean() + 1e-20) for lo, hi in BANDS])
    return b - b[3]


def target_curve(brightness=0.0, warmth=0.0):
    """TARGET tilted by the user's Brightness (top bands, up to +-6 dB) and Warmth (body, up to +-3 dB)."""
    t = np.array(TARGET)
    t += brightness * 6.0 * np.array([0, 0, 0, 0, 0.2, 0.45, 0.75, 1.0])
    t += warmth * 3.0 * np.array([0.8, 1.0, 0.6, 0, 0, 0, -0.2, -0.3])
    return t


def denoise(y, reduce_db):
    """Stationary spectral gate: noise print from the quietest 15% of frames, soft mask smoothed over
    frequency and time so it doesn't leave 'musical noise'."""
    D = librosa.stft(y, n_fft=2048, hop_length=512)
    mag = np.abs(D)
    fe = mag.mean(0)
    noise = np.median(mag[:, fe <= np.percentile(fe, 15)], axis=1, keepdims=True)
    g = uniform_filter(np.clip(1 - 1.6 * noise / (mag + 1e-12), 10 ** (-reduce_db / 20), 1), size=(3, 5))
    return librosa.istft(D * g, hop_length=512, length=len(y)).astype(np.float32)


def find_resonances(y, max_n=5, min_prom=5.0):
    """Narrow peaks above a 1/3-octave-smoothed long-term spectrum, 150 Hz-8 kHz -> (freq, cut dB, Q)."""
    n = 8192
    loud = _loud_frames(y, n)
    if not len(loud):
        return []
    L = 10 * np.log10((np.abs(np.fft.rfft(loud * np.hanning(n), axis=1)) ** 2).mean(0) + 1e-20)
    f = np.fft.rfftfreq(n, 1 / SR)
    lf = np.log2(np.maximum(f, 1))
    prom = L - np.array([L[(lf > a - 1 / 6) & (lf < a + 1 / 6)].mean() for a in lf])
    out = []
    for i in np.argsort(-prom):
        if prom[i] < min_prom:
            break
        if 150 < f[i] < 8000 and not any(abs(np.log2(f[i] / g)) < 0.15 for g, _, _ in out):
            out.append((float(f[i]), -float(min(8.0, prom[i] - 2)), 8.0))
            if len(out) == max_n:
                break
    return out


def eq_pass(y, scale=0.8, target=None):
    t = np.array(TARGET if target is None else target)
    diff = np.clip(t - band_spectrum(y), -8, 10)
    fx = [PeakFilter(c, float(d) * scale, 0.9) for c, d in zip(CENTERS[:-1], diff[:-1]) if abs(d * scale) > 0.5]
    if abs(diff[-1] * scale) > 0.5:
        fx.append(HighShelfFilter(10000, float(diff[-1]) * scale, 0.7))
    return _pb(fx, y)


def match_tone(y, target=None, tol=1.0, passes=6):
    t = np.array(TARGET if target is None else target)
    for _ in range(passes):
        if np.abs(np.clip(t - band_spectrum(y), -8, 10)).max() < tol:
            break
        y = eq_pass(y, 0.9, t)
    return y


def exciter(y, amount=0.12):
    """Gentle even-harmonic air: saturate the 3 kHz+ band asymmetrically, keep only new >7 kHz content.
    (The old 0.3 / 5 kHz setting measured fine but sounded fizzy.)"""
    band = sosfilt(butter(2, 3000, "high", fs=SR, output="sos"), y)
    d = 2.0 / (np.abs(band).max() + 1e-9)
    harm = (np.tanh(band * d + 0.3) - np.tanh(0.3)) / d            # +0.3 bias -> even harmonics (smooth)
    return y + amount * sosfilt(butter(2, 7000, "high", fs=SR, output="sos"), harm)


def saturate(y, amount):
    """Tape-style warmth: asymmetric soft clip of the whole voice, blended in. Density, not distortion."""
    if amount <= 0:
        return y
    pk = np.percentile(np.abs(y), 99.9) + 1e-9
    d = 1.6 / pk
    sat = (np.tanh(y * d + 0.15) - np.tanh(0.15)) / d
    sat *= np.sqrt(np.mean(y ** 2) / (np.mean(sat ** 2) + 1e-12))  # level-match before blending
    return (1 - amount) * y + amount * sat


def dyn_band(y, lo, hi, over_db, max_cut):
    """Split-band dynamic cut: turn lo-hi Hz down only where it is unusually loud relative to the voice
    (de-esser for 5.5-11 kHz, harshness tamer for 2.5-5 kHz)."""
    if max_cut <= 0:
        return y
    band = sosfiltfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), y)
    w = int(SR * 0.005)
    b_db = 10 * np.log10(uniform_filter1d(band ** 2, w) + 1e-12)
    a_db = 10 * np.log10(uniform_filter1d(y ** 2, w) + 1e-12)
    loud = a_db > np.percentile(a_db, 40)
    rel = b_db - a_db
    cut = np.clip((rel - np.median(rel[loud]) - over_db) * 0.8, 0, max_cut) * loud
    return y - band + band * 10 ** (-uniform_filter1d(cut, int(SR * 0.012)) / 20)


def peak_control(y, above_db):
    """Catch consonant spikes ~above_db over the voice's RMS. Uses the engine's look-ahead brickwall:
    a fast compressor (0.3 ms attack) flicked its gain on every tuned pulse and clicked."""
    active = y[np.abs(y) > 1e-3]
    if not len(active):
        return y
    rms_db = 10 * np.log10(np.mean(active ** 2))
    return engine.brickwall(y[None], float(rms_db + above_db), lookahead_ms=5.0, release_ms=80)[0]


def gap_gate(y, below_db=24.0, slope=3.0, floor_db=-24.0):
    """Downward expander for the gaps between phrases (compression lifts the noise there)."""
    env_db = 20 * np.log10(uniform_filter1d(np.abs(y), int(SR * 0.02)) + 1e-9)
    g_db = np.clip((env_db - (np.percentile(env_db, 95) - below_db)) * slope, floor_db, 0)
    return y * 10 ** (uniform_filter1d(g_db, int(SR * 0.06)) / 20)


# ---------- space: convolution reverb, ping-pong delay, doubler ----------

_IR_CACHE = {}


def reverb_ir(style):
    """Synthetic stereo IR: decaying, decorrelated noise per band (highs die faster, like a real plate/hall),
    soft onset, pre-delay. Smooth and dense, unlike a comb-filter (Freeverb) reverb."""
    if style in _IR_CACHE:
        return _IR_CACHE[style]
    rt, pre = REVERB_STYLES[style]
    n = int(SR * rt * 1.3)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    ir = np.zeros((2, n))
    for lo, hi, k in ((60, 500, 1.15), (500, 4000, 1.0), (4000, 12000, 0.55)):   # band edges, RT multiplier
        sos = butter(2, [lo, hi], "band", fs=SR, output="sos")
        env = 10 ** (-3 * t / (rt * k))                                          # -60 dB at RT
        ir += sosfilt(sos, rng.normal(size=(2, n)), axis=1) * env
    ir *= np.minimum(1, t / 0.004)                                               # no click at the onset
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))
    ir = np.pad(ir, ((0, 0), (int(SR * pre), 0)))
    _IR_CACHE[style] = ir.astype(np.float32)
    return _IR_CACHE[style]


# Shared by the server render and the browser's live engine (sent to the UI as job["fx"]), so the
# preview and the download are the same mix. 2nd-order Butterworth = a Web Audio biquad at Q 0.7071.
FX = {"send_hp": 300.0, "send_lp": 8500.0, "reverb_gain": 0.55, "delay_gain": 0.5, "delay_fb": 0.32,
      "delay_lp": 4500.0, "delays": DELAY_STYLES, "doubler": [[0.014, 0.0007, 0.31], [0.021, 0.0009, 0.23]],
      "doubler_db": -8.0, "doubler_hp": 220.0, "doubler_lp": 10000.0, "bright_hz": 8000.0, "bright_db": 6.0,
      "warm_hz": 200.0, "warm_db": 3.0, "duck_rate": 100}
STEM_LUFS = -16.0


def _bq(kind, f, y):
    return sosfilt(butter(2, f, kind, fs=SR, output="sos"), y, axis=-1).astype(np.float32)


def _duck(y, depth=0.55):
    """Gain for effect returns: dips while the voice is loud, blooms in the gaps (keeps the words clear)."""
    env = uniform_filter1d(np.abs(y), int(SR * 0.01))
    # one-pole release (250 ms) on a 64x-decimated envelope: fast
    D = 64
    e = env[::D]
    out = np.empty_like(e)
    cur = 0.0
    r = 1 - np.exp(-D / (SR * 0.25))
    for i, v in enumerate(e):
        cur = v if v > cur else cur + (v - cur) * r
        out[i] = cur
    env = np.interp(np.arange(len(y)), np.arange(len(out)) * D, out)
    norm = np.clip(env / (np.percentile(env, 95) + 1e-9), 0, 1)
    return 1 - depth * norm


def duck_curve(polished):
    """The ducking gain at FX["duck_rate"] Hz: the browser schedules exactly these points."""
    return _duck(polished)[:: SR // FX["duck_rate"]].astype(np.float32)


def _duck_at(curve, n):
    """Curve back to per-sample, linear between points (what Web Audio's setValueCurveAtTime does)."""
    return np.interp(np.arange(n), np.arange(len(curve)) * (SR // FX["duck_rate"]), curve).astype(np.float32)


def doubler(y, amount):
    """Two modulated copies (14/21 ms, slow wobble = a few cents of drift) panned L/R: width + richness."""
    n = np.arange(len(y))
    out = []
    for base, depth, rate in FX["doubler"]:
        d = (base + depth * np.sin(2 * np.pi * rate * n / SR)) * SR
        out.append(np.interp(n - d, n, y, left=0.0))
    st = _bq("low", FX["doubler_lp"], _bq("high", FX["doubler_hp"], np.stack(out)))
    return st * (amount * 10 ** (FX["doubler_db"] / 20))


def _echo(x, t, first=None):
    """Feedback delay: y[n] = x[n-D] + fb*y[n-D] (pedalboard Delay = a Web Audio DelayNode in a feedback loop)."""
    fx = [Delay(delay_seconds=first, feedback=0, mix=1.0)] if first else []
    return Pedalboard(fx + [Delay(delay_seconds=2 * t, feedback=FX["delay_fb"], mix=1.0)])(x[None], SR)[0]


def space(y, s, duck):
    """Mono vocal -> stereo: dry + doubler + ducked convolution reverb + ducked ping-pong echo."""
    a = s["mix"]
    st = np.stack([y, y])
    if s["width"] * a > 0:
        st = st + doubler(y, s["width"] * a)
    send = _bq("low", FX["send_lp"], _bq("high", FX["send_hp"], st))
    d = _duck_at(duck, len(y))
    if s["reverb"] * a > 0:
        ir = reverb_ir(s["reverb_style"])
        wet = np.stack([fftconvolve(send[c], ir[c])[: len(y)] for c in (0, 1)])
        st = st + wet * d * (FX["reverb_gain"] * s["reverb"] * a)
    if s["delay"] * a > 0:
        t = DELAY_STYLES[s["delay_style"]]
        echo = np.stack([_echo(send[0], t), _echo(send[1], t, first=t)])      # L: 2t, 4t.. R: t, 3t..
        st = st + _bq("low", FX["delay_lp"], echo) * d * (FX["delay_gain"] * s["delay"] * a)
    return st


def tone_knobs(y, s):
    """Brightness / Warmth knobs: shelves on the vocal, identical to the browser's biquads (Q 0.7071)."""
    fx = []
    if s["warmth"]:
        fx.append(LowShelfFilter(FX["warm_hz"], FX["warm_db"] * s["warmth"], 0.7071))
    if s["brightness"]:
        fx.append(HighShelfFilter(FX["bright_hz"], FX["bright_db"] * s["brightness"], 0.7071))
    return _pb(fx, y)


def mixdown(s0, s1, duck, s):
    """Mix knob = dry/wet between your cleaned voice (s0) and the polished one (s1). Same tuning and no
    latency between them, so blending is plain parallel processing (no comb filtering)."""
    v = (1 - s["mix"]) * s0 + s["mix"] * s1
    return space(tone_knobs(v, s), s, duck)


def render(s0, s1, duck, s, out_path):
    engine.save(master(mixdown(s0, s1, duck, s)).astype(np.float32), out_path)


def _tp_envelope(st):
    """Per-sample peak of the 4x-oversampled signal: catches peaks between samples."""
    n = st.shape[-1]
    up = np.abs(resample_poly(st, 4, 1, axis=-1)).max(axis=0)
    return np.pad(up, (0, max(0, 4 * n - len(up))))[: 4 * n].reshape(n, 4).max(1)


def master(st, lufs_target=TARGET_LUFS, ceiling=CEILING_DBTP):
    x = engine.to_lufs(st, lufs_target)
    y = x
    for _ in range(3):                         # limiting lowers LUFS; re-aim
        y = engine.brickwall(x, ceiling, peak=_tp_envelope(x))
        miss = lufs_target - engine.lufs(y)
        if abs(miss) < 0.2:
            break
        x = x * 10 ** (miss / 20)
    return y


# ---------- the chain ----------
PREP = ("clean", "hum", "eq", "autotune")              # cleanup + tuning: always full strength, cached per take
POLISH = ("bright", "dynamics", "sibilance", "tone", "gate")


def _prep_step(y, step):
    p, sid = step["params"], step["id"]
    if sid == "clean":
        y = derumble(y - y.mean())
        return engine.to_lufs(denoise(y, p["denoise_db"])[None], -18.0)[0]
    if sid == "hum":                           # true notches: very deep, ~2 Hz wide
        for f in p["freqs"]:
            sos = tf2sos(*iirnotch(f, 25.0, SR))
            y = sosfilt(sos, sosfilt(sos, y))
        return y
    if sid == "eq":
        return _pb([PeakFilter(f, g, q) for f, g, q in find_resonances(y)], y)
    if sid == "autotune":
        return tune.autotune(y[None], p["level"], p["key"])[0]
    return y


def _polish_step(y, sid, s):
    """One polish stage at the user's settings. a = mix amount scales every move; 0 leaves the voice alone."""
    a = s["mix"]
    if a <= 0:
        return y
    tgt = target_curve(s["brightness"], s["warmth"])
    if sid == "bright":
        return exciter(eq_pass(y, 0.8 * a, tgt), 0.12 * a)
    if sid == "dynamics":
        dry = _pb([Compressor(threshold_db=-22, ratio=1 + 3 * a, attack_ms=10, release_ms=80),
                   Compressor(threshold_db=-20, ratio=1 + 2 * a, attack_ms=15, release_ms=150)], y)
        # parallel ("New York") compression: a squashed copy under the voice = thickness without pumping
        crush = _pb([Compressor(threshold_db=-34, ratio=10, attack_ms=5, release_ms=120)], y)
        crush *= np.sqrt(np.mean(dry ** 2) / (np.mean(crush ** 2) + 1e-12))
        y = dry + 0.35 * a * crush
        return peak_control(y, 8.0)
    if sid == "sibilance":
        y = dyn_band(y, 2500, 5000, 4.0, 4.0 * a)        # harsh upper-mids, only when they stab
        return dyn_band(y, 5500, 11000, 6.0, 9.0 * a)    # S / T
    if sid == "tone":
        y = saturate(y, a * (0.18 + 0.17 * s["warmth"]))
        own = band_spectrum(y)
        return derumble(match_tone(y, own + a * (tgt - own)))   # again: the 113 Hz body boost lifts rumble too
    if sid == "gate":
        return gap_gate(y, floor_db=-32.0 * a)   # deeper than v1: parallel compression lifts the gaps
    return y


def polish(prep, s=POLISH_AT):
    y = prep
    for sid in POLISH:
        y = _polish_step(y, sid, s).astype(np.float32)
    return y


def fix(in_path, out_path, steps, progress=engine._noop, dry_path=None, stem_paths=None):
    """One-click fix. Writes the finished vocal (default settings) to out_path and returns the duck curve.
    stem_paths=(s0, s1): your cleaned/tuned voice and the polished voice, level-matched at STEM_LUFS, for the
    live Mix rack. dry_path: polished vocal mastered without reverb/echo, for Phantom (it reads tails as noise)."""
    tune.autotune.last_key = None
    y = engine.load(in_path).mean(axis=0)
    prep = None
    for i, step in enumerate(steps):
        progress("plugin", slot=i, plugin=step["label"])
        if step["id"] in PREP:
            y = _prep_step(y, step).astype(np.float32)
        elif step["id"] in POLISH:
            if prep is None:
                prep = y
            y = _polish_step(y, step["id"], POLISH_AT).astype(np.float32)
    s0 = engine.to_lufs((y if prep is None else prep)[None], STEM_LUFS)[0].astype(np.float32)
    s1 = engine.to_lufs(y[None], STEM_LUFS)[0].astype(np.float32)
    duck = duck_curve(s1)
    render(s0, s1, duck, settings(), out_path)
    if stem_paths:
        for path, stem in zip(stem_paths, (s0, s1)):
            write_stem(path, stem)
    if dry_path:
        engine.save(master(np.stack([s1, s1])).astype(np.float32), dry_path)
    progress("meta", key=tune.autotune.last_key)
    return duck


def write_stem(path, mono):
    """Stems for the browser: 24-bit FLAC, sample-accurate (mp3 adds padding that would misalign them)."""
    engine.sf.write(path, np.clip(mono, -1, 1), SR, subtype="PCM_24", format="FLAC")


def read_stem(path):
    return engine.sf.read(path, dtype="float32")[0]


def write_ir(style, path):
    engine.sf.write(path, reverb_ir(style).T, SR, subtype="FLOAT")


def score(report, before=None):
    """0-100: severity penalties (each problem type once) + distance from the loudness target.
    With `before`, unfixable damage found there keeps its penalty even if the re-analysis misses it."""
    if not report:
        return None
    found = _problems(report)
    carried = {t: p for t, p in _problems(before).items() if t in UNFIXABLE and t not in found}
    pen = sum(_PENALTY.get(p.get("severity"), 4) for p in {**found, **carried}.values())
    lufs = report.get("loudness", {}).get("integrated_lufs")
    if lufs is not None:
        pen += min(15.0, max(0.0, abs(lufs - TARGET_LUFS) - 1.0) * 1.5)
    return int(round(max(0.0, 100.0 - pen)))


def fixed(before, after):
    """Problem types present before the fix and gone after it (never the unfixable kinds)."""
    return sorted(set(_problems(before)) - set(_problems(after)) - UNFIXABLE)


def _tuned_harmonics(problem, key, share=0.7):
    """True when most reported 'resonances' sit on harmonics of in-key notes: a tuned voice holds exact
    pitches, so its harmonics look like narrow peaks. That is the tuning working, not a room problem."""
    pcs = tune.scale_pcs(key)
    res = problem.get("details", {}).get("resonances", [])

    def on_note(f):
        m = 69 + 12 * np.log2(f / 440)
        return any(abs(m - 12 * np.log2(k) - round(m - 12 * np.log2(k))) < 0.2
                   and round(m - 12 * np.log2(k)) % 12 in pcs for k in range(1, 9))
    return bool(res) and np.mean([on_note(r["frequency_hz"]) for r in res]) >= share


def visible(report, tuned_key=None):
    """The report with harmless findings dropped (same rules as scoring), for the UI.
    tuned_key: the key auto-tune used, so tuned-note harmonics aren't shown as resonances."""
    if not report:
        return report
    keep = set(_problems(report))
    probs = [p for p in (report.get("problems") or {}).get("problems", []) if p["type"] in keep
             and not (tuned_key and p["type"] == "resonant_peak" and _tuned_harmonics(p, tuned_key))]
    return {**report, "problems": {**(report.get("problems") or {}), "problems": probs}}
