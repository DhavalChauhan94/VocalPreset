"""Rules-based vocal fixer: Phantom findings (+ optional auto-tune key) -> pedalboard/librosa moves.

plan()  is pure: report -> ordered steps, each with a plain-English label and a "why" for the UI.
fix()   applies the steps, reusing engine.py's DSP (pre_clean, autotune, deess, master).
score() turns a Phantom report into a 0-100 "studio readiness" number.
Thresholds come from measurements in the report, not by ear (CLAUDE.md rule 2). Values marked
"check" are first guesses to confirm on real vocals with match.py / a re-analysis.
"""
import numpy as np
from scipy.signal import iirnotch, sosfilt, tf2sos
from pedalboard import (Compressor, HighpassFilter, HighShelfFilter, LowShelfFilter, NoiseGate, PeakFilter,
                        Pedalboard, Reverb)

import engine

SR = engine.SR
TARGET_LUFS = -16.0
# Light keeps natural slides, Heavy snaps instantly (the robotic hip-hop effect). Same keys as Pitcher.
AUTOTUNE = {"light": {"amount": 0.6, "speed": 0.6},
            "medium": {"amount": 0.85, "speed": 0.3},
            "heavy": {"amount": 1.0, "speed": 0.0}}
_PENALTY = {"dealbreaker": 30, "significant": 12, "moderate": 6, "minor": 2}
# Damage baked into the recording: re-analysis stops flagging it once peaks are limited, but it is still audible.
UNFIXABLE = {"clipping", "lossy_codec"}


def _problems(report):
    return {p["type"]: p for p in ((report or {}).get("problems") or {}).get("problems", [])}


def _step(id_, label, why, fixes=(), **params):
    return {"id": id_, "label": label, "why": why, "fixes": list(fixes), "params": params}


def plan(report, autotune="off", key=None):
    """Ordered fix steps for this take. Works with report=None (analysis failed): generic polish only."""
    pr = _problems(report)
    spec = (report or {}).get("spectral", {}).get("octave_band_energy_db", {})
    crest = (report or {}).get("dynamics", {}).get("crest_factor_db", 14.0)
    s = [_step("clean", "Clean up the recording",
               "Removes rumble and DC offset, quiets the gaps between phrases and sets a healthy level.",
               ("dc_offset", "noise_floor", "snr"),
               gate_db=-45.0 if ("noise_floor" in pr or "snr" in pr) else -55.0)]
    if "hum" in pr:
        d = pr["hum"].get("details", {})
        base = d.get("primary_frequency_hz") or 50.0
        # mains hum always brings harmonics (2x, 3x, 4x), even when only the fundamental is reported
        freqs = sorted({round(f, 1) for f in [*(d.get("frequencies_hz") or []), *(base * k for k in (1, 2, 3, 4))]
                        if f < 1000})
        s.append(_step("hum", "Remove electrical hum",
                       f"A steady {base:.0f} Hz buzz was found; we cut it and its echoes very narrowly.",
                       ("hum",), freqs=freqs))
    if autotune in AUTOTUNE:
        s.append(_step("autotune", f"Auto-tune ({autotune})",
                       f"Pulls each note to the nearest note of {key or 'the detected key'}.",
                       (), level=autotune, key=key or "auto", **AUTOTUNE[autotune]))
    cuts = []
    if "resonant_peak" in pr:
        res = [r for r in pr["resonant_peak"].get("details", {}).get("resonances", []) if r["frequency_hz"] > 150]
        for r in sorted(res, key=lambda r: -r["prominence_db"])[:4]:
            cuts.append((r["frequency_hz"], -min(6.0, r["prominence_db"] / 6), min(max(r["q_factor"], 2.0), 12.0)))
    for kind, freq, q in (("mud", 320.0, 1.0), ("harshness", 3000.0, 1.2)):
        if kind in pr:
            cuts.append((freq, -min(4.0, 1.0 + pr[kind].get("details", {}).get("excess_db", 2.0) / 2), q))
    if cuts:
        s.append(_step("eq", "Tame harsh and boomy spots",
                       f"{len(cuts)} frequency spot(s) stick out; narrow EQ cuts smooth them.",
                       ("resonant_peak", "mud", "harshness"), cuts=[list(c) for c in cuts]))
    # tone balance from octave bands (check): thin top -> add air, heavy low end -> trim body
    mid = np.mean([spec.get("1000_hz", -20), spec.get("2000_hz", -20)])
    air = np.mean([spec.get("8000_hz", mid - 12), spec.get("16000_hz", mid - 12)])
    low = np.mean([spec.get("125_hz", mid), spec.get("250_hz", mid)])
    s.append(_step("tone", "Balance the tone",
                   "Adds clarity on top and keeps the low end tidy, like a studio vocal.", (),
                   air_db=2.5 if air < mid - 18 else 1.0, low_db=-2.0 if low > mid + 6 else 0.0))
    s.append(_step("dynamics", "Even out the volume",
                   f"Loud and quiet words are {crest:.0f} dB apart; a compressor brings them closer.", (),
                   ratio=round(float(np.clip(1.5 + (crest - 8) / 4, 2.0, 5.0)), 1)))
    if "sibilance" in pr:
        s.append(_step("sibilance", "Soften harsh S sounds",
                       "Sharp 'S' and 'T' sounds are too loud; a de-esser turns just those down.", ("sibilance",)))
    if "clipping" in pr or "lossy_codec" in pr:
        s.append(_step("note", "Damage we can't fully undo",
                       "Distorted (clipped) or heavily compressed audio has lost detail for good. "
                       "We'll smooth it, but re-recording gives the best result.", ("clipping", "lossy_codec")))
    s.append(_step("polish", "Studio polish", "A touch of room so it doesn't sound dry and boxy.", ()))
    s.append(_step("master", "Loudness for streaming",
                   f"Sets {TARGET_LUFS:.0f} LUFS with a safe -1 dB peak ceiling, so it plays loud and clean.",
                   ("inter_sample_peak",)))
    return s


def _apply(x, step):
    p = step["params"]
    sid = step["id"]
    if sid == "clean":
        x = x - x.mean(axis=1, keepdims=True)
        x = np.repeat(x.mean(axis=0, keepdims=True), 2, axis=0)
        x = engine.to_lufs(x, -18.0)
        return Pedalboard([HighpassFilter(80), NoiseGate(threshold_db=p["gate_db"], ratio=2,
                                                                attack_ms=5, release_ms=220)])(x, SR)
    if sid == "hum":   # true notches (very deep at the exact frequency, ~2 Hz wide); peak-EQ cuts were too shallow
        for f in p["freqs"]:
            sos = tf2sos(*iirnotch(f, 25.0, SR))
            x = sosfilt(sos, sosfilt(sos, x, axis=1), axis=1)
        return x
    if sid == "autotune":
        return engine.autotune(x, p, p["key"])
    if sid == "eq":
        return Pedalboard([PeakFilter(f, g, q) for f, g, q in p["cuts"]])(x, SR)
    if sid == "tone":
        fx = [HighShelfFilter(9000, p["air_db"], 0.7)]
        if p["low_db"]:
            fx.append(LowShelfFilter(200, p["low_db"], 0.7))
        return Pedalboard(fx)(x, SR)
    if sid == "dynamics":
        return Pedalboard([Compressor(threshold_db=-24, ratio=p["ratio"], attack_ms=5, release_ms=90)])(x, SR)
    if sid == "sibilance":
        return engine.deess(x, thresh_db=-34, max_cut_db=10)
    if sid == "polish":
        return Pedalboard([Reverb(room_size=0.25, damping=0.6, wet_level=0.08, dry_level=1.0, width=0.6)])(x, SR)
    if sid == "master":   # 20 Hz high-pass first: the compressor and reverb leave a small DC offset
        return engine.master(Pedalboard([HighpassFilter(20)])(x, SR), TARGET_LUFS)
    return x   # "note": information only


def fix(in_path, out_path, steps, progress=engine._noop):
    engine.autotune.last_key = None
    x = engine.load(in_path)
    for i, step in enumerate(steps):
        progress("plugin", slot=i, plugin=step["label"])
        x = _apply(x, step).astype(np.float32)
    progress("meta", key=engine.autotune.last_key)
    engine.save(x, out_path)
    return out_path


def score(report, before=None):
    """0-100: severity penalties (each problem type counted once) + distance from the loudness target.
    With `before`, unfixable damage found there keeps its penalty even if the re-analysis misses it."""
    if not report:
        return None
    found = _problems(report)
    carried = {t: p for t, p in _problems(before).items() if t in UNFIXABLE and t not in found}
    pen = sum(_PENALTY.get(p.get("severity"), 4) for p in {**found, **carried}.values())
    lufs = report.get("loudness", {}).get("integrated_lufs")
    if lufs is not None:
        pen += min(15.0, abs(lufs - TARGET_LUFS) * 1.5)
    return int(round(max(0.0, 100.0 - pen)))


def fixed(before, after):
    """Problem types present before the fix and gone after it (never the unfixable kinds)."""
    return sorted(set(_problems(before)) - set(_problems(after)) - UNFIXABLE)
