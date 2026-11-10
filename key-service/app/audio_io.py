"""Upload validation and decoding (ffmpeg -> mono float32 at 44.1 kHz). No FastAPI imports."""
import os
import subprocess

import numpy as np

SAMPLE_RATE: int = 44100
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg"})


class AudioError(Exception):
    """A client-facing failure with a stable code and HTTP status."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def max_upload_bytes() -> int:
    return int(float(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024)


def check_extension(filename: str | None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AudioError("UNSUPPORTED_FORMAT",
                         f"'{ext or 'no extension'}' is not supported. Use one of: "
                         + ", ".join(sorted(ALLOWED_EXTENSIONS)), 415)
    return ext


def too_large() -> AudioError:
    return AudioError("FILE_TOO_LARGE",
                      f"File is larger than {max_upload_bytes() // (1024 * 1024)} MB.", 413)


def decode(path: str) -> np.ndarray:
    """Any format ffmpeg reads -> 1-D float32 mono at SAMPLE_RATE."""
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no audio stream"]
        raise AudioError("DECODE_FAILED", f"Could not decode the audio: {detail[0]}", 422)
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()
