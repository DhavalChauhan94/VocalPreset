import numpy as np

import keys

HOP = keys.HOP_S


def frames(notes, gap_s=0.4):
    """[(midi, seconds) or None for a phrase break] -> per-frame pitch track like pitch_track() returns."""
    out = []
    for n in notes:
        if n is None:
            out += [np.nan] * int(gap_s / HOP)
            continue
        m, sec = n
        out += [m + 0.15 * np.sin(i / 3) for i in range(int(sec / HOP))]   # a little vibrato
    return np.array(out + [np.nan] * 40)


def phrase(degrees, root, steps, end_deg, base=48):   # 48 = C3; the root is added on top
    return [(base + root + steps[d % 7] + 12 * (d // 7), 0.35) for d in degrees] + [(base + root + steps[end_deg], 0.8), None]


def test_finds_f_sharp_minor_melody():
    fs, mi = keys.NOTES.index("F#"), keys.MINOR
    melody = []
    for _ in range(4):
        melody += phrase([0, 2, 4, 3, 2, 1, 4, 6], fs, mi, 0)
    ranked, _ = keys.rank_keys(frames(melody))
    assert ranked[0]["key"] == "F# minor"


def test_slides_between_notes_are_ignored():
    # a fast slide through off-key pitches must not count as held notes
    track = frames([(60, 0.6), None])
    slide = np.linspace(60, 67, 6)                      # ~70 ms glide through C#, D, D#, E, F, F#
    assert len(keys.held_notes(np.concatenate([track[:20], slide, track[:20]]))) == 2


def test_tonic_comes_from_phrase_endings():
    # same notes (A major / F# minor); phrases end on A -> A major
    a, ma = keys.NOTES.index("A"), keys.MAJOR
    melody = []
    for _ in range(4):
        melody += phrase([2, 4, 1, 5, 3, 2, 1], a, ma, 0)
    ranked, _ = keys.rank_keys(frames(melody))
    assert ranked[0]["key"] == "A major"


def test_answer_shape_and_twin_scale_warning():
    r = keys.describe("C# minor", 0.6, False, "vocal", ["C# minor", "F# minor"], [])
    assert r["display_key"] == "C# minor" and r["pitch_classes"] == [1, 3, 4, 6, 8, 9, 11] and r["relative_key"] == "E major"
    assert keys.describe("A# major", 0.9, False, "beat", [], [])["display_key"] == "Bb major"
    assert not keys._same_notes("C# minor", "F# minor") and keys._same_notes("F# minor", "A major")


def test_too_few_notes_gives_no_guess():
    ranked, stats = keys.rank_keys(frames([(60, 0.5), None]))
    assert ranked == [] and stats["held_notes"] < 8
