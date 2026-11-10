"""Upload validation and decoding (ffmpeg -> mono float32 at 44.1 kHz). No FastAPI imports."""
import os
import subprocess

import numpy as np

SAMPLE_RATE: int = 44100
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg"})
# Uploads are untrusted. Without these, ffmpeg guesses the format from the content, so an HLS playlist or
# concat list renamed to .wav could make it fetch URLs (SSRF) or read local files. Only demuxers that the
# allowed extensions can hold; local files only; capped decode length and time (no decompression bombs).
FFMPEG_FORMATS: str = "wav,w64,mp3,flac,ogg,mov,mp4,m4a,3gp,aac"
MAX_DECODE_SECONDS: int = 600
DECODE_TIMEOUT_S: int = 120


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
    """A real wav/mp3/flac/m4a/ogg file -> 1-D float32 mono at SAMPLE_RATE (first MAX_DECODE_SECONDS)."""
    failed = AudioError("DECODE_FAILED", "Could not decode the audio. Upload a real wav, mp3, flac, m4a or ogg file.", 422)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", FFMPEG_FORMATS,
             "-t", str(MAX_DECODE_SECONDS), "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
            capture_output=True, check=False, timeout=DECODE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise failed from None
    if proc.returncode != 0 or not proc.stdout:   # ffmpeg's own message names server paths: don't echo it
        raise failed
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()
