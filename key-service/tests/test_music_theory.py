import pytest

from app import music_theory as mt

ALL_KEYS = [(n, s) for s in ("major", "minor") for n in mt.NOTES]


@pytest.mark.parametrize("key,scale", ALL_KEYS)
def test_all_24_keys(key: str, scale: str) -> None:
    pcs = mt.pitch_classes(key, scale)
    root = mt.NOTES.index(key)
    assert len(pcs) == 7 and len(set(pcs)) == 7
    assert pcs == [(root + step) % 12 for step in mt.MODES[scale]]
    assert mt.scale_notes(key, scale) == [mt.NOTES[pc] for pc in pcs]
    assert mt.scale_notes(key, scale)[0] == key
    # relative keys share all 7 notes and point back to each other
    rel_key, rel_scale = mt.relative_key(key, scale).split()
    assert sorted(mt.pitch_classes(rel_key, rel_scale)) == sorted(pcs)
    assert mt.relative_key(rel_key, rel_scale) == f"{key} {scale}"


@pytest.mark.parametrize("key,scale,notes,pcs", [
    ("A", "minor", ["A", "B", "C", "D", "E", "F", "G"], [9, 11, 0, 2, 4, 5, 7]),
    ("C", "major", ["C", "D", "E", "F", "G", "A", "B"], [0, 2, 4, 5, 7, 9, 11]),
    ("F#", "minor", ["F#", "G#", "A", "B", "C#", "D", "E"], [6, 8, 9, 11, 1, 2, 4]),
    ("D#", "major", ["D#", "F", "G", "G#", "A#", "C", "D"], [3, 5, 7, 8, 10, 0, 2]),
])
def test_known_scales(key: str, scale: str, notes: list[str], pcs: list[int]) -> None:
    assert mt.scale_notes(key, scale) == notes
    assert mt.pitch_classes(key, scale) == pcs


def test_relative_examples() -> None:
    assert mt.relative_key("A", "minor") == "C major"
    assert mt.relative_key("C", "major") == "A minor"
    assert mt.relative_key("D#", "major") == "C minor"


@pytest.mark.parametrize("given,expected", [("Bb", "A#"), ("bb", "A#"), ("Eb", "D#"), ("Db", "C#"),
                                            ("Gb", "F#"), ("Ab", "G#"), ("F#", "F#"), ("c", "C")])
def test_normalize_to_sharps(given: str, expected: str) -> None:
    assert mt.normalize_note(given) == expected


@pytest.mark.parametrize("key,scale,shown", [("A#", "major", "Bb major"), ("D#", "major", "Eb major"),
                                             ("F#", "minor", "F# minor"), ("G#", "major", "Ab major"),
                                             ("C#", "minor", "C# minor"), ("D#", "minor", "Eb minor")])
def test_display_spelling(key: str, scale: str, shown: str) -> None:
    assert mt.display_key(key, scale) == shown


def test_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        mt.normalize_note("H")
    with pytest.raises(ValueError):
        mt.scale_notes("C", "lydian")
