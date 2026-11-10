import json
import os

import fixer

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = json.load(open(os.path.join(HERE, "..", "docs", "phantom-sample.json")))   # real report, clipped file


def ids(steps):
    return [s["id"] for s in steps]


def test_plan_from_real_report():
    steps = fixer.plan(SAMPLE)
    assert ids(steps)[0] == "clean" and ids(steps)[-2:] == ["polish", "master"]
    assert "note" in ids(steps)            # clipping is flagged honestly, not "fixed"
    assert "hum" in ids(steps)             # the sample report contains hum
    for s in steps:
        assert s["label"] and s["why"]     # every step explains itself to the user


def test_plan_without_report_is_generic():
    assert ids(fixer.plan(None)) == ["clean", "tone", "dynamics", "polish", "master"]


def test_autotune_levels():
    for level, p in fixer.AUTOTUNE.items():
        st = next(s for s in fixer.plan(None, level, "A minor") if s["id"] == "autotune")
        assert st["params"]["key"] == "A minor" and st["params"]["amount"] == p["amount"]
    assert "autotune" not in ids(fixer.plan(None, "off"))
    # stronger level = more correction, faster snap
    assert fixer.AUTOTUNE["light"]["amount"] < fixer.AUTOTUNE["heavy"]["amount"]
    assert fixer.AUTOTUNE["light"]["speed"] > fixer.AUTOTUNE["heavy"]["speed"]


def test_eq_cuts_are_safe():
    rep = {"problems": {"problems": [{"type": "resonant_peak", "severity": "significant", "details": {
        "resonances": [{"frequency_hz": f, "prominence_db": 60, "q_factor": 80} for f in (100, 500, 900, 1500, 2500, 4000)]}}]}}
    cuts = next(s for s in fixer.plan(rep) if s["id"] == "eq")["params"]["cuts"]
    assert len(cuts) == 4                                   # at most 4 resonances
    assert all(f > 150 and -6 <= g < 0 and q <= 12 for f, g, q in cuts)


def test_score_bounds_and_fixed():
    assert 0 <= fixer.score(SAMPLE) < 60                    # clipped + hum + loud -> poor
    clean = {"problems": {"problems": []}, "loudness": {"integrated_lufs": -16.0}}
    assert fixer.score(clean) == 100
    assert fixer.score(None) is None
    assert "hum" in fixer.fixed(SAMPLE, clean)
    # clipping is baked in: never reported as fixed, and its penalty stays after the fix
    assert "clipping" not in fixer.fixed(SAMPLE, clean)
    assert fixer.score(clean, before=SAMPLE) == 70
