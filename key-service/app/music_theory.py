"""Key -> scale notes, MIDI pitch classes and relative key. Pure functions, no audio."""

NOTES: list[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLATS: dict[str, str] = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
                          "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}

# Semitone steps from the root. A new mode (e.g. "dorian": [0, 2, 3, 5, 7, 9, 10]) only needs an entry here.
MODES: dict[str, list[int]] = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],   # natural minor
}
# mode -> (relative mode, semitones from this root to the relative root)
RELATIVE: dict[str, tuple[str, int]] = {"major": ("minor", 9), "minor": ("major", 3)}

# Conventional key-signature spelling, indexed by pitch class (fewest accidentals, as musicians write it).
_DISPLAY: dict[str, list[str]] = {
    "major": ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"],
    "minor": ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"],
}


def normalize_note(name: str) -> str:
    """Any spelling ("Bb", "a#", "Db") -> sharp spelling ("A#", "A#", "C#")."""
    n = name.strip()
    n = n[:1].upper() + n[1:]
    n = _FLATS.get(n, n)
    if n not in NOTES:
        raise ValueError(f"unknown note: {name!r}")
    return n


def pitch_class(note: str) -> int:
    return NOTES.index(normalize_note(note))


def _check_mode(scale: str) -> str:
    if scale not in MODES:
        raise ValueError(f"unsupported scale: {scale!r}")
    return scale


def pitch_classes(key: str, scale: str) -> list[int]:
    root = pitch_class(key)
    return [(root + step) % 12 for step in MODES[_check_mode(scale)]]


def scale_notes(key: str, scale: str) -> list[str]:
    return [NOTES[pc] for pc in pitch_classes(key, scale)]


def relative_key(key: str, scale: str) -> str:
    other, shift = RELATIVE[_check_mode(scale)]
    return f"{NOTES[(pitch_class(key) + shift) % 12]} {other}"


def display_key(key: str, scale: str) -> str:
    return f"{_DISPLAY[_check_mode(scale)][pitch_class(key)]} {scale}"
