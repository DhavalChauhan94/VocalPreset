import subprocess

import pytest
from fastapi.testclient import TestClient

import app
import engine

client = TestClient(app.app)


def test_disguised_playlist_is_refused(tmp_path):
    # an HLS playlist renamed to .wav must not make ffmpeg fetch URLs (SSRF) or read other files
    p = tmp_path / "evil.wav"
    p.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/secret\n#EXT-X-ENDLIST\n")
    with pytest.raises(subprocess.CalledProcessError):
        engine.load(str(p))


def test_concat_list_is_refused(tmp_path):
    p = tmp_path / "evil.mp3"
    p.write_text("ffconcat version 1.0\nfile 'C:/Windows/win.ini'\n")
    with pytest.raises(subprocess.CalledProcessError):
        engine.load(str(p))


def test_oversized_upload_refused_before_reading():
    big = (app.MAX_MB + 5) * 1024 * 1024
    r = client.post("/api/takes", content=b"x", headers={"content-length": str(big), "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


def test_uploads_and_paths_are_never_served():
    for name in ("0123456789ab_in.wav", "0123456789ab_beat.wav", "..%2Fapp.py", "0123456789ab_s2.flac"):
        assert client.get(f"/api/file/{name}").status_code == 404
