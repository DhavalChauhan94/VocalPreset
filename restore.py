"""AI restoration: a phone / laptop / bedroom take -> a booth-like dry vocal, before the studio chain.
MelBand-Roformer de-noise (aufr33) -> de-reverb (anvuew), run by audio-separator. With the pro chain (pro.py, ir/) it
won the owner's blind A/B on 2026-11-13 (7 of 9 clips). Optional: without audio-separator or the models, takes skip it.

    python restore.py --download        # fetch the two models (~0.9 GB each) into models/ (git-ignored)

Speed (measured): ~7x the take's length on a 6-core laptop CPU, ~1.2-1.8x on an RTX 3050 laptop GPU (SETUP.md).
"""
import importlib.util
import logging
import os
import shutil
import sys
import tempfile
import threading

import engine

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
# (checkpoint, stem we keep, overlap). De-noise overlap 4 -> 2: 1.7x faster, output changes by -59 dB (inaudible).
MODELS = (("denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt", "(dry)", 2),
          ("dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt", "(noreverb)", None))
_LOCK = threading.Lock()     # one take at a time: two runs at once ran a 16 GB PC out of memory
_SEPS = {}                   # loaded models, kept between takes (loading one takes ~10 s)


def available():
    return (importlib.util.find_spec("audio_separator") is not None
            and all(os.path.exists(os.path.join(MODEL_DIR, m)) for m, _, _ in MODELS))


def _separator(model, overlap):
    if model not in _SEPS:
        from audio_separator.separator import Separator    # imports torch: only when restoration is used
        sep = Separator(log_level=logging.WARNING, model_file_dir=MODEL_DIR, output_format="WAV",
                        mdxc_params={"segment_size": 256, "override_model_segment_size": False, "batch_size": None,
                                     "overlap": overlap, "pitch_shift": 0})
        sep.load_model(model_filename=model)                # downloads the model if it's missing
        _SEPS[model] = sep
    return _SEPS[model]


def restore(in_path, out_path):
    """Write the restored take to out_path (mono float wav at engine.SR)."""
    with _LOCK:
        work = tempfile.mkdtemp(prefix="vp-restore-")
        try:
            cur = os.path.join(work, "take.wav")
            # decode with our hardened ffmpeg (protocol/format whitelists), never the separator's own loader
            engine.sf.write(cur, engine.load(in_path).mean(axis=0), engine.SR, subtype="FLOAT")
            for model, keep, overlap in MODELS:
                sep = _separator(model, overlap)
                sep.output_dir = sep.model_instance.output_dir = work
                outs = sep.separate(cur)
                cur = os.path.join(work, os.path.basename(next(o for o in outs if keep in o)))
            y = engine.sf.read(cur, dtype="float32", always_2d=True)[0].mean(axis=1)
            engine.sf.write(out_path, y, engine.SR, subtype="FLOAT")
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__" and sys.argv[1:] == ["--download"]:
    for m, _, ov in MODELS:
        _separator(m, ov)
        print("ready:", m)
