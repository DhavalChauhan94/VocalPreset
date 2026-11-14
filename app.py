"""VocalPreset API + serves the built React app (web/dist).

  POST /api/jobs        vocal, part, sound, key, [beat]  -> {id}
  GET  /api/jobs/{id}   live progress: stage, current plugin, key, bpm, result urls
  GET  /api/sounds      decoded FL presets with their plugin chains
Run:  .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
"""
import os
import shutil
import tempfile
import threading
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import analysis
import engine
import fixer
import keys
import restore

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "jobs")          # generated mp3/wav, served by /api/file
TAKES = os.path.join(HERE, "out", "takes")       # raw uploads: never served
# Only our own render names can be downloaded, never an uploaded file (stops stored HTML/SVG from our origin).
_SERVABLE = re.compile(r"^[0-9a-f]{12}(_raw|_v\d{1,4})?\.(mp3|wav)$|^[0-9a-f]{12}_s[01]\.flac$")
_MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac"}   # not the OS registry's guess
_MEDIA_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".mpeg", ".mp4", ".mov", ".webm", ".3gp", ".amr", ".wma", ".aiff", ".aif"}
DIST = os.path.join(HERE, "web", "dist")
os.makedirs(OUT, exist_ok=True)
os.makedirs(TAKES, exist_ok=True)
MAX_MB = 80
JOBS: dict[str, dict] = {}

@asynccontextmanager
async def _lifespan(_app):
    """Jobs live in memory, so after a restart no one can reach the old renders or uploads: delete them
    (the folder otherwise grew ~0.6 GB a day, and it holds copies of people's vocals)."""
    for folder in (OUT, TAKES):
        for name in os.listdir(folder):
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:      # a sub-folder or a file still open elsewhere: leave it
                pass
    yield


app = FastAPI(title="VocalPreset", lifespan=_lifespan)


@app.middleware("http")
async def cap_request_body(request: Request, call_next):
    """Refuse oversized POSTs from their declared size, before the multipart body is read and spooled to disk."""
    if request.method == "POST":
        n = request.headers.get("content-length")
        if n is None:
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        if not n.isdigit() or int(n) > (MAX_MB + 2) * 1024 * 1024:     # +2 MB: multipart overhead and a beat
            return JSONResponse({"detail": f"File over {MAX_MB} MB"}, status_code=413)
    return await call_next(request)


def _save_upload(up: UploadFile, folder: str) -> str:
    ext = os.path.splitext(up.filename or "")[1][:8] or ".bin"
    path = os.path.join(folder, uuid.uuid4().hex + ext)
    with open(path, "wb") as f:
        shutil.copyfileobj(up.file, f, length=1 << 20)
    if os.path.getsize(path) > MAX_MB * 1024 * 1024:
        os.unlink(path)
        raise HTTPException(413, f"File over {MAX_MB} MB")
    return path


def _ffmp3(src, dst, kbps=320, title=None):
    """MP3 that every phone and chat app plays: 44.1 kHz CBR, ID3v2.3 (+v1) tags; WhatsApp and older Android
    players skip the v2.4 tags ffmpeg writes by default."""
    tags = ["-metadata", f"title={title}"] if title else []
    engine.run_ffmpeg([*engine.ffmpeg_input(src), "-vn", "-ac", "2", "-ar", str(engine.SR), "-c:a", "libmp3lame",
                       "-b:a", f"{kbps}k", "-id3v2_version", "3", "-write_id3v1", "1", *tags, dst])


def _title(filename):
    """The upload's name, made safe for a download name and a tag: "Recording (154).wav" -> "Recording (154)"."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    return re.sub(r"[^\w \-()]+", "", stem, flags=re.ASCII).strip()[:60] or "vocal"


def _download_name(t, ext):
    return f"{t.get('title', 'vocal')} - {fixer.STYLES[t.get('style', fixer.DEFAULT_STYLE)]['file']} mix.{ext}"


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
            rep = fixer.visible(analysis.analyze(t["input"]))
            t.update(analysis=rep, score=fixer.score(rep),
                     lufs_raw=rep.get("loudness", {}).get("integrated_lufs"))
        except Exception as e:   # the fix still works without a report (generic polish)
            t["analysis_error"] = str(e)[:300] or type(e).__name__
        t.update(plan=fixer.plan(t.get("analysis")), status="analysed", stage="Analysed")
    except Exception as e:      # undecodable upload; the raw error holds server paths, so log it, don't send it
        print(f"take {tid}: {e}")
        t.update(status="error", error="We couldn't read this file as audio. Try an mp3, wav, m4a or a voice note.")
    if tid in RESTORING:        # after the analysis, not alongside: together they pushed Phantom past its 60 s timeout
        _restore_take(tid)


RESTORING: dict[str, threading.Event] = {}   # take id -> set once its AI restoration finished (or failed)


def _restore_take(tid):
    """Runs right after the upload's analysis, so it's usually done by the time the user has picked a sound and pressed Fix."""
    t = JOBS[tid]
    out = os.path.join(TAKES, f"{tid}_restored.wav")
    try:
        restore.restore(t["input"], out)
        t["restored"] = out
    except Exception as e:      # the fix still runs, on the original take
        print(f"restore {tid}: {e}")
    finally:
        RESTORING[tid].set()


def _fix_take(tid, autotune, key, style):
    t = JOBS[tid]

    def progress(kind, **kw):
        if kind == "plugin":
            t.update(stage=kw["plugin"], slot=kw["slot"])
        elif kind == "meta":
            t.update({k: v for k, v in kw.items() if v is not None})

    try:
        steps = fixer.plan(t.get("analysis"), autotune, key, style, restore=tid in RESTORING)
        t.update(steps=steps, chain=[s["label"] for s in steps], slot=0)
        if tid in RESTORING and not RESTORING[tid].is_set():
            t.update(stage="Restoring your recording (AI)")
            RESTORING[tid].wait()
        wav = os.path.join(OUT, f"{tid}.wav")
        dry = os.path.join(TAKES, f"{tid}_dry.wav")      # no reverb: Phantom hears reverb tails as noise
        t.update(settings=fixer.settings(style=style), mix_version=0)  # each "Fix" starts from the style's one-click mix
        stems = [os.path.join(OUT, f"{tid}_s{i}.flac") for i in (0, 1)]   # for the live Mix rack in the browser
        duck = fixer.fix(t.get("restored", t["input"]), wav, steps, progress, dry_path=dry, stem_paths=stems, style=style)
        t.update(stems=[f"/api/file/{tid}_s{i}.flac?t={int(time.time())}" for i in (0, 1)],
                 duck=np.round(duck, 4).tolist(), fx=fixer.FX)
        t.update(stage="Checking the result", slot=len(steps))
        _ffmp3(wav, wav[:-4] + ".mp3", title=_download_name(t, "mp3")[:-4])
        y, _ = engine.sf.read(wav, always_2d=True)
        t.update(lufs_out=round(float(engine.lufs(y.T)), 2), peaks_after=_peaks(wav),
                 wav=f"/api/file/{tid}.wav?t={int(time.time())}", mp3=f"/api/file/{tid}.mp3?t={int(time.time())}")   # ?t: re-fix = new URL, no stale cache
        try:
            tuned = t.get("key") if autotune != "off" else None   # key auto-tune actually used
            after = fixer.visible(analysis.analyze(dry), tuned_key=tuned)
            t.update(analysis_after=after, score_after=fixer.score(after, t.get("analysis")),
                     fixed=fixer.fixed(t.get("analysis"), after))
        except Exception as e:
            t["analysis_after_error"] = str(e)[:300] or type(e).__name__
        t.update(status="done", stage="Done", seconds=round(time.time() - t["t_fix"], 1))
    except Exception as e:
        t.update(status="error", error=str(e)[:300])


def _mix_take(tid, version, s):
    """Export: render the exact Mix-rack settings from the stems (the browser plays them live)."""
    t = JOBS[tid]
    try:
        s0, s1 = (fixer.read_stem(os.path.join(OUT, f"{tid}_s{i}.flac")) for i in (0, 1))
        name = f"{tid}_v{version}"
        wav = os.path.join(OUT, f"{name}.wav")
        fixer.render(s0, s1, np.asarray(t["duck"], dtype=np.float32), s, wav)
        if t.get("mix_version") != version:       # a newer export arrived meanwhile: drop this one
            os.unlink(wav)
            return
        _ffmp3(wav, wav[:-4] + ".mp3", title=_download_name(t, "mp3")[:-4])
        y, _ = engine.sf.read(wav, always_2d=True)
        old = [t.get("wav"), t.get("mp3")]
        t.update(settings=s, lufs_out=round(float(engine.lufs(y.T)), 2),
                 wav=f"/api/file/{name}.wav", mp3=f"/api/file/{name}.mp3", status="done", stage="Done")
        for url in old:                           # previous export's files (never the original render)
            if url and "_v" in url:
                try:
                    os.unlink(os.path.join(OUT, url.rsplit("/", 1)[1]))
                except OSError:
                    pass
    except Exception as e:
        if t.get("mix_version") == version:
            print(f"mix {tid}: {e}")
            t.update(status="done", stage="Done", mix_error="Couldn't export that mix. Try again.")


@app.get("/api/ir/{style}.wav")
def reverb_ir(style: str):
    """Reverb impulse responses for the browser's ConvolverNode: the same ones the server renders with."""
    if style not in fixer.REVERB_STYLES:
        raise HTTPException(404)
    return FileResponse(os.path.join(fixer.IR_DIR, f"{style}.wav"), media_type="audio/wav")


@app.post("/api/takes")
async def create_take(vocal: UploadFile = File(...)):
    tid = uuid.uuid4().hex[:12]
    ext = os.path.splitext(vocal.filename or "")[1].lower()
    ext = ext if ext in _MEDIA_EXT else ".bin"   # ffmpeg sniffs the content; the name is only a hint
    path = _save_upload(vocal, TAKES)
    final = os.path.join(TAKES, f"{tid}_in{ext}")   # shortcut: cleared only on restart (_lifespan); add a TTL before going public
    os.replace(path, final)
    JOBS[tid] = {"id": tid, "input": final, "title": _title(vocal.filename), "status": "analysing", "stage": "Listening to your take",
                 "slot": None, "t0": time.time()}
    if restore.available():
        RESTORING[tid] = threading.Event()
    threading.Thread(target=_analyse_take, args=(tid,), daemon=True).start()
    return {"id": tid}


@app.post("/api/takes/{tid}/key")
def take_key(tid: str, beat: UploadFile | None = File(None)):
    """Key for auto-tune from the vocal, or (most accurate) from the beat the user adds."""
    t = _take(tid, "analysed", "done")
    if beat is not None and beat.filename:
        ext = os.path.splitext(beat.filename)[1].lower()
        path = _save_upload(beat, TAKES)
        t["beat"] = os.path.join(TAKES, f"{tid}_beat{ext if ext in _MEDIA_EXT else '.bin'}")   # never served
        os.replace(path, t["beat"])
    try:
        t["key_info"] = keys.detect(t["input"], t.get("beat"))
    except ValueError as e:      # silent audio / no sung notes
        raise HTTPException(422, str(e))
    return t["key_info"]


_KEY_RE = re.compile(r"^[A-G]#? (major|minor)$")


class FixRequest(BaseModel):
    autotune: Literal["off", "light", "medium", "heavy"] = "off"
    key: str | None = None
    style: Literal["rap", "melodic", "pop"] = fixer.DEFAULT_STYLE   # the vocal sound: see fixer.STYLES


@app.post("/api/takes/{tid}/fix")
def take_fix(tid: str, req: FixRequest):
    t = _take(tid, "analysed", "done", "error")
    if "plan" not in t:          # analysis stage never finished (e.g. undecodable file)
        raise HTTPException(409, "analyse the take first")
    if req.key is not None and not _KEY_RE.match(req.key):
        raise HTTPException(422, 'key must look like "A minor" or "F# major"')
    for k in ("analysis_after", "analysis_after_error", "score_after", "fixed", "error", "key"):
        t.pop(k, None)
    t.update(status="fixing", stage="Planning the fix", t_fix=time.time(), autotune=req.autotune, style=req.style,
             style_label=fixer.STYLES[req.style]["label"])
    threading.Thread(target=_fix_take, args=(tid, req.autotune, req.key, req.style), daemon=True).start()
    return {"id": tid}


class MixRequest(BaseModel):
    mix: float | None = None
    reverb: float | None = None
    reverb_style: str | None = None
    delay: float | None = None
    delay_style: str | None = None
    feedback: float | None = None
    width: float | None = None
    mod: float | None = None
    brightness: float | None = None
    warmth: float | None = None
    reset: bool = False          # back to the one-click mix


@app.post("/api/takes/{tid}/mix")
def take_mix(tid: str, req: MixRequest):
    t = _take(tid, "done", "mixing")
    if "duck" not in t:
        raise HTTPException(409, "fix the take first")
    style = t.get("style")
    s = fixer.settings(style=style) if req.reset else fixer.settings(
        {**t.get("settings", {}), **req.model_dump(exclude_none=True, exclude={"reset"})}, style)   # clamps + validates
    version = t.get("mix_version", 0) + 1
    t.update(status="mixing", stage="Exporting your mix", mix_version=version, mix_error=None)
    threading.Thread(target=_mix_take, args=(tid, version, s), daemon=True).start()
    return {"version": version, "settings": s}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404)
    j = dict(JOBS[job_id])
    j["elapsed"] = round(time.time() - j.pop("t_fix", j.pop("t0")), 1)
    j.pop("t0", None)
    for k in ("input", "beat", "restored"):   # server paths, not for the client
        j.pop(k, None)
    if "style" in j:
        j["names"] = {ext: _download_name(j, ext) for ext in ("mp3", "wav")}
    return j


@app.get("/api/file/{name}")
def file(name: str):
    if not _SERVABLE.match(name):
        raise HTTPException(404)
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        raise HTTPException(404)
    ext = name.rsplit(".", 1)[1]
    t = JOBS.get(name[:12], {})
    nice = _download_name(t, ext) if ext in ("mp3", "wav") and "_raw" not in name and "style" in t else f"vocalpreset-{name}"
    # both forms: filename* for browsers, plain filename for older download managers (nice is ASCII: see _title)
    disp = f"attachment; filename=\"{nice}\"; filename*=utf-8''{quote(nice)}"
    return FileResponse(path, media_type=_MIME[ext], headers={"Content-Disposition": disp})


if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
