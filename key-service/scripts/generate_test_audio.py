"""Synthesize 15 s chord progressions in known keys -> tests/fixtures/*.wav.
Major: I-IV-V-I. Minor: i-iv-v-i (natural minor). Bass + triad, 5 harmonics, soft attack and release.
Usage: python scripts/generate_test_audio.py
"""
import wave
from pathlib import Path

import numpy as np

SR = 44100
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# file stem -> (sharp-spelled root, scale)
KEYS: dict[str, tuple[str, str]] = {
    "c_major": ("C", "major"),
    "a_minor": ("A", "minor"),
    "fs_minor": ("F#", "minor"),
    "eb_major": ("D#", "major"),
    "g_major": ("G", "major"),
}
_PROGRESSION = {"major": [(0, (0, 4, 7)), (5, (0, 4, 7)), (7, (0, 4, 7)), (0, (0, 4, 7))],
                "minor": [(0, (0, 3, 7)), (5, (0, 3, 7)), (7, (0, 3, 7)), (0, (0, 3, 7))]}


def _tone(midi: float, n: int) -> np.ndarray:
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    return sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, 6) if f * k < SR / 2)


def _envelope(n: int, fade_s: float = 0.05) -> np.ndarray:
    fade = int(fade_s * SR)
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return env


def progression(root: str, scale: str, seconds: float = 15.0) -> np.ndarray:
    tonic = 48 + NOTES.index(root)            # bass octave (C3..B3)
    n = int(seconds * SR / 4)
    chords = []
    for degree, triad in _PROGRESSION[scale]:
        bass = _tone(tonic + degree - 12, n) * 0.6
        upper = sum(_tone(tonic + degree + iv + 12, n) for iv in triad)
        chords.append((bass + upper) * _envelope(n))
    audio = np.concatenate(chords)
    return (audio / np.abs(audio).max() * 0.7).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


def main() -> None:
    for stem, (root, scale) in KEYS.items():
        write_wav(FIXTURES / f"{stem}.wav", progression(root, scale))
        print(f"wrote tests/fixtures/{stem}.wav ({root} {scale})")


if __name__ == "__main__":
    main()
