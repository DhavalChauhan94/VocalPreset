"""Key detection by ensemble voting over Essentia KeyExtractor profiles. No FastAPI imports."""
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from app.audio_io import SAMPLE_RATE, AudioError
from app.music_theory import normalize_note

PROFILES: tuple[str, ...] = ("edma", "bgate", "temperley")
MIN_SECONDS: float = 5.0
HEAD_SECONDS: float = 120.0
MIDDLE_SECONDS: float = 60.0
SILENCE_RMS: float = 1e-4   # about -80 dBFS


@dataclass(frozen=True)
class KeyDetection:
    key: str            # sharp spelling, e.g. "F#"
    scale: str          # "major" | "minor"
    confidence: float   # 0..1
    agreeing: int       # profiles whose own pick matches the winner
    profiles: int


def analysis_windows(audio: np.ndarray, sr: int = SAMPLE_RATE) -> list[np.ndarray]:
    """Whole file if it fits in the head window; else the first 120 s plus 60 s from the middle."""
    if len(audio) <= HEAD_SECONDS * sr:
        return [audio]
    mid, half = len(audio) // 2, int(MIDDLE_SECONDS * sr / 2)
    return [audio[: int(HEAD_SECONDS * sr)], audio[mid - half: mid + half]]


def check_audio(audio: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    seconds = len(audio) / sr
    if seconds < MIN_SECONDS:
        raise AudioError("AUDIO_TOO_SHORT",
                         f"Audio is {seconds:.1f} s long; at least {MIN_SECONDS:.0f} s is needed.", 422)
    if float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) < SILENCE_RMS:
        raise AudioError("SILENT_AUDIO", "Audio is silent, so there is no key to detect.", 422)


def _run_profile(audio: np.ndarray, profile: str, sr: int) -> tuple[str, float]:
    import essentia.standard as es   # deferred: heavy import, and only this function needs it
    key, scale, strength = es.KeyExtractor(profileType=profile, sampleRate=sr)(audio)
    return f"{normalize_note(key)} {scale}", float(strength)


def detect(audio: np.ndarray, sr: int = SAMPLE_RATE) -> KeyDetection:
    """Sum strength per 'key scale' over every profile and window; the highest total wins.
    confidence = winning total / number of runs (one run = one profile on one window)."""
    check_audio(audio, sr)
    windows = analysis_windows(audio, sr)
    totals: dict[str, float] = defaultdict(float)
    per_profile: dict[str, dict[str, float]] = {p: defaultdict(float) for p in PROFILES}
    for window in windows:
        for profile in PROFILES:
            candidate, strength = _run_profile(window, profile, sr)
            totals[candidate] += strength
            per_profile[profile][candidate] += strength
    winner = max(totals, key=totals.__getitem__)
    agreeing = sum(max(votes, key=votes.__getitem__) == winner for votes in per_profile.values())
    key, scale = winner.split()
    return KeyDetection(key=key, scale=scale,
                        confidence=round(totals[winner] / (len(PROFILES) * len(windows)), 2),
                        agreeing=agreeing, profiles=len(PROFILES))
