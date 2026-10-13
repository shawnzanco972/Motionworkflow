"""Local web app: http://127.0.0.1:8770

Designed for one person on their own machine. It binds to localhost and
rejects cross-site and non-local requests so a web page you visit cannot
spend your credits or read your keys.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import (__version__, budget, catalog, config, genjutsu, jobs, library, media, pricing, validation, webhook,
               workflows)
from .providers.base import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT

UPLOAD_FIELDS = {
    "video": VIDEO_EXT,
    "original": VIDEO_EXT | AUDIO_EXT,
    "image": IMAGE_EXT,
    "refs": IMAGE_EXT | VIDEO_EXT,
    "character": IMAGE_EXT,
    "music": AUDIO_EXT,
    "avatar": IMAGE_EXT | VIDEO_EXT,
    "voice_sample": AUDIO_EXT | VIDEO_EXT,
}
MAX_UPLOAD = 500 * 1024 * 1024
SETTABLE = set(config.KEYS) | {
    "MW_DEFAULT_TIER", "MW_MAX_COST_PER_JOB", "MW_DAILY_BUDGET", "MW_CONFIRM_ABOVE", "MW_MAX_PARALLEL",
    "MW_PLANNER_MODEL", "MW_PLANNER_MODEL_BUDGET", "MW_REVIEWER_MODEL", "MW_REVIEWER_MODEL_BUDGET", "ENHANCOR_WEBHOOK_URL", "MEDIA_HOST", "MEDIA_HOST_FALLBACKS",
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


def _title(job: jobs.Job) -> str:
    p = job.params
    plan = job.data.get("plan") or {}
    for value in (plan.get("title"), p.get("topic"), p.get("idea"), p.get("prompt"), p.get("text"), (p.get("script") or "")[:80]):
        if value and str(value).strip():
            return str(value).strip()[:90]
    return {"swap": "Character swap", "presenter": "Presenter video"}.get(job.data["workflow"], job.data["workflow"].title())


def _thumb(data: dict) -> str | None:
    outputs = data.get("outputs", [])
    for pick in (lambda o: o["path"] == "thumbnail.jpg", lambda o: o["label"] == "Shot 1 keyframe",
                 lambda o: o["kind"] == "image"):
        found = next((o for o in outputs if pick(o)), None)
        if found:
            return found["url"]
    for field in ("avatar", "image", "character", "refs"):  # before any output exists
        for rel in data.get("inputs", {}).get(field, []):
            if rel.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                return f"/files/{data['id']}/{rel}"
    return None


def _public(job: jobs.Job, ledger: list[dict] | None = None, full: bool = True) -> dict:
    """A job as the browser sees it. Lists pass the job's ledger rows in (read once) and skip the detail."""
    data = job.public()
    if ledger is None:
        ledger = budget.job_entries(job.id)
    data["active"] = workflows.is_active(job.id)
    data["spent"] = round(sum(r.get("usd", 0) for r in ledger), 4)
    data["title"] = _title(job)
    data["thumb"] = _thumb(data)
    data["cost"] = _cost(job, data, ledger) if full else {
        "estimate": (data.get("estimate") or {}).get("total"), "spent": data["spent"],
        "next": (data.get("awaiting") or {}).get("estimate")}
    data.pop("traceback", None)
    if not full:
        data.pop("log", None)
    return data


def _cost(job: jobs.Job, data: dict, ledger: list[dict]) -> dict:
    """Planned vs spent, per step, plus what the next approval will cost."""
    per_step: dict[str, float] = {}
    for row in ledger:
        key = budget.step_of(row.get("note", ""))
        per_step[key] = per_step.get(key, 0) + row.get("usd", 0)
    steps = []
    for key, step in job.data.get("steps", {}).items():
        steps.append({"key": key, "label": step.get("label") or key, "model": step.get("model"),
                      "state": step.get("state"), "estimate": step.get("estimate"),
                      "spent": round(per_step.pop(key, 0.0), 4)})
    for key, usd in per_step.items():  # e.g. prep, review
        if abs(usd) > 1e-9:
            steps.append({"key": key, "label": {"review": "Fresh-eyes review", "prep": "Genjutsu prep"}.get(key, key),
                          "model": None, "state": "done", "estimate": None, "spent": round(usd, 4)})
    quote = data.get("estimate") or {}
    awaiting = data.get("awaiting") or {}
    spent = round(sum(r.get("usd", 0) for r in ledger), 4)
    return {
        "estimate": quote.get("total"),
        "planned": quote.get("items", []),
        "spent": spent,
        "next": awaiting.get("estimate"),
        "steps": steps,
        "ledger": ledger[::-1],
        "mock": bool(job.data.get("used_mock")),
    }


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


app.mount("/static", StaticFiles(directory=config.PACKAGE / "static"), name="static")


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
        "skills": {
            "take_one": (config.ROOT / ".claude" / "skills" / "take-one" / "SKILL.md").exists(),
            "genjutsu": genjutsu.status(),
        },
        "library": {kind: len(library.items(kind)) for kind in library.KINDS},
        "jobs": _job_counts(),
        "attention": _attention(),
    }


def _attention() -> list[dict]:
    """Projects that just need you (approval) or just finished/failed, newest first, for notifications."""
    out = []
    for job in jobs.all_jobs(100):
        state = job.data["state"]
        if state in (jobs.WAITING, jobs.DONE, jobs.ERROR, jobs.STOPPED):
            out.append({"id": job.id, "state": state, "title": _title(job), "updated": job.data.get("updated"),
                        "stage": (job.data.get("awaiting") or {}).get("stage")})
    return sorted(out, key=lambda x: x["updated"] or "", reverse=True)[:20]


def _job_counts() -> dict:
    counts: dict[str, int] = {}
    for job in jobs.all_jobs(500):
        counts[job.data["state"]] = counts.get(job.data["state"], 0) + 1
    return counts


@app.get("/api/spend")
def spend(days: int = 14):
    data = budget.summary(max(7, min(90, days)))
    titles = {}
    for job in jobs.all_jobs(1000):
        titles[job.id] = {"title": _title(job), "workflow": job.data["workflow"]}
    by_workflow: dict[str, float] = {}
    for job_id, usd in data.pop("by_job").items():
        wf = titles.get(job_id, {}).get("workflow", "deleted")
        by_workflow[wf] = by_workflow.get(wf, 0) + usd
    data["by_workflow"] = sorted(({"workflow": k, "usd": round(v, 4)} for k, v in by_workflow.items() if abs(v) > 1e-9),
                                 key=lambda x: -x["usd"])
    for row in data["recent"]:
        row.update(titles.get(row.get("job"), {"title": "Deleted project", "workflow": None}))
    return data


@app.get("/api/pricing")
def price_guide():
    return pricing.guide()


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
    by_job: dict[str, list[dict]] = {}
    for row in budget.entries():
        by_job.setdefault(row.get("job"), []).append(row)
    return [_public(j, by_job.get(j.id, []), full=False) for j in jobs.all_jobs(max(1, min(500, limit)))]


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
            try:
                validation.check_media(dest, field, upload.filename)
            except validation.InputError as exc:
                raise HTTPException(400, str(exc)) from None
            saved.setdefault(field, []).append(dest)
    return saved


def _resolve_library(values: dict, saved: dict) -> None:
    """Swap library ids for their files, so a job keeps working if the item is later deleted."""
    if values.get("avatar_id") and not saved.get("avatar"):
        saved["avatar"] = [Path(library.get("avatars", values["avatar_id"])["path"])]
    if values.get("voice_id") and not saved.get("voice_sample"):
        voice = library.get("voices", values["voice_id"])
        saved["voice_sample"] = [Path(voice["reference_path"])]
        if voice.get("transcript") and voice["duration"] <= library.REF_SECONDS + 0.5:
            values["voice_transcript"] = voice["transcript"]


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
    avatar: UploadFile | None = File(None),
    voice_sample: UploadFile | None = File(None),
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
                   "music": [music], "avatar": [avatar], "voice_sample": [voice_sample], "refs": refs or []}
        saved = _save_uploads(uploads, tmp)
        try:
            _resolve_library(values, saved)
        except library.LibraryError as exc:
            raise HTTPException(400, str(exc)) from None
        counts = {k: len(v) for k, v in saved.items()}
        counts["avatar_is_video"] = bool(saved.get("avatar") and saved["avatar"][0].suffix.lower() in VIDEO_EXT)
        if workflow == "swap" and saved.get("video"):
            values["source_seconds"] = round(min(600, media.probe(saved["video"][0])["duration"]), 2)
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
    if job.data.get("state") in (jobs.DONE, jobs.WAITING):
        raise HTTPException(409, "Nothing to resume." if job.data["state"] == jobs.DONE else "This project is waiting for your approval.")
    workflows.start(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/stop")
def stop(job_id: str):
    job = _job(job_id)
    try:
        result = workflows.stop(job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {**_public(job), "stop": result}


@app.post("/api/jobs/{job_id}/duplicate")
async def duplicate(job_id: str, request: Request):
    """A new project with the same inputs and settings (your edits to the script or shots included)."""
    job = _job(job_id)
    body = await request.json() if (await request.body()) else {}
    values = json.loads(json.dumps(job.params))
    values.pop("overrides", None)
    plan = job.data.get("plan") or {}
    if job.data["workflow"] == "presenter" and plan.get("lines") and body.get("keep_script", True):
        values["script"] = "\n".join(line["text"] for line in plan["lines"])  # reuse the reviewed words
    files = {field: [job.folder / rel for rel in rels] for field, rels in job.data.get("inputs", {}).items()}
    files = {k: [p for p in v if p.exists()] for k, v in files.items()}
    counts = {k: len(v) for k, v in files.items() if v}
    counts["avatar_is_video"] = bool(files.get("avatar") and files["avatar"][0].suffix.lower() in VIDEO_EXT)
    try:
        quote = workflows.check_start(job.data["workflow"], values, counts, bool(body.get("confirm")))
    except workflows.NeedsConfirmation as exc:
        return JSONResponse({"detail": str(exc), "needs_confirmation": True, "quote": exc.quote}, status_code=402)
    except (ValueError, budget.BudgetExceeded, config.MissingKey) as exc:
        raise HTTPException(400, str(exc)) from None
    copy = jobs.create(job.data["workflow"], values, {k: v for k, v in files.items() if v})
    copy.data["estimate"] = quote
    copy.data["duplicate_of"] = job.id
    copy.save()
    workflows.start(copy)
    return _public(copy)


@app.get("/api/jobs/{job_id}/download")
def download_all(job_id: str):
    """Every output (final, parts, script, review) in one zip."""
    job = _job(job_id)
    outputs = [o for o in job.data.get("outputs", []) if (job.folder / o["path"]).is_file()]
    if not outputs:
        raise HTTPException(404, "Nothing to download yet.")
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=config.RUNS)
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:  # media is already compressed
        for o in outputs:
            zf.write(job.folder / o["path"], o["path"])
    name = re.sub(r"[^A-Za-z0-9]+", "-", _title(job)).strip("-")[:50] or job.id
    return FileResponse(tmp, filename=f"{name}.zip", media_type="application/zip",
                        background=BackgroundTask(os.unlink, tmp))


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    job = _job(job_id)
    if workflows.is_active(job.id):
        raise HTTPException(409, "Job is still running.")
    shutil.rmtree(job.folder, ignore_errors=True)
    jobs._live.pop(job.id, None)
    return {"deleted": job_id}


# -- asset library -------------------------------------------------------------

@app.get("/api/library")
def get_library():
    return {kind: library.items(kind) for kind in library.KINDS}


@app.post("/api/library/{kind}")
async def add_library_item(kind: str, file: UploadFile = File(...), name: str = Form(""), consent: bool = Form(False),
                           transcript: str = Form("")):
    if kind not in library.KINDS:
        raise HTTPException(404)
    suffix = Path(file.filename or "").suffix.lower() or ".bin"
    tmp = Path(tempfile.mkdtemp(prefix="lib-", dir=config.RUNS))
    try:
        src = tmp / ("upload" + suffix)
        with src.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        if src.stat().st_size > MAX_UPLOAD:
            raise HTTPException(413, "That file is larger than 500 MB.")
        if kind == "avatars":
            return library.add_avatar(src, name, consent)
        return library.add_voice(src, name, consent, transcript)
    except (library.LibraryError, media.MediaError) as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.patch("/api/library/{kind}/{item_id}")
async def rename_library_item(kind: str, item_id: str, request: Request):
    body = await request.json()
    try:
        return library.rename(kind, item_id, body.get("name", ""))
    except library.LibraryError as exc:
        raise HTTPException(404, str(exc)) from None


@app.delete("/api/library/{kind}/{item_id}")
def delete_library_item(kind: str, item_id: str):
    try:
        library.delete(kind, item_id)
    except library.LibraryError as exc:
        raise HTTPException(404, str(exc)) from None
    return {"deleted": item_id}


@app.get("/library/{kind}/{item_id}/{name}")
def library_file(kind: str, item_id: str, name: str):
    try:
        return FileResponse(library.file_path(kind, item_id, name))
    except library.LibraryError:
        raise HTTPException(404) from None


@app.get("/api/settings")
def get_settings():
    return {
        "keys": {k: config.has_key(k) for k in config.KEYS},
        "settings": {k: config.setting(k) for k in sorted(SETTABLE - set(config.KEYS) - {"CATBOX_USERHASH"})},
    }


MONEY_SETTINGS = {"MW_MAX_COST_PER_JOB": "Max per project", "MW_DAILY_BUDGET": "Daily budget",
                  "MW_CONFIRM_ABOVE": "Ask me above"}


def _setting_problem(name: str, value: str) -> str | None:
    """A plain message if a setting value can't work; empty means "use the default"."""
    if not value:
        return None
    if name in MONEY_SETTINGS or name == "MW_MAX_PARALLEL":
        label = MONEY_SETTINGS.get(name, "Parallel generations")
        try:
            number = float(value)
        except ValueError:
            return f"{label} must be a number (got “{value[:20]}”)."
        if not math.isfinite(number) or number < 0:
            return f"{label} must be zero or more."
        if name == "MW_MAX_PARALLEL" and not (1 <= number <= 8 and number == int(number)):
            return "Parallel generations must be a whole number from 1 to 8."
        if name in MONEY_SETTINGS and number > 1000:
            return f"{label} looks too high (over $1,000). Type it again if you mean it, without extra zeros."
    if name == "MW_DEFAULT_TIER" and value not in catalog.TIERS:
        return f"Quality tier must be one of: {', '.join(catalog.TIERS)}."
    if name == "MW_ALLOW_MOCK" and value not in ("0", "1"):
        return "MW_ALLOW_MOCK must be 0 or 1."
    return None


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
        if name in MONEY_SETTINGS:
            value = value.lstrip("$").strip()
        problem = _setting_problem(name, value)
        if problem:
            raise HTTPException(400, problem)
        if value or name not in config.KEYS:
            updates[name] = value
    if updates:
        config.save_keys(updates)
    return get_settings()


def main(host: str = "127.0.0.1", port: int = 8770) -> None:
    import uvicorn

    print(f"MotionWorkflow running at http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
