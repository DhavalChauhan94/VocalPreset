from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import generate_test_audio as gen
from app.main import app

client = TestClient(app)
FIELDS = ["key", "scale", "key_string", "display_key", "confidence", "agreement", "scale_notes",
          "pitch_classes", "relative_key", "low_confidence", "warnings", "analysis_seconds"]


def _post(path: Path, name: str | None = None, **params: str):
    with open(path, "rb") as f:
        return client.post("/detect-key", files={"file": (name or path.name, f)}, params=params)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_valid_upload(fixtures: Path) -> None:
    r = _post(fixtures / "a_minor.wav")
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == FIELDS
    assert body["key_string"] in ("A minor", "C major")
    assert len(body["pitch_classes"]) == 7 and body["warnings"] == []
    assert body["agreement"].endswith("/3")


def test_vocals_warning(fixtures: Path) -> None:
    body = _post(fixtures / "c_major.wav", source_type="vocals").json()
    assert len(body["warnings"]) == 1 and "vocals" in body["warnings"][0]


def test_bad_source_type(fixtures: Path) -> None:
    assert _post(fixtures / "c_major.wav", source_type="podcast").status_code == 422


def test_wrong_format(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("not audio")
    r = _post(p)
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


def test_oversized(fixtures: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.1")   # fixtures are ~1.3 MB
    r = _post(fixtures / "c_major.wav")
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_silent(tmp_path: Path) -> None:
    p = tmp_path / "silence.wav"
    gen.write_wav(p, np.zeros(10 * gen.SR, dtype=np.float32))
    r = _post(p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "SILENT_AUDIO"


def test_too_short(tmp_path: Path) -> None:
    p = tmp_path / "short.wav"
    gen.write_wav(p, gen.progression("C", "major", seconds=2.0))
    r = _post(p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "AUDIO_TOO_SHORT"


def test_undecodable(tmp_path: Path) -> None:
    p = tmp_path / "broken.mp3"
    p.write_bytes(b"\x00" * 4096)
    r = _post(p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "DECODE_FAILED"


def test_disguised_playlist_is_refused(tmp_path: Path) -> None:
    # an HLS playlist renamed to .wav must not make ffmpeg fetch URLs or read other files
    p = tmp_path / "evil.wav"
    p.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/secret\n#EXT-X-ENDLIST\n")
    r = _post(p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "DECODE_FAILED"
    assert "evil" not in r.json()["error"]["message"] and "/" not in r.json()["error"]["message"]   # no paths echoed


def test_missing_content_length_is_refused() -> None:
    r = client.post("/detect-key", content=b"x", headers={"content-type": "application/octet-stream", "content-length": ""})
    assert r.status_code in (411, 413)
