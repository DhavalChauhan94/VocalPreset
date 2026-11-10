"""Key detection for auto-tune: our key-service (Essentia, 3-profile vote) with a librosa backup.

KEY_SERVICE_URL  default http://localhost:8001/detect-key (key-service runs in WSL/Docker, see SETUP.md)
"""
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid

import librosa
import numpy as np

import engine

URL = os.environ.get("KEY_SERVICE_URL", "http://localhost:8001/detect-key")
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _post_wav(wav_path, timeout=60):
    boundary = uuid.uuid4().hex
    with open(wav_path, "rb") as f:
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"take.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n").encode() + f.read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{URL}?source_type=vocals", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _backup(path, reason):
    """engine.detect_key: Krumhansl profile over the singer's own pYIN notes (librosa)."""
    x = engine.load(path).mean(axis=0)
    sr2 = 22050
    f0, voiced, _ = librosa.pyin(librosa.resample(x, orig_sr=engine.SR, target_sr=sr2),
                                 fmin=65, fmax=1050, sr=sr2, frame_length=2048, hop_length=256)
    name, notes = engine.detect_key(librosa.hz_to_midi(np.where(voiced, f0, np.nan)))
    root, scale = name.split()
    rel =f"{_NOTES[(_NOTES.index(root) + (9 if scale == 'major' else 3)) % 12]} {'minor' if scale == 'major' else 'major'}"
    return {"key": root, "scale": scale, "key_string": name, "display_key": name, "confidence": None,
            "agreement": "backup", "scale_notes": notes, "pitch_classes": [_NOTES.index(n) for n in notes],
            "relative_key": rel, "low_confidence": True,
            "warnings": [f"Used the backup detector ({reason}); please confirm the key."], "source": "backup"}


def detect(path):
    """Key JSON in the key-service shape. Never raises for a readable file: falls back to librosa."""
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        # the service only takes wav/mp3/flac/m4a/ogg, so WhatsApp .mpeg/.opus/video become a mono wav
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "44100",
                        "-c:a", "pcm_s16le", wav], check=True)
        try:
            return {**_post_wav(wav), "source": "key-service"}
        except Exception as e:   # service down, WSL asleep, or it rejected the audio
            reason = "key-service unavailable"
            if isinstance(e, urllib.error.HTTPError):
                err = json.loads(e.read() or b"{}").get("error", {})
                if err.get("code") == "SILENT_AUDIO":   # nothing to detect; a guess would mislead
                    raise ValueError(err["message"]) from e
                reason = err.get("message", reason)
            return _backup(path, reason)
    finally:
        os.unlink(wav)
