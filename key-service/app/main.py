"""Key-detection microservice: POST /detect-key, GET /health."""
import os
import tempfile
import time
from typing import Literal

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import music_theory as mt
from app.audio_io import AudioError, check_extension, decode, max_upload_bytes, too_large
from app.detector import detect
from app.schemas import ErrorResponse, KeyResult

LOW_CONFIDENCE: float = 0.6
VOCALS_WARNING = ("Key detection on dry vocals is less reliable than on a full mix or instrumental; "
                  "confirm the key before autotuning.")
SourceType = Literal["full_mix", "instrumental", "vocals"]

app = FastAPI(title="key-service", version="1.0.0")


@app.middleware("http")
async def cap_request_body(request: Request, call_next):
    """Refuse oversized uploads from the declared size, before the multipart body is read and spooled."""
    if request.method == "POST":
        n = request.headers.get("content-length")
        if n is None:
            return JSONResponse(status_code=411, content={"error": {"code": "LENGTH_REQUIRED",
                                                                    "message": "Content-Length header required."}})
        if not n.isdigit() or int(n) > max_upload_bytes() + 1024 * 1024:   # +1 MB multipart overhead
            e = too_large()
            return JSONResponse(status_code=e.status, content={"error": {"code": e.code, "message": e.message}})
    return await call_next(request)


@app.exception_handler(AudioError)
async def audio_error_handler(_: Request, exc: AudioError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _save_upload(upload: UploadFile, ext: str) -> str:
    """Stream to a temp file, stopping as soon as the size limit is passed."""
    limit, size = max_upload_bytes(), 0
    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await upload.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise too_large()
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return path


def _analyze(path: str, source_type: SourceType | None) -> KeyResult:
    started = time.perf_counter()
    found = detect(decode(path))
    warnings = [VOCALS_WARNING] if source_type == "vocals" else []
    return KeyResult(
        key=found.key, scale=found.scale,
        key_string=f"{found.key} {found.scale}",
        display_key=mt.display_key(found.key, found.scale),
        confidence=found.confidence,
        agreement=f"{found.agreeing}/{found.profiles}",
        scale_notes=mt.scale_notes(found.key, found.scale),
        pitch_classes=mt.pitch_classes(found.key, found.scale),
        relative_key=mt.relative_key(found.key, found.scale),
        low_confidence=found.confidence < LOW_CONFIDENCE or found.agreeing <= 1,
        warnings=warnings,
        analysis_seconds=round(time.perf_counter() - started, 2),
    )


@app.post("/detect-key", response_model=KeyResult,
          responses={c: {"model": ErrorResponse} for c in (413, 415, 422)})
async def detect_key(file: UploadFile = File(...), source_type: SourceType | None = None) -> KeyResult:
    path = await _save_upload(file, check_extension(file.filename))
    try:
        return await run_in_threadpool(_analyze, path, source_type)   # Essentia is CPU-bound
    finally:
        os.unlink(path)
