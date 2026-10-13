"""Local web app: http://127.0.0.1:8770

Designed for one person on their own machine. It binds to localhost and
rejects cross-site and non-local requests so a web page you visit cannot
spend your credits or read your keys.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, budget, catalog, config, jobs, media, webhook, workflows
from .providers.base import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT

UPLOAD_FIELDS = {
    "video": VIDEO_EXT,
    "original": VIDEO_EXT | AUDIO_EXT,
    "image": IMAGE_EXT,
    "refs": IMAGE_EXT | VIDEO_EXT,
    "character": IMAGE_EXT,
    "music": AUDIO_EXT,
}
MAX_UPLOAD = 500 * 1024 * 1024
SETTABLE = set(config.KEYS) | {
    "MW_DEFAULT_TIER", "MW_MAX_COST_PER_JOB", "MW_DAILY_BUDGET", "MW_CONFIRM_ABOVE", "MW_MAX_PARALLEL",
    "MW_PLANNER_MODEL", "MW_PLANNER_MODEL_BUDGET", "ENHANCOR_WEBHOOK_URL", "MEDIA_HOST", "MEDIA_HOST_FALLBACKS",
    "CATBOX_USERHASH", "MW_ALLOW_MOCK",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@asynccontextmanager
async def lifespan(_app):
    config.RUNS.mkdir(parents=True, exist_ok=True)
    workflows.resume_all()
    yield


app = FastAPI(title="MotionWorkflow", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if config.setting("MW_ALLOW_REMOTE") != "1":
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS and host != "testserver":
            return JSONResponse({"detail": "MotionWorkflow only answers on localhost."}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD") and origin:
            origin_host = origin.split("://", 1)[-1].rsplit(":", 1)[0]
            if origin_host not in LOCAL_HOSTS:
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
    return await call_next(request)


def _job(job_id: str) -> jobs.Job:
    try:
        return jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


def _public(job: jobs.Job) -> dict:
    data = job.public()
    data["active"] = workflows.is_active(job.id)
    data["spent"] = round(budget.spent_on_job(job.id), 4)
    data.pop("traceback", None)
    return data


# -- pages and files ---------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(config.PACKAGE / "static" / "index.html")


@app.get("/files/{job_id}/{path:path}")
def files(job_id: str, path: str):
    job = _job(job_id)
    target = (job.folder / path).resolve()
    if not target.is_relative_to(job.folder.resolve()) or not target.is_file() or target.name == "job.json":
        raise HTTPException(404)
    return FileResponse(target)


# -- read-only API -------------------------------------------------------------

@app.get("/api/status")
def status():
    try:
        media.ffmpeg()
        ffmpeg_ok = True
    except media.MediaError:
        ffmpeg_ok = False
    return {
        "version": __version__,
        "providers": config.providers_status(),
        "budget": budget.report(),
        "default_tier": config.setting("MW_DEFAULT_TIER"),
        "ffmpeg": ffmpeg_ok,
        "enhancor_webhook": bool(config.setting("ENHANCOR_WEBHOOK_URL") or webhook.current_url()),
    }


@app.get("/api/models")
def models(kind: str | None = None):
    items = catalog.for_kind(kind) if kind else catalog.models()
    return [catalog.summary(m) for m in items]


@app.post("/api/estimate")
async def estimate(request: Request):
    body = await request.json()
    try:
        return workflows.estimate(body.get("workflow", ""), body.get("params") or {}, body.get("counts") or {})
    except (ValueError, config.MissingKey) as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/jobs")
def list_jobs(limit: int = 60):
    return [_public(j) for j in jobs.all_jobs(limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _public(_job(job_id))


# -- actions -----------------------------------------------------------------

def _save_uploads(uploads: dict[str, list[UploadFile]], tmp: Path) -> dict[str, list[Path]]:
    saved: dict[str, list[Path]] = {}
    for field, items in uploads.items():
        allowed = UPLOAD_FIELDS[field]
        for i, upload in enumerate(items):
            if not upload or not upload.filename:
                continue
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in allowed:
                raise HTTPException(400, f"{field}: {suffix or 'this file type'} is not supported here.")
            dest = tmp / f"{field}-{i}{suffix}"
            with dest.open("wb") as out:
                shutil.copyfileobj(upload.file, out)
            if dest.stat().st_size > MAX_UPLOAD:
                raise HTTPException(413, f"{upload.filename} is larger than 500 MB.")
            saved.setdefault(field, []).append(dest)
    return saved


@app.post("/api/jobs")
async def create_job(
    workflow: str = Form(...),
    params: str = Form("{}"),
    confirm: bool = Form(False),
    video: UploadFile | None = File(None),
    original: UploadFile | None = File(None),
    image: UploadFile | None = File(None),
    character: UploadFile | None = File(None),
    music: UploadFile | None = File(None),
    refs: list[UploadFile] | None = File(None),
):
    try:
        values = json.loads(params)
        assert isinstance(values, dict)
    except (ValueError, AssertionError):
        raise HTTPException(400, "params must be a JSON object") from None
    tmp = Path(tempfile.mkdtemp(prefix="upload-", dir=config.RUNS))
    try:
        uploads = {"video": [video], "original": [original], "image": [image], "character": [character],
                   "music": [music], "refs": refs or []}
        saved = _save_uploads(uploads, tmp)
        counts = {k: len(v) for k, v in saved.items()}
        if workflow == "swap" and saved.get("video"):
            values["source_seconds"] = round(media.probe(saved["video"][0])["duration"], 2)
        try:
            quote = workflows.check_start(workflow, values, counts, confirm)
        except workflows.NeedsConfirmation as exc:
            return JSONResponse({"detail": str(exc), "needs_confirmation": True, "quote": exc.quote}, status_code=402)
        except (ValueError, budget.BudgetExceeded, config.MissingKey) as exc:
            raise HTTPException(400, str(exc)) from None
        job = jobs.create(workflow, values, saved)
        job.data["estimate"] = quote
        job.save()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    workflows.start(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/approve")
async def approve(job_id: str, request: Request):
    job = _job(job_id)
    body = await request.json()
    awaiting = job.data.get("awaiting") or {}
    stage = body.get("stage") or awaiting.get("stage")
    if not stage or stage != awaiting.get("stage"):
        raise HTTPException(409, "This job is not waiting for that approval.")
    job.approve(stage, body.get("note", ""))
    workflows.start(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/retry")
async def retry(job_id: str, request: Request):
    job = _job(job_id)
    if workflows.is_active(job.id):
        raise HTTPException(409, "Job is still running.")
    body = await request.json()
    workflows.retry(job, force=bool(body.get("force")))
    workflows.start(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/redo")
async def redo(job_id: str, request: Request):
    job = _job(job_id)
    if workflows.is_active(job.id):
        raise HTTPException(409, "Job is still running.")
    body = await request.json()
    workflows.redo(job, body.get("steps") or [], body.get("overrides") or {})
    workflows.start(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/resume")
def resume(job_id: str):
    job = _job(job_id)
    workflows.start(job)
    return _public(job)


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    job = _job(job_id)
    if workflows.is_active(job.id):
        raise HTTPException(409, "Job is still running.")
    shutil.rmtree(job.folder, ignore_errors=True)
    jobs._live.pop(job.id, None)
    return {"deleted": job_id}


@app.get("/api/settings")
def get_settings():
    return {
        "keys": {k: config.has_key(k) for k in config.KEYS},
        "settings": {k: config.setting(k) for k in sorted(SETTABLE - set(config.KEYS) - {"CATBOX_USERHASH"})},
    }


@app.post("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    updates = {}
    for name, value in {**(body.get("keys") or {}), **(body.get("settings") or {})}.items():
        if name not in SETTABLE:
            raise HTTPException(400, f"{name} cannot be set here.")
        value = str(value).strip()
        if "\n" in value or "\r" in value:
            raise HTTPException(400, f"{name} must be a single line.")
        if value or name not in config.KEYS:
            updates[name] = value
    if updates:
        config.save_keys(updates)
    return get_settings()


def main(host: str = "127.0.0.1", port: int = 8770) -> None:
    import uvicorn

    print(f"MotionWorkflow running at http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
