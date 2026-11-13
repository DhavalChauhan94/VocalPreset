"""Downloads must open and share everywhere (WhatsApp, phones): 16-bit WAV, ID3v2.3 MP3, readable names."""
import os
import shutil

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import app
import engine

client = TestClient(app.app)
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


def test_wav_is_16_bit_dithered(tmp_path):
    p = str(tmp_path / "v.wav")
    x = np.zeros((2, engine.SR), dtype=np.float32)
    engine.save_16(x, p)
    info = sf.info(p)
    assert info.subtype == "PCM_16" and info.samplerate == 44100 and info.channels == 2
    y, _ = sf.read(p, dtype="int16")
    assert np.abs(y).max() <= 2                                    # silence stays (dither is +-1 LSB)


@needs_ffmpeg
def test_mp3_has_id3v23_and_a_title(tmp_path):
    src, dst = str(tmp_path / "v.wav"), str(tmp_path / "v.mp3")
    engine.save_16((0.1 * np.sin(np.arange(engine.SR) / 7)).astype(np.float32)[None].repeat(2, 0), src)
    app._ffmp3(src, dst, title="Recording (154) - Rap mix")
    head = open(dst, "rb").read(10)
    assert head[:3] == b"ID3" and head[3] == 3                     # v2.3, not v2.4
    assert b"Recording (154) - Rap mix" in open(dst, "rb").read(4096)


def test_titles_are_safe():
    assert app._title(r"C:\x\Recording (154).wav") == "Recording (154)"
    assert app._title("../../evil<script>.mp3") == "evilscript"
    assert app._title("गाना.m4a") == "vocal" and app._title(None) == "vocal"


def test_download_gets_a_readable_name():
    tid = "0123456789ab"
    path = os.path.join(app.OUT, f"{tid}.mp3")
    open(path, "wb").write(b"ID3")
    app.JOBS[tid] = {"id": tid, "title": "Recording (154)", "style": "melodic", "t0": 0}
    try:
        r = client.get(f"/api/file/{tid}.mp3")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
        assert 'filename="Recording (154) - Melodic mix.mp3"' in r.headers["content-disposition"]
        assert client.get(f"/api/jobs/{tid}").json()["names"]["wav"] == "Recording (154) - Melodic mix.wav"
    finally:
        os.unlink(path)
        app.JOBS.pop(tid)
