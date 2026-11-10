import json
import os

import numpy as np
import pyworld as pw

import fixer
import tune

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = json.load(open(os.path.join(HERE, "..", "docs", "phantom-sample.json")))   # real report, clipped file
SR = fixer.SR


def ids(steps):
    return [s["id"] for s in steps]


def test_plan_from_real_report():
    steps = fixer.plan(SAMPLE)
    assert ids(steps)[0] == "clean" and ids(steps)[-2:] == ["space", "master"]
    assert "note" in ids(steps)                            # clipping flagged honestly
    assert "hum" not in ids(steps)                         # its "hum" has salience 0.005: a clipping side effect
    for s in steps:
        assert s["label"] and s["why"]                     # every step explains itself


def test_plan_without_report_is_full_chain():
    assert ids(fixer.plan(None)) == ["clean", "eq", "bright", "dynamics", "sibilance", "tone", "gate", "space", "master"]


def test_autotune_step_and_levels():
    st = next(s for s in fixer.plan(None, "heavy", "A minor") if s["id"] == "autotune")
    assert st["params"] == {"level": "heavy", "key": "A minor"}
    assert "autotune" not in ids(fixer.plan(None, "off"))
    L = tune.LEVELS   # stronger = more correction, faster snap
    assert L["light"]["amount"] < L["heavy"]["amount"] and L["light"]["retune_ms"] > L["heavy"]["retune_ms"] == 0


def test_target_f0_snaps_with_hysteresis():
    pcs = tune.scale_pcs("A major")
    f0 = np.array([446.0] * 5 + [0.0] + [452.0] * 5)        # ~24 c then ~46 c sharp of A4
    out = tune.target_f0(f0, pcs, amount=1.0, retune_ms=0)
    assert np.allclose(out[f0 > 0], 440.0, atol=0.5) and out[5] == 0


def test_autotune_pulls_a_sharp_note_onto_pitch():
    t = np.arange(int(SR * 1.5)) / SR
    x = (0.3 * sum(np.sin(2 * np.pi * 446 * k * t) / k for k in range(1, 6))).astype(np.float32)
    y = tune.autotune(x[None], "heavy", "A major")[0]
    f0, _ = pw.harvest(y.astype(np.float64), SR, f0_floor=100, f0_ceil=800, frame_period=5)
    mid = f0[len(f0) // 4: -len(f0) // 4]
    assert abs(1200 * np.log2(np.median(mid[mid > 0]) / 440)) < 5    # within 5 cents of A4


def test_master_is_loud_and_true_peak_safe():
    rng = np.random.default_rng(0)
    x = (rng.normal(0, 0.1, (2, SR * 4)) * np.sin(np.linspace(0, 20, SR * 4)) ** 2).astype(np.float32)
    y = fixer.master(x)
    assert abs(fixer.engine.lufs(y) - fixer.TARGET_LUFS) < 0.5
    assert 20 * np.log10(fixer._tp_envelope(y).max()) <= fixer.CEILING_DBTP + 0.15


def test_match_tone_converges_on_target():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.05, SR * 6).astype(np.float32)          # flat (white) start, far from target
    y = fixer.match_tone(x)
    assert np.abs(np.array(fixer.TARGET) - fixer.band_spectrum(y)).max() < 2.0


def test_score_bounds_and_fixed():
    assert 0 <= fixer.score(SAMPLE) < 60                          # clipped + hum + loud -> poor
    clean = {"problems": {"problems": []}, "loudness": {"integrated_lufs": -12.0, "true_peak_dbtp": -1.2}}
    assert fixer.score(clean) == 100
    assert fixer.score(None) is None
    real_hum = {"loudness": {"integrated_lufs": -20.0}, "problems": {"problems": [
        {"type": "hum", "severity": "significant", "details": {"primary_frequency_hz": 50.0, "primary_salience": 0.995}}]}}
    assert "hum" in ids(fixer.plan(real_hum)) and "hum" in fixer.fixed(real_hum, clean)
    assert "clipping" not in fixer.fixed(SAMPLE, clean)           # baked in: never "fixed"
    assert fixer.score(clean, before=SAMPLE) == 70                # ...and keeps its penalty


def test_safe_inter_sample_peaks_are_not_problems():
    rep = {"loudness": {"true_peak_dbtp": -2.0},
           "problems": {"problems": [{"type": "inter_sample_peak", "severity": "moderate"}]}}
    assert fixer.score(rep) is not None and fixer.visible(rep)["problems"]["problems"] == []
    rep["loudness"]["true_peak_dbtp"] = 0.3
    assert len(fixer.visible(rep)["problems"]["problems"]) == 1


def test_tuned_note_harmonics_are_not_resonances():
    # harmonics of A4 (440) and E5 (659.3), both in A major, plus one off-key ring
    res = [{"frequency_hz": f} for f in (440.0, 880.0, 1320.0, 659.3, 1318.5, 1000.0)]
    rep = {"loudness": {"true_peak_dbtp": -1.2},
           "problems": {"problems": [{"type": "resonant_peak", "severity": "significant", "details": {"resonances": res}}]}}
    assert fixer.visible(rep, tuned_key="A major")["problems"]["problems"] == []
    assert len(fixer.visible(rep)["problems"]["problems"]) == 1          # untuned: still reported


def test_settings_are_validated():
    s = fixer.settings({"mix": 7, "warmth": -9, "reverb_style": "<script>", "delay_style": "quarter", "evil": 1})
    assert s["mix"] == 1.0 and s["warmth"] == -1.0 and s["reverb_style"] == "plate" and s["delay_style"] == "quarter"
    assert "evil" not in s and fixer.settings() == fixer.DEFAULTS


def test_mix_zero_is_your_cleaned_voice():
    rng = np.random.default_rng(2)
    s0 = (rng.normal(0, 0.05, SR * 3) * np.sin(np.linspace(0, 9, SR * 3)) ** 2).astype(np.float32)
    s1 = s0 * 0.5 + 0.01
    duck = fixer.duck_curve(s1)
    st = fixer.mixdown(s0, s1, duck, fixer.settings({"mix": 0.0}))
    assert np.allclose(st[0], s0, atol=1e-6) and np.allclose(st[1], s0, atol=1e-6)   # no polish, reverb, echo, double
    half = fixer.mixdown(s0, s1, duck, fixer.settings({"mix": 0.5, "reverb": 0, "delay": 0, "width": 0}))
    assert np.allclose(half[0], 0.5 * s0 + 0.5 * s1, atol=1e-6)                       # Mix = plain dry/wet


def test_duck_curve_round_trips():
    t = np.arange(SR * 4) / SR
    v = (0.3 * np.sin(2 * np.pi * 1000 * t) * (t < 2)).astype(np.float32)
    c = fixer.duck_curve(v)
    assert len(c) == int(np.ceil(len(v) / (SR // fixer.FX["duck_rate"])))
    assert np.abs(fixer._duck_at(c, len(v)) - fixer._duck(v)).max() < 0.05     # what the browser plays ~ server


def test_effects_duck_under_the_voice():
    t = np.arange(SR * 4) / SR
    voice = (0.3 * np.sin(2 * np.pi * 1000 * t) * (t < 2)).astype(np.float32)   # 2 s of voice, then silence
    g = fixer._duck(voice)
    assert g[int(SR * 1.5)] < 0.5                    # reverb/echo turned down ~6+ dB while the voice plays
    assert g[int(SR * 3.0)] > 0.95                   # and fully back once it stops, so tails bloom
