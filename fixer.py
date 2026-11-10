"""Studio vocal chain driven by measurement: Phantom findings + the take's own spectrum -> fix steps.

plan()  pure: report -> ordered steps (plain-English label + why for the UI).
fix()   applies them. Tone is matched to TARGET by measuring the take, not by fixed EQ moves.
score() 0-100 "studio readiness" from a Phantom report.

Chain order (dynamics before the final tone match, since compressors reshape the balance):
clean (HPF + spectral denoise) -> hum notches -> resonance cuts -> auto-tune -> rough tone + exciter
-> two compressors + peak control -> split-band de-esser -> final tone match -> gap expander
-> space (plate + 1/8 echo) -> true-peak master.
Tuned on a real 83 s laptop-mic take: score 61 -> 84, 7 kHz -28.7 -> -8.8 dB vs 1 kHz, gaps
-48 -> -69 dBFS, -12 LUFS at -1.2 dBTP. TARGET is a first reference curve ("check"): confirm it
against real studio vocals with match.py before treating it as final.
"""
import numpy as np
import librosa
from pedalboard import (Compressor, Delay, Gain, HighpassFilter, HighShelfFilter, LowpassFilter,
                        PeakFilter, Pedalboard, Reverb)
from scipy.ndimage import uniform_filter, uniform_filter1d
from scipy.signal import butter, iirnotch, resample_poly, sosfilt, sosfiltfilt, tf2sos

import engine
import tune

SR = engine.SR
TARGET_LUFS = -12.0
CEILING_DBTP = -1.2
AUTOTUNE = tune.LEVELS
# Long-term spectrum of a bright modern vocal, dB vs the 1 kHz band, loud frames only ("check").
BANDS = [(80, 160), (160, 320), (320, 640), (640, 1280), (1280, 2560), (2560, 5120), (5120, 10240), (10240, 16000)]
CENTERS = [113, 226, 453, 905, 1810, 3620, 7240, 12800]
TARGET = [-8.0, -5.0, -2.0, 0.0, -2.0, -5.0, -9.0, -14.0]
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
    s.append(_step("bright", "Add brightness and air",
                   "Brings up clarity and adds real top-end shimmer, the polished sheen of a studio mic."))
    s.append(_step("dynamics", "Make it loud and steady",
                   "Two compressors even out loud and quiet words so every line sits up front."))
    s.append(_step("sibilance", "Soften harsh S sounds",
                   "Once it's brighter, sharp 'S' and 'T' sounds are turned down only when they stab out.",
                   ("sibilance",)))
    s.append(_step("tone", "Balance the tone like a studio vocal",
                   "Measures your voice and shapes it to a studio vocal's balance: less boom, more presence.",
                   ("mud", "harshness")))
    s.append(_step("gate", "Silence the gaps", "Turns down background noise between phrases.", ("noise_floor", "snr")))
    if "clipping" in pr or "lossy_codec" in pr:
        s.append(_step("note", "Damage we can't fully undo",
                       "Distorted (clipped) or heavily compressed audio has lost detail for good. "
                       "We'll smooth it, but re-recording gives the best result.", ("clipping", "lossy_codec")))
    s.append(_step("space", "Studio space", "A short plate reverb and a soft echo, so it sounds produced, not dry."))
    s.append(_step("master", "Loud and streaming-safe",
                   f"Masters to {TARGET_LUFS:.0f} LUFS with true peaks under {CEILING_DBTP} dB: loud, and never crackles.",
                   ("inter_sample_peak",)))
    return s


# ---------- DSP (mono float32 arrays unless noted) ----------

def _pb(fx, y):
    return Pedalboard(fx)(y[None], SR)[0] if fx else y


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


def eq_pass(y, scale=0.8):
    diff = np.clip(np.array(TARGET) - band_spectrum(y), -8, 10)
    fx = [PeakFilter(c, float(d) * scale, 0.9) for c, d in zip(CENTERS[:-1], diff[:-1]) if abs(d) > 0.75]
    if abs(diff[-1]) > 0.75:
        fx.append(HighShelfFilter(10000, float(diff[-1]) * scale, 0.7))
    return _pb(fx, y)


def match_tone(y, tol=1.0, passes=4):
    for _ in range(passes):
        if np.abs(np.clip(np.array(TARGET) - band_spectrum(y), -8, 10)).max() < tol:
            break
        y = eq_pass(y, 0.9)
    return y


def exciter(y, amount=0.3):
    """Saturate the 2.5 kHz+ band and keep only the new >5 kHz harmonics: real top end a dark mic never caught."""
    band = sosfilt(butter(2, 2500, "high", fs=SR, output="sos"), y)
    drive = 2.0 / (np.abs(band).max() + 1e-9)
    harm = sosfilt(butter(2, 5000, "high", fs=SR, output="sos"), np.tanh(band * drive) / drive)
    return y + amount * harm


def deess(y, over_db=6.0, max_cut=9.0):
    """Split-band de-esser: cut 5.5-11 kHz only where it is unusually loud relative to the whole voice."""
    sib = sosfiltfilt(butter(2, [5500, 11000], "band", fs=SR, output="sos"), y)
    w = int(SR * 0.005)
    s_db = 10 * np.log10(uniform_filter1d(sib ** 2, w) + 1e-12)
    a_db = 10 * np.log10(uniform_filter1d(y ** 2, w) + 1e-12)
    loud = a_db > np.percentile(a_db, 40)
    rel = s_db - a_db
    cut = np.clip((rel - np.median(rel[loud]) - over_db) * 0.8, 0, max_cut) * loud
    return y - sib + sib * 10 ** (-uniform_filter1d(cut, int(SR * 0.012)) / 20)


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


def space(y):
    """Plate-style reverb (30 ms pre-delay) + 1/8 echo on a filtered send. Mono in, stereo out."""
    st = np.stack([y, y])
    send = Pedalboard([HighpassFilter(400), LowpassFilter(9000)])(st, SR)
    verb = Pedalboard([Delay(delay_seconds=0.03, feedback=0, mix=1.0),
                       Reverb(room_size=0.55, damping=0.55, wet_level=1.0, dry_level=0.0, width=1.0)])(send, SR)
    echo = Pedalboard([Delay(delay_seconds=0.214, feedback=0.22, mix=1.0), LowpassFilter(5000)])(send, SR)
    return st + 0.14 * verb + 0.07 * echo


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


def _apply(y, step):
    p, sid = step["params"], step["id"]
    if sid == "clean":
        y = _pb([HighpassFilter(85)], (y - y.mean()).astype(np.float32))
        return engine.to_lufs(denoise(y, p["denoise_db"])[None], -18.0)[0]
    if sid == "hum":                           # true notches: very deep, ~2 Hz wide
        for f in p["freqs"]:
            sos = tf2sos(*iirnotch(f, 25.0, SR))
            y = sosfilt(sos, sosfilt(sos, y))
        return y
    if sid == "autotune":
        return tune.autotune(y[None], p["level"], p["key"])[0]
    if sid == "eq":
        return _pb([PeakFilter(f, g, q) for f, g, q in find_resonances(y)], y)
    if sid == "bright":
        return exciter(eq_pass(y))
    if sid == "dynamics":
        # 10/15 ms attacks: faster ones ripple the gain on every pulse of a tuned low voice (measured clicks)
        y = _pb([Compressor(threshold_db=-22, ratio=4, attack_ms=10, release_ms=80),
                 Compressor(threshold_db=-20, ratio=3, attack_ms=15, release_ms=150), Gain(5)], y)
        return peak_control(y, 8.0)
    if sid == "sibilance":
        return deess(y)
    if sid == "tone":
        return _pb([HighpassFilter(20)], match_tone(y))
    if sid == "gate":
        return gap_gate(y)
    return y   # "note" is information only; "space" and "master" are handled in fix()


def fix(in_path, out_path, steps, progress=engine._noop, dry_path=None):
    """Write the finished stereo vocal to out_path. dry_path (optional) gets the same vocal mastered
    without reverb/echo: Phantom reads reverb tails as noise, so the after-analysis uses that one."""
    tune.autotune.last_key = None
    y = engine.load(in_path).mean(axis=0)
    wet = None
    for i, step in enumerate(steps):
        progress("plugin", slot=i, plugin=step["label"])
        if step["id"] == "space":
            wet = space(y)
        elif step["id"] != "master":
            y = _apply(y, step).astype(np.float32)
    dry = np.stack([y, y])
    engine.save(master(wet if wet is not None else dry).astype(np.float32), out_path)
    if dry_path:
        engine.save(master(dry).astype(np.float32), dry_path)
    progress("meta", key=tune.autotune.last_key)
    return out_path


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
