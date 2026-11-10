"""VocalPreset API + serves the built React app (web/dist).

  POST /api/jobs        vocal, part, sound, key, [beat]  -> {id}
  GET  /api/jobs/{id}   live progress: stage, current plugin, key, bpm, result urls
  GET  /api/sounds      decoded FL presets with their plugin chains
Run:  .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
"""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import analysis
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "jobs")
DIST = os.path.join(HERE, "web", "dist")
os.makedirs(OUT, exist_ok=True)
MAX_MB = 80
JOBS: dict[str, dict] = {}

app = FastAPI(title="VocalPreset")


def _save_upload(up: UploadFile, folder: str) -> str:
    ext = os.path.splitext(up.filename or "")[1][:8] or ".bin"
    path = os.path.join(folder, uuid.uuid4().hex + ext)
    with open(path, "wb") as f:
        shutil.copyfileobj(up.file, f, length=1 << 20)
    if os.path.getsize(path) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File over {MAX_MB} MB")
    return path


def _ffmp3(src, dst, kbps=320):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "2",
                    "-b:a", f"{kbps}k", dst], check=True)


def _peaks(path, n=600):
    """Downsampled waveform for the UI (max abs per bucket, 0..1)."""
    x = engine.load(path).mean(axis=0)
    x = x[: len(x) // n * n].reshape(n, -1)
    return np.round(np.abs(x).max(axis=1), 3).tolist()


def _run(job_id, tmp, vocal, beat, part, sound, key):
    job = JOBS[job_id]

    def progress(kind, **kw):
        if kind == "stage":
            job["stage"] = kw["name"]
        elif kind == "plugin":
            job["stage"] = kw["plugin"]
            job["slot"] = kw["slot"]
        elif kind == "meta":
            job.update({k: v for k, v in kw.items() if v is not None})

    try:
        job["stage"] = "Analysing the raw take"
        try:   # Phantom report for the next step; never allowed to block the mix
            job["analysis"] = analysis.analyze(vocal)
        except Exception as e:
            job["analysis_error"] = str(e)[:300] or type(e).__name__
        wav = os.path.join(OUT, f"{job_id}.wav")
        engine.process(vocal, part, wav, beat, sound, key, progress)
        job["stage"] = "Encoding"
        _ffmp3(wav, wav[:-4] + ".mp3")
        _ffmp3(vocal, os.path.join(OUT, f"{job_id}_raw.mp3"), 192)
        y, _ = engine.sf.read(wav, always_2d=True)
        job.update({
            "lufs_out": round(float(engine.lufs(y.T)), 2),
            "peaks_before": _peaks(vocal), "peaks_after": _peaks(wav),
            "wav": f"/api/file/{job_id}.wav", "mp3": f"/api/file/{job_id}.mp3",
            "raw": f"/api/file/{job_id}_raw.mp3", "mixed": bool(beat),
            "status": "done", "stage": "Done", "seconds": round(time.time() - job["t0"], 1),
        })
    except Exception as e:  # undecodable upload etc.
        job.update({"status": "error", "error": str(e)[:300]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/api/sounds")
def sounds():
    out = []
    for sid, meta in engine.SOUNDS.items():
        p = engine.load_sound(sid)
        live = [s for s in p["chain"] if s["enabled"]]
        out.append({"id": sid, **meta,
                    "chain": [s["plugin"] for s in live],
                    # plugins in the FL chain the engine can't rebuild yet (skipped when rendering)
                    "skipped": [s["plugin"] for s in live if s["type"] == "unknown"],
                    "autotune": any(s["type"] == "pitcher" for s in live)})
    return {"sounds": out, "parts": list(engine.ROLE)}


@app.post("/api/jobs")
async def create_job(vocal: UploadFile = File(...), part: str = Form("lead"),
                     sound: str = Form("studio_air"), key: str = Form("auto"),
                     beat: UploadFile | None = File(None)):
    if part not in engine.ROLE or sound not in engine.SOUNDS:
        raise HTTPException(400, "unknown part or sound")
    tmp = tempfile.mkdtemp()
    v = _save_upload(vocal, tmp)
    b = _save_upload(beat, tmp) if beat and beat.filename else None
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "status": "running", "stage": "Queued", "slot": None,
                    "sound": sound, "part": part, "t0": time.time()}
    threading.Thread(target=_run, args=(job_id, tmp, v, b, part, sound, key),
                     daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404)
    j = dict(JOBS[job_id])
    j["elapsed"] = round(time.time() - j.pop("t0"), 1)
    return j


@app.get("/api/file/{name}")
def file(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400)
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, filename=f"vocalpreset-{name}")


if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
