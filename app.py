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
import re
import time
import uuid
from typing import Literal

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import analysis
import engine
import fixer
import keys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "jobs")          # generated mp3/wav, served by /api/file
TAKES = os.path.join(HERE, "out", "takes")       # raw uploads: never served
# Only our own render names can be downloaded, never an uploaded file (stops stored HTML/SVG from our origin).
_SERVABLE = re.compile(r"^[0-9a-f]{12}(_raw)?\.(mp3|wav)$")
_MEDIA_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mpeg", ".mp4", ".mov", ".webm", ".3gp", ".amr", ".wma", ".aiff", ".aif"}
DIST = os.path.join(HERE, "web", "dist")
os.makedirs(OUT, exist_ok=True)
os.makedirs(TAKES, exist_ok=True)
MAX_MB = 80
JOBS: dict[str, dict] = {}

app = FastAPI(title="VocalPreset")


def _save_upload(up: UploadFile, folder: str) -> str:
    ext = os.path.splitext(up.filename or "")[1][:8] or ".bin"
    path = os.path.join(folder, uuid.uuid4().hex + ext)
    with open(path, "wb") as f:
        shutil.copyfileobj(up.file, f, length=1 << 20)
    if os.path.getsize(path) > MAX_MB * 1024 * 1024:
        os.unlink(path)
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


# ---------- take flow: analyse -> (key for auto-tune) -> fix ----------

def _take(take_id, *ok_status):
    t = JOBS.get(take_id)
    if not t or "input" not in t:
        raise HTTPException(404, "unknown take")
    if ok_status and t["status"] not in ok_status:
        raise HTTPException(409, f"take is {t['status']}")
    return t


def _analyse_take(tid):
    t = JOBS[tid]
    try:
        t["peaks_before"] = _peaks(t["input"])
        _ffmp3(t["input"], os.path.join(OUT, f"{tid}_raw.mp3"), 192)
        t["raw"] = f"/api/file/{tid}_raw.mp3"
        try:
            rep = analysis.analyze(t["input"])
            t.update(analysis=rep, score=fixer.score(rep),
                     lufs_raw=rep.get("loudness", {}).get("integrated_lufs"))
        except Exception as e:   # the fix still works without a report (generic polish)
            t["analysis_error"] = str(e)[:300] or type(e).__name__
        t.update(plan=fixer.plan(t.get("analysis")), status="analysed", stage="Analysed")
    except Exception as e:      # undecodable upload; the raw error holds server paths, so log it, don't send it
        print(f"take {tid}: {e}")
        t.update(status="error", error="We couldn't read this file as audio. Try an mp3, wav, m4a or a voice note.")


def _fix_take(tid, autotune, key):
    t = JOBS[tid]

    def progress(kind, **kw):
        if kind == "plugin":
            t.update(stage=kw["plugin"], slot=kw["slot"])
        elif kind == "meta":
            t.update({k: v for k, v in kw.items() if v is not None})

    try:
        steps = fixer.plan(t.get("analysis"), autotune, key)
        t.update(steps=steps, chain=[s["label"] for s in steps], slot=0)
        wav = os.path.join(OUT, f"{tid}.wav")
        fixer.fix(t["input"], wav, steps, progress)
        t.update(stage="Checking the result", slot=len(steps))
        _ffmp3(wav, wav[:-4] + ".mp3")
        y, _ = engine.sf.read(wav, always_2d=True)
        t.update(lufs_out=round(float(engine.lufs(y.T)), 2), peaks_after=_peaks(wav),
                 wav=f"/api/file/{tid}.wav", mp3=f"/api/file/{tid}.mp3")
        try:
            after = analysis.analyze(wav)
            t.update(analysis_after=after, score_after=fixer.score(after, t.get("analysis")),
                     fixed=fixer.fixed(t.get("analysis"), after))
        except Exception as e:
            t["analysis_after_error"] = str(e)[:300] or type(e).__name__
        t.update(status="done", stage="Done", seconds=round(time.time() - t["t_fix"], 1))
    except Exception as e:
        t.update(status="error", error=str(e)[:300])


@app.post("/api/takes")
async def create_take(vocal: UploadFile = File(...)):
    tid = uuid.uuid4().hex[:12]
    ext = os.path.splitext(vocal.filename or "")[1].lower()
    ext = ext if ext in _MEDIA_EXT else ".bin"   # ffmpeg sniffs the content; the name is only a hint
    path = _save_upload(vocal, TAKES)
    final = os.path.join(TAKES, f"{tid}_in{ext}")   # shortcut: no TTL cleanup of takes yet; add before going public
    os.replace(path, final)
    JOBS[tid] = {"id": tid, "input": final, "status": "analysing", "stage": "Listening to your take",
                 "slot": None, "t0": time.time()}
    threading.Thread(target=_analyse_take, args=(tid,), daemon=True).start()
    return {"id": tid}


@app.post("/api/takes/{tid}/key")
def take_key(tid: str):
    t = _take(tid, "analysed", "done")
    try:
        t["key_info"] = keys.detect(t["input"])
    except ValueError as e:      # silent audio
        raise HTTPException(422, str(e))
    return t["key_info"]


_KEY_RE = re.compile(r"^[A-G]#? (major|minor)$")


class FixRequest(BaseModel):
    autotune: Literal["off", "light", "medium", "heavy"] = "off"
    key: str | None = None


@app.post("/api/takes/{tid}/fix")
def take_fix(tid: str, req: FixRequest):
    t = _take(tid, "analysed", "done", "error")
    if "plan" not in t:          # analysis stage never finished (e.g. undecodable file)
        raise HTTPException(409, "analyse the take first")
    if req.key is not None and not _KEY_RE.match(req.key):
        raise HTTPException(422, 'key must look like "A minor" or "F# major"')
    for k in ("analysis_after", "analysis_after_error", "score_after", "fixed", "error", "key"):
        t.pop(k, None)
    t.update(status="fixing", stage="Planning the fix", t_fix=time.time(), autotune=req.autotune)
    threading.Thread(target=_fix_take, args=(tid, req.autotune, req.key), daemon=True).start()
    return {"id": tid}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404)
    j = dict(JOBS[job_id])
    j["elapsed"] = round(time.time() - j.pop("t_fix", j.pop("t0")), 1)
    j.pop("t0", None)
    j.pop("input", None)   # server path, not for the client
    return j


@app.get("/api/file/{name}")
def file(name: str):
    if not _SERVABLE.match(name):
        raise HTTPException(404)
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, filename=f"vocalpreset-{name}")


if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
