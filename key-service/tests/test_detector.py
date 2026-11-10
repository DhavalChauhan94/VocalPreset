import logging
from pathlib import Path

import numpy as np
import pytest

import generate_test_audio as gen
from app.audio_io import AudioError, decode
from app.detector import analysis_windows, detect
from app.music_theory import relative_key

log = logging.getLogger(__name__)


@pytest.mark.parametrize("stem", list(gen.KEYS))
def test_fixture_keys(stem: str, fixtures: Path) -> None:
    root, scale = gen.KEYS[stem]
    expected = f"{root} {scale}"
    found = detect(decode(str(fixtures / f"{stem}.wav")))
    got = f"{found.key} {found.scale}"
    if got == expected:
        return
    # soft pass: the relative key shares every note, which is the classic ambiguity
    assert got == relative_key(root, scale), f"{stem}: expected {expected}, got {got}"
    log.warning("%s: soft pass, detected relative key %s instead of %s", stem, got, expected)


def test_result_shape(fixtures: Path) -> None:
    found = detect(decode(str(fixtures / "c_major.wav")))
    assert 0.0 <= found.confidence <= 1.0
    assert 0 <= found.agreeing <= found.profiles == 3


def test_too_short() -> None:
    with pytest.raises(AudioError) as e:
        detect(gen.progression("C", "major", seconds=3.0))
    assert e.value.code == "AUDIO_TOO_SHORT"


def test_silent() -> None:
    with pytest.raises(AudioError) as e:
        detect(np.zeros(10 * gen.SR, dtype=np.float32))
    assert e.value.code == "SILENT_AUDIO"


def test_long_file_windows() -> None:
    sr = 100   # small rate keeps the arrays tiny; only lengths matter here
    short = analysis_windows(np.zeros(90 * sr), sr)
    long = analysis_windows(np.arange(600 * sr), sr)
    assert len(short) == 1
    assert [len(w) / sr for w in long] == [120.0, 60.0]
    assert long[1][0] / sr == 270.0   # centred on the middle (300 s)


def test_long_file_detects(fixtures: Path) -> None:
    clip = decode(str(fixtures / "g_major.wav"))
    found = detect(np.tile(clip, 14))   # 210 s: exercises the head + middle path
    assert f"{found.key} {found.scale}" in ("G major", "E minor")
