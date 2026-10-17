"""Local studio entry point. Run `python main.py`; no frontend build step."""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.bezier_geometry import build_geometry
from core.exporter import export_mp4, export_svg
from core.kolam_graph import plan_grid
from core.mir_extractor import extract_audio, label_analysis

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SVARAKOLAM_DATA", str(ROOT / ".runtime"))).resolve()
MAX_UPLOAD = 32*1024*1024
MAX_SESSIONS = 12
TTL = 24*3600
lock = threading.RLock()
sessions, designs, jobs = {}, {}, {}
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="svarakolam")
log = logging.getLogger("svarakolam")


def cleanup():
    now = time.time()
    with lock:
        expired = [k for k, v in sessions.items() if now-v["created"] > TTL and not v.get("busy")]
        for key in expired:
            sessions.pop(key)
            for design_id in [d for d, v in designs.items() if v["session"] == key]:
                designs.pop(design_id)
            for job_id in [j for j, v in jobs.items() if v["session"] == key]:
                jobs.pop(job_id)
            shutil.rmtree(DATA/key, ignore_errors=True)


@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    # Old artifacts contain user audio. Retain no abandoned runtime directories.
    for child in DATA.iterdir():
        if child.is_dir() and len(child.name) == 32:
            try:
                uuid.UUID(hex=child.name)
            except ValueError:
                continue
            if time.time()-child.stat().st_mtime > TTL:
                shutil.rmtree(child, ignore_errors=True)
    yield
    pool.shutdown(wait=True)


app = FastAPI(title="SvaraKolam", version="1.0.0", lifespan=lifespan)


class Options(BaseModel):
    grid: str = Field(default="ner", pattern="^(ner|idukku)$")
    size: int = Field(default=7, ge=2, le=15)
    mela: int = Field(default=29, ge=1, le=72)
    tonic: float | None = Field(default=None, ge=55, le=1000, allow_inf_nan=False)
    tala: int = Field(default=8, ge=3, le=16)


def require(mapping, key, label):
    with lock:
        value = mapping.get(key)
        if value is None:
            raise HTTPException(404, f"{label} not found or expired. Upload the clip again.")
        return value


def update(job_id, progress, message):
    with lock:
        jobs[job_id].update(progress=round(float(progress), 3), message=message)


def create_design(session_id, options):
    session = require(sessions, session_id, "Session")
    if "raw" not in session:
        raise HTTPException(409, "Audio analysis is still running.")
    analysis = label_analysis(session["raw"], options.tonic, options.mela, options.tala)
    plan = plan_grid(options.size, options.grid, analysis["notes"])
    geometry = build_geometry(plan, analysis)
    design_id = uuid.uuid4().hex
    result = dict(id=design_id, session=session_id, options=options.model_dump(),
                  analysis=analysis, geometry=geometry, audio_url=f"/api/sessions/{session_id}/audio")
    with lock:
        owned = [d for d, v in designs.items() if v["session"] == session_id]
        # Keep a bounded history; never evict a design with an active export.
        for old in owned[:-15]:
            if not any(j.get("design") == old and j["state"] == "running" for j in jobs.values()):
                designs.pop(old, None)
        designs[design_id] = result
    return result


def analyze_worker(session_id, job_id, source, tracker, options):
    try:
        normalized = source.parent/"normalized.wav"
        raw = extract_audio(source, normalized, tracker, lambda p, m: update(job_id, p, m))
        with lock:
            sessions[session_id]["raw"] = raw
        result = create_design(session_id, options)
        with lock:
            jobs[job_id].update(state="complete", progress=1, message="Ready to draw", result=result)
    except Exception as exc:
        log.exception("Audio analysis failed")
        message = str(exc) if isinstance(exc, ValueError) else "Audio analysis failed. Try a clearer solo recording. See server logs for details."
        with lock:
            jobs[job_id].update(state="failed", message=message)
        (source.parent/"normalized.wav").unlink(missing_ok=True)
    finally:
        source.unlink(missing_ok=True)
        with lock:
            sessions[session_id]["busy"] = False


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/preview")
def preview(options: Options):
    # Structural preview contains no audio, fabricated pitches, or musical events.
    return build_geometry(plan_grid(options.size, options.grid, []), {"duration": 1., "notes": []})


@app.post("/api/analyze", status_code=202)
async def analyze(file: UploadFile = File(...), tracker: str = Form("auto")):
    cleanup()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".wav", ".mp3", ".flac", ".ogg"}:
        await file.close()
        raise HTTPException(415, "Choose a WAV, MP3, FLAC, or OGG audio file.")
    if tracker not in {"auto", "pyin", "crepe"}:
        await file.close()
        raise HTTPException(422, "Unknown pitch tracker.")
    session_id, job_id = uuid.uuid4().hex, uuid.uuid4().hex
    with lock:
        if len(sessions) >= MAX_SESSIONS:
            await file.close()
            raise HTTPException(429, "Studio session limit reached. Delete an old session or restart the server.")
        sessions[session_id] = dict(created=time.time(), busy=True)
    folder = DATA/session_id
    folder.mkdir(parents=True)
    source = folder/f"upload{ext}"
    try:
        length = 0
        with source.open("wb") as output:
            while block := await file.read(1024*1024):
                length += len(block)
                if length > MAX_UPLOAD:
                    raise HTTPException(413, "Upload limit is 32 MB.")
                output.write(block)
        if not length:
            raise HTTPException(422, "The uploaded file is empty.")
    except BaseException:
        with lock:
            sessions.pop(session_id, None)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()
    with lock:
        jobs[job_id] = dict(id=job_id, session=session_id, state="running", progress=0,
                            message="Queued for audio analysis")
    pool.submit(analyze_worker, session_id, job_id, source, tracker, Options())
    return {"job": job_id, "session": session_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with lock:
        return dict(require(jobs, job_id, "Job"))


@app.post("/api/sessions/{session_id}/design")
def recompute(session_id: str, options: Options):
    return create_design(session_id, options)


@app.get("/api/sessions/{session_id}/audio")
def audio(session_id: str):
    require(sessions, session_id, "Session")
    path = DATA/session_id/"normalized.wav"
    if not path.exists():
        raise HTTPException(409, "Normalized audio is not ready.")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/designs/{design_id}/svg")
def svg(design_id: str):
    design = require(designs, design_id, "Design")
    path = DATA/design["session"]/f"{design_id}.svg"
    # Build to a unique temporary file and atomically replace for concurrent reads.
    temp = path.with_name(f"{design_id}-{uuid.uuid4().hex}.svg")
    export_svg(design["geometry"], temp)
    temp.replace(path)
    return FileResponse(path, media_type="image/svg+xml", filename="svarakolam.svg")


def video_worker(design, job_id):
    session_id = design["session"]
    path = DATA/session_id/f"{job_id}.mp4"
    try:
        export_mp4(design["geometry"], design["analysis"], DATA/session_id/"normalized.wav", path,
                   lambda p, m: update(job_id, p, m))
        with lock:
            jobs[job_id].update(state="complete", progress=1, message="Video ready",
                               url=f"/api/jobs/{job_id}/video")
    except Exception:
        log.exception("Video export failed")
        with lock:
            jobs[job_id].update(state="failed", message="Video export failed. Check available disk space and server logs.")
    finally:
        with lock:
            sessions[session_id]["busy"] = False


@app.post("/api/designs/{design_id}/mp4", status_code=202)
def video(design_id: str):
    design = require(designs, design_id, "Design")
    with lock:
        for job in jobs.values():
            if job.get("design") == design_id and job["state"] in {"running", "complete"}:
                return {"job": job["id"]}
        if sessions[design["session"]].get("busy"):
            raise HTTPException(409, "This clip already has an export in progress.")
        if sum(j["state"] == "running" for j in jobs.values()) >= 4:
            raise HTTPException(429, "Export queue is full. Try again shortly.")
        job_id = uuid.uuid4().hex
        sessions[design["session"]]["busy"] = True
        jobs[job_id] = dict(id=job_id, session=design["session"], design=design_id,
                            state="running", progress=0, message="Queued for video export")
    pool.submit(video_worker, design, job_id)
    return {"job": job_id}


@app.get("/api/jobs/{job_id}/video")
def video_download(job_id: str):
    job = require(jobs, job_id, "Job")
    if job["state"] != "complete" or "design" not in job:
        raise HTTPException(409, "Video is not ready.")
    return FileResponse(DATA/job["session"]/f"{job_id}.mp4", media_type="video/mp4", filename="svarakolam.mp4")


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    with lock:
        session = require(sessions, session_id, "Session")
        if session.get("busy"):
            raise HTTPException(409, "Wait for analysis or export to finish before deleting.")
        session["created"] = 0
    cleanup()


app.mount("/", StaticFiles(directory=ROOT/"static", html=True), name="static")

if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="SvaraKolam local music and kolam studio")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
