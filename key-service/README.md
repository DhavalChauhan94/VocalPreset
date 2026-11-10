# key-service

A local, free microservice that detects a song's **key and scale** and returns JSON that an autotune step can use directly.

It runs Essentia's `KeyExtractor` with three profiles (`edma`, `bgate`, `temperley`) and lets them vote. No paid APIs, no cloud.

## Run it

### Docker (recommended)
```bash
docker build -t key-service:1.0 .
docker run -d --name keysvc -p 8001:8001 key-service:1.0      # 2 uvicorn workers
curl localhost:8001/health                                     # {"status":"ok"}
```
The upload limit is set with `-e MAX_UPLOAD_MB=50` (the default).

### Local (Linux / macOS / WSL; Python 3.11 and ffmpeg)
```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8001
```
**Windows:** Essentia has no Windows wheel, so run the service in WSL or Docker. WSL forwards `localhost:8001` to Windows.

WSL shuts Ubuntu down shortly after the last WSL window closes, and that stops the container. So run it with `--restart unless-stopped` and keep a WSL window open while you use it:
```bash
docker run -d --restart unless-stopped --name keysvc -p 8001:8001 key-service:1.0
```

### Tests
```bash
python scripts/generate_test_audio.py   # writes tests/fixtures/*.wav (also done automatically by pytest)
pytest -q
```

## API

### `POST /detect-key`
Multipart upload with the field `file`.
- Accepted: `.wav .mp3 .flac .m4a .ogg`
- Optional query `source_type`: `full_mix | instrumental | vocals`. `vocals` adds a reliability warning.

```bash
curl -F file=@tests/fixtures/fs_minor.wav localhost:8001/detect-key
curl -F file=@take.m4a "localhost:8001/detect-key?source_type=vocals"
```
Real output for `fs_minor.wav`:
```json
{
  "key": "F#", "scale": "minor", "key_string": "F# minor", "display_key": "F# minor",
  "confidence": 0.87, "agreement": "3/3",
  "scale_notes": ["F#", "G#", "A", "B", "C#", "D", "E"],
  "pitch_classes": [6, 8, 9, 11, 1, 2, 4],
  "relative_key": "A major", "low_confidence": false, "warnings": [], "analysis_seconds": 1.02
}
```
Field notes:
- **Spelling:** `key`, `key_string`, `scale_notes` and `relative_key` always use **sharps**. `display_key` uses the spelling musicians expect, e.g. D# major is shown as "Eb major".
- **`confidence`** is the winning candidate's total strength divided by the number of runs (profiles × analysed windows), so it falls between 0 and 1.
- **`agreement`** is how many of the three profiles picked the winner on their own.
- **`low_confidence`** is `true` when confidence is below 0.6 or only 1 of the 3 profiles agrees. The frontend should then ask the user to confirm or override the key.
- **Long files:** only the first 120 s plus 60 s from the middle are analysed, and their votes are combined.

### Errors
`{"error": {"code": "...", "message": "..."}}`

| Code | HTTP | When |
|---|---|---|
| `UNSUPPORTED_FORMAT` | 415 | The extension isn't in the list above |
| `FILE_TOO_LARGE` | 413 | The upload is over `MAX_UPLOAD_MB` (default 50) |
| `AUDIO_TOO_SHORT` | 422 | Under 5 s |
| `SILENT_AUDIO` | 422 | Below about -80 dBFS RMS |
| `DECODE_FAILED` | 422 | ffmpeg can't read the file |

### `GET /health`
Returns `{"status": "ok"}`.

## Using `pitch_classes` in the autotune agent
`pitch_classes` are the allowed notes, numbered 0–11 (C = 0). Snap each detected pitch to the nearest allowed one:
```python
import numpy as np

def snap_to_key(midi: np.ndarray, pitch_classes: list[int]) -> np.ndarray:
    """midi: detected pitch per frame (float MIDI, NaN = unvoiced) -> target MIDI per frame."""
    allowed = np.array(pitch_classes)
    pc = np.mod(midi, 12)
    diff = (allowed[None, :] - pc[:, None] + 6) % 12 - 6          # signed distance, wraps at the octave
    step = np.take_along_axis(diff, np.nanargmin(np.abs(np.nan_to_num(diff, nan=99)), axis=1)[:, None], 1)[:, 0]
    return midi + step                                              # NaN frames stay NaN

key = requests.post(URL, files={"file": open(path, "rb")}).json()
if key["low_confidence"]:
    ...  # ask the user to confirm key["display_key"] or pick another key before tuning
target = snap_to_key(midi, key["pitch_classes"])
```

## Licensing
**Essentia is AGPL-3.0.** If this service runs as a **public or commercial network service**, you must either open-source this service (including your changes) under the AGPL, or buy Essentia's commercial licence from the MTG (Universitat Pompeu Fabra).

madmom's pretrained key models are deliberately **not** used: their licence is non-commercial.

## Known limitations
- **Relative major/minor confusion** (e.g. A minor vs C major share every note) and **keys a fifth apart** (C vs G) are the most common mistakes. Check `relative_key` and `low_confidence`.
- **Dry vocals** are less reliable than a full mix or instrumental: a solo line rarely states the whole scale. Use `source_type=vocals` so the response carries a warning.
- **Key changes:** a song that modulates returns only the dominant key across the analysed windows.
- **Modes:** only major and natural minor. To add one, add an entry to `MODES` in `app/music_theory.py`.
- **Image size:** the image is about 1 GB, mostly Debian's `ffmpeg` package (~460 MB of libraries).
