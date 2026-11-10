"""Key detection for auto-tune.

1. The vocal itself (primary): held notes -> the 7-note scale that covers the most sung time -> the
   tonic from phrase endings, time on the note and key profiles. Built for dry vocals: chord-based
   detectors (Essentia) are made for full mixes and picked C major for an F# minor take.
2. The beat (optional, most accurate): the key-service reads the instrumental's chords. Its answer is
   trusted only if the vocal's held notes fit that scale, so a bad beat reading can't override a clear vocal.
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
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
# conventional spelling (fewest accidentals), indexed by pitch class
_DISPLAY = {"major": ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"],
            "minor": ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]}
# Krumhansl-Kessler and Albrecht-Shanahan key profiles: (major, minor), C-rooted
_PROFILES = (([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
              [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
             ([0.238, 0.006, 0.111, 0.006, 0.137, 0.094, 0.016, 0.214, 0.009, 0.080, 0.008, 0.081],
              [0.220, 0.006, 0.104, 0.123, 0.019, 0.103, 0.012, 0.214, 0.062, 0.022, 0.061, 0.052]))
# tonic weights: phrase endings, time on the note, longest notes, penalty per unit of scale fit lost,
# and how close (fit) a scale must be to the best to be a candidate. Tuned on synthetic melodies (see ARCHITECTURE).
_W = (1.0, 0.6, 0.4, 2.0, 0.04)
_SR2, _HOP = 22050, 256
HOP_S = _HOP / _SR2


# ---------- the vocal ----------

def pitch_track(x_mono):
    """pYIN pitch in MIDI (NaN = unvoiced), one value per HOP_S seconds."""
    y = librosa.resample(x_mono, orig_sr=engine.SR, target_sr=_SR2)
    f0, v, _ = librosa.pyin(y, fmin=65, fmax=1050, sr=_SR2, frame_length=2048, hop_length=_HOP)
    return librosa.hz_to_midi(np.where(v, f0, np.nan))


def held_notes(midi, hop_s=HOP_S, tol=0.3, min_s=0.10, phrase_gap_s=0.25):
    """Rows of (pitch, seconds, ends_phrase) for every stretch held within +-tol semitones for >= min_s.
    Slides and passing pitches between notes are left out: they are what fooled the old detectors."""
    notes, run, gap = [], [], 0

    def close():
        if len(run) * hop_s >= min_s:
            notes.append([float(np.median(run)), len(run) * hop_s, 0.0])

    for m in midi:
        if not np.isfinite(m):
            if run:
                close()
                run = []
            gap += 1
            if gap * hop_s >= phrase_gap_s and notes:
                notes[-1][2] = 1.0                     # last held note before a pause ends a phrase
            continue
        gap = 0
        if run and abs(m - np.median(run[-8:])) > tol:
            close()
            run = []
        run.append(m)
    if run:
        close()
    if notes:
        notes[-1][2] = 1.0
    return np.array(notes, dtype=float).reshape(-1, 3)


def _z(v):
    v = np.asarray(v, dtype=float)
    return (v - v.mean()) / (v.std() + 1e-12)


def scale_fit(hist, root, mode):
    """Share of held time that lands on the 7 notes of root/mode."""
    steps = MAJOR if mode == "major" else MINOR
    return float(hist[[(root + i) % 12 for i in steps]].sum() / max(hist.sum(), 1e-12))


def rank_keys(midi, hop_s=HOP_S):
    """All plausible keys for a vocal, best first: [{key, score, fit}], plus held-note stats."""
    n = held_notes(midi, hop_s)
    if len(n) < 8 or n[:, 1].sum() < 3.0:
        return [], {"held_notes": int(len(n))}
    pcs = np.round(n[:, 0]).astype(int) % 12
    dur = n[:, 1]
    hist = np.bincount(pcs, weights=dur, minlength=12)
    share = hist / hist.sum()
    end = n[:, 2] > 0
    ends = np.bincount(pcs[end], weights=dur[end], minlength=12)
    ends = ends / max(ends.sum(), 1e-12)
    long_ = dur >= np.percentile(dur, 80)
    longest = np.bincount(pcs[long_], weights=dur[long_], minlength=12)
    longest = longest / max(longest.sum(), 1e-12)
    fits = np.array([scale_fit(hist, r, "major") for r in range(12)])   # relative minors share the set
    best_fit = fits.max()
    out = []
    for r in range(12):
        if fits[r] < best_fit - _W[4]:             # only scales nearly as good as the best are candidates
            continue
        for root, mode, mi in ((r, "major", 0), ((r + 9) % 12, "minor", 1)):
            prof = np.mean([np.corrcoef(np.roll(_z(P[mi]), root), hist)[0, 1] for P in _PROFILES])
            score = prof + _W[0] * ends[root] + _W[1] * share[root] + _W[2] * longest[root] + _W[3] * (fits[r] - best_fit)
            out.append({"key": f"{NOTES[root]} {mode}", "score": float(score), "fit": float(fits[r])})
    out.sort(key=lambda k: -k["score"])
    return out, {"held_notes": int(len(n)), "hist": hist}


# ---------- the key-service (beat, and a tie-break vote on the vocal) ----------

def _post_wav(wav_path, source, timeout=60):
    boundary = uuid.uuid4().hex
    with open(wav_path, "rb") as f:
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"take.wav\"\r\n"
                "Content-Type: audio/wav\r\n\r\n").encode() + f.read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{URL}?source_type={source}", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _service(path, source):
    """key-service answer for a file, or None if it's down/rejects it. Raises only for silent audio."""
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        # the service only takes wav/mp3/flac/m4a/ogg, so WhatsApp .mpeg/.opus/video become a mono wav
        engine.run_ffmpeg([*engine.ffmpeg_input(path), "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", wav])
        return _post_wav(wav, source)
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        if err.get("code") == "SILENT_AUDIO":
            raise ValueError(err["message"]) from e
        return None
    except (urllib.error.URLError, OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    finally:
        os.unlink(wav)


# ---------- answer ----------

def _notes_of(key_string):
    root, mode = key_string.split()
    return {(NOTES.index(root) + i) % 12 for i in (MAJOR if mode == "major" else MINOR)}


def _same_notes(a, b):
    return _notes_of(a) == _notes_of(b)


def _pretty(key_string):
    root, mode = key_string.split()
    return f"{_DISPLAY[mode][NOTES.index(root)]} {mode}"


def describe(key_string, confidence, low, source, alternatives, warnings):
    """The key-service response shape the UI and the fix already use."""
    root, mode = key_string.split()
    r = NOTES.index(root)
    steps = MAJOR if mode == "major" else MINOR
    pcs = [(r + i) % 12 for i in steps]
    rel_root, rel_mode = ((r + 9) % 12, "minor") if mode == "major" else ((r + 3) % 12, "major")
    return {"key": root, "scale": mode, "key_string": key_string,
            "display_key": f"{_DISPLAY[mode][r]} {mode}", "confidence": confidence,
            "agreement": source, "scale_notes": [NOTES[p] for p in pcs], "pitch_classes": pcs,
            "relative_key": f"{NOTES[rel_root]} {rel_mode}", "low_confidence": low,
            "warnings": warnings, "source": source, "alternatives": alternatives}


def detect(path, beat_path=None):
    """Most accurate key we can get for this take. Never raises for a readable file (silent -> ValueError)."""
    ranked, stats = rank_keys(pitch_track(engine.load(path).mean(axis=0)))
    hist = stats.get("hist")
    warnings = []

    if beat_path:                                   # the beat's chords define the song's key
        b = _service(beat_path, "instrumental")
        if b and hist is not None:
            fit = scale_fit(hist, NOTES.index(b["key"]), b["scale"])
            best = max((k["fit"] for k in ranked), default=0.0)
            if fit >= best - 0.10:
                alts = [b["key_string"]] + [k["key"] for k in ranked if k["key"] != b["key_string"]][:3]
                return describe(b["key_string"], b["confidence"], bool(b["low_confidence"]), "beat", alts, [])
            warnings.append(f"Your beat sounded like {b['display_key']}, but your sung notes don't fit it, "
                            "so we went with your vocal. Please check the key.")
        elif b and not ranked:
            return describe(b["key_string"], b["confidence"], bool(b["low_confidence"]), "beat",
                            [b["key_string"]], [])
        else:
            warnings.append("We couldn't read a key from the beat, so we used your vocal.")

    if not ranked:                                  # too few held notes (speech, short clip): Essentia
        s = _service(path, "vocals")
        if s:
            return describe(s["key_string"], s["confidence"], True, "key-service", [s["key_string"]],
                            ["Not many held notes to go on; please confirm the key."])
        raise ValueError("We couldn't hear enough sung notes to find a key. Pick it yourself.")

    # Essentia on the vocal: only a small tie-break vote among the vocal's own candidates
    s = _service(path, "vocals")
    if s:
        for k in ranked:
            if k["key"] == s["key_string"]:
                k["score"] += 0.15
        ranked.sort(key=lambda k: -k["score"])
    top = ranked[0]
    gap = top["score"] - ranked[1]["score"] if len(ranked) > 1 else 1.0
    confidence = round(float(np.clip(0.5 + gap, 0, 1) * top["fit"]), 2)
    low = gap < 0.15 or top["fit"] < 0.75
    # another scale (different 7 notes) fits the held notes just as well: the melody never sings the note
    # that tells them apart, so only the beat or the singer can decide
    twin = next((k for k in ranked[1:] if not _same_notes(k["key"], top["key"]) and top["fit"] - k["fit"] < 0.01), None)
    if twin:
        low = True
        warnings.append(f"Your melody fits {_pretty(top['key'])} and {_pretty(twin['key'])} equally well. "
                        "Tap the right one, or add your beat and we'll know for sure.")
    elif low:
        warnings.append("A dry vocal can sit between two keys. If you know the key, pick it; "
                        "adding your beat gives the most accurate answer.")
    return describe(top["key"], confidence, low, "vocal", [k["key"] for k in ranked[:4]], warnings)
