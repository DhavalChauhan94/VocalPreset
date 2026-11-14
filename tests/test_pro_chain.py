"""The sound engine that won the owner's blind A/B: AI restoration -> Airwindows processors -> Dragonfly reverb IRs."""
import numpy as np
import pytest

import fixer
import pro
import restore

SR = fixer.SR


def test_reverbs_are_the_captured_dragonfly_irs():
    for style in fixer.REVERB_STYLES:
        ir = fixer.reverb_ir(style)
        assert ir.shape[0] == 2 and ir.dtype == np.float32 and ir.shape[1] > SR      # stereo, over 1 s of tail
        assert np.abs(ir[:, -100:]).max() < 1e-3                                      # faded out, no click at the end
    assert fixer.reverb_ir("hall").shape[1] > fixer.reverb_ir("room").shape[1]       # a hall rings longer than a room
    assert fixer.settings({"reverb_style": "../app.py"})["reverb_style"] == fixer.DEFAULTS["reverb_style"]


def test_restoration_step_only_when_it_runs():
    assert [s["id"] for s in fixer.plan(None, restore=True)][:2] == ["restore", "clean"]
    assert "restore" not in [s["id"] for s in fixer.plan(None)]


def test_restoration_is_optional(monkeypatch, tmp_path):
    monkeypatch.setattr(restore, "MODEL_DIR", str(tmp_path))          # no models -> takes skip it, nothing breaks
    assert not restore.available()


def test_airwindows_state_codec_round_trips():
    raw = bytes(range(256)) * 3 + b"\x00\x01"
    assert pro._jdec(pro._jenc(raw)) == raw


@pytest.mark.skipif(not pro.available(), reason="Airwindows Consolidated not installed (start.ps1 installs it)")
def test_airwindows_effects_run_and_keep_the_level():
    t = np.arange(SR // 2) / SR
    y = (0.1 * np.sin(2 * np.pi * 220 * t) * (1 + np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    for name, knobs in (("Air3", dict(air=0.6, gnd=0.5)), ("Channel9", dict(console_type=0.5, drive=0.6, output=0.5)),
                        ("DeBess", dict(intense=0.3, sharp=0.5, depth=0.5, filter=0.5, sense=0.0))):
        z = pro.airwindows(name, y, **knobs)
        assert z.shape == y.shape and np.isfinite(z).all()
        assert abs(np.std(z) / np.std(y) - 1) < 1e-3                  # level-matched: gain staging unchanged
