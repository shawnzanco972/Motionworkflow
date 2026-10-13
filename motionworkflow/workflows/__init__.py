"""Workflow registry and job runner (used by both the web app and the CLI)."""
from __future__ import annotations

import shutil
import threading
import traceback

from .. import budget, jobs, validation
from ..jobs import DONE, ERROR, RUNNING, STOPPED, WAITING, Job, JobStopped
from . import image, presenter, short, swap, video, voice
from .common import StepFailed

WORKFLOWS = {"image": image, "video": video, "short": short, "swap": swap, "voice": voice,
             "presenter": presenter}

_active: set[str] = set()
_active_lock = threading.Lock()


class NeedsConfirmation(RuntimeError):
    def __init__(self, quote: dict):
        super().__init__(f"This job is estimated at ${quote['total']:.2f}. Confirm the cost to start it.")
        self.quote = quote


def module(name: str):
    try:
        return WORKFLOWS[name]
    except KeyError:
        raise ValueError(f"Unknown workflow '{name}'. Use one of: {', '.join(WORKFLOWS)}.") from None


def estimate(workflow: str, params: dict, counts: dict | None = None) -> dict:
    module(workflow)
    params = validation.coerce(workflow, dict(params))
    quote = module(workflow).estimate(params, counts or {})
    quote["needs_confirmation"] = budget.needs_confirmation(quote["total"])
    quote["mock"] = any(i.get("mock") for i in quote["items"])
    quote["budget"] = budget.report()
    return quote


def check_start(workflow: str, params: dict, counts: dict, confirmed: bool) -> dict:
    """Validate inputs and cost before a job is created. Cleans `params` in place.

    Raises InputError for something to fix in the form, BudgetExceeded over a cap,
    or NeedsConfirmation when the person hasn't confirmed a large spend.
    """
    module(workflow)
    validation.coerce(workflow, params)
    validation.require(workflow, params, counts)
    quote = estimate(workflow, params, counts)
    budget.check_job(quote["total"])
    if quote["needs_confirmation"] and not confirmed:
        raise NeedsConfirmation(quote)
    return quote


def run(job: Job) -> Job:
    """Run (or continue) a job until it finishes, fails, or waits for approval."""
    with _active_lock:
        if job.id in _active:
            return job
        _active.add(job.id)
    try:
        job.clear_stop()
        job.data.pop("error", None)
        job.status("Working", RUNNING)
        module(job.data["workflow"]).run(job)
        if job.data.get("state") != WAITING:
            note = " (mock output: add an API key for real media)" if job.data.get("used_mock") else ""
            job.status("Finished" + note, DONE)
    except JobStopped:
        job.status("Stopped. Requests already sent may still finish at the provider; Resume collects them "
                   "without paying twice.", STOPPED)
    except (StepFailed, ValueError, budget.BudgetExceeded) as exc:
        job.data["error"] = str(exc)
        job.status(str(exc), ERROR)
    except Exception as exc:  # noqa: BLE001 - surface anything else to the UI
        job.data["error"] = f"{type(exc).__name__}: {exc}"
        job.data["traceback"] = traceback.format_exc()[-4000:]
        job.status(job.data["error"], ERROR)
    finally:
        job.clear_stop()
        with _active_lock:
            _active.discard(job.id)
    return job


def stop(job: Job) -> str:
    """Stop a job at its next checkpoint. Returns what happened, for the UI."""
    if is_active(job.id):
        job.request_stop()
        return "stopping"
    if job.data.get("state") in (RUNNING, "queued"):  # left over from a closed app
        job.status("Stopped.", STOPPED)
        return "stopped"
    raise ValueError("This project isn't running.")


def start(job: Job, background: bool = True) -> Job:
    if background:
        threading.Thread(target=run, args=(job,), daemon=True, name=f"job-{job.id}").start()
        return job
    return run(job)


def is_active(job_id: str) -> bool:
    return job_id in _active


def retry(job: Job, force: bool = False) -> None:
    """Clear failed steps so they are submitted again (an explicit, user-approved re-spend)."""
    for key, step in list(job.data.get("steps", {}).items()):
        if step.get("state") == "failed" or (force and step.get("state") in ("unknown", "submitting")):
            del job.data["steps"][key]
    job.save()


def redo(job: Job, step_keys: list[str], overrides: dict | None = None) -> None:
    """Regenerate specific steps (e.g. one storyboard shot), optionally with new prompts.

    Any earlier approval is withdrawn: approval belongs to the exact media the
    user looked at, as in the Genjutsu review gate.
    """
    steps = job.data.get("steps", {})
    keys = set(step_keys)
    overrides = {str(k): v for k, v in (overrides or {}).items()}
    for key in list(keys):
        if key.startswith("key-"):
            keys.add("clip-" + key[4:])  # a new keyframe needs a new animation
    for index, edits in overrides.items():
        if edits.get("text"):  # presenter: a rewritten line is voiced again
            keys.add(f"voice-{index}")
        if "broll" in edits:
            keys.add(f"broll-{index}")
        if edits.get("visual"):
            keys.update({f"key-{index}", f"clip-{index}"})
        if edits.get("motion"):
            keys.add(f"clip-{index}")
        if edits.get("narration"):
            keys.add(f"voice-{index}")
    if any(k.startswith("voice-") for k in keys) and job.data.get("workflow") == "presenter":
        # New words mean a new voice track, so every animated part is redone.
        keys.update(k for k in steps if k.startswith("face-"))
        job.path("voice.wav").unlink(missing_ok=True)
        for old in job.path("assemble").glob("segment-*.wav") if job.path("assemble").exists() else []:
            old.unlink()
        job.data["outputs"] = [o for o in job.data.get("outputs", []) if o["path"] != "voice.wav"]
    for key in keys:
        steps.pop(key, None)
    if overrides:
        merged = job.params.setdefault("overrides", {})
        for index, edits in overrides.items():
            merged.setdefault(index, {}).update({k: v for k, v in edits.items() if v or k == "broll"})
    if "plan" in keys:
        job.path("plan.json").unlink(missing_ok=True)
    if "prep" in keys:  # new Genjutsu prep: everything generated from the old one goes
        keys.update({"draft", "final"})
        steps.pop("draft", None)
        shutil.rmtree(job.path("genjutsu"), ignore_errors=True)
        job.data["outputs"] = [o for o in job.data.get("outputs", []) if not o["path"].startswith("genjutsu/")]
    if "draft" in keys:
        job.path("draft-preview.mp4").unlink(missing_ok=True)
        job.data["outputs"] = [o for o in job.data.get("outputs", []) if o["path"] != "draft-preview.mp4"]
        steps.pop("final", None)
    job.path("final.mp4").unlink(missing_ok=True)
    shutil.rmtree(job.path("review"), ignore_errors=True)  # a new cut needs a new reviewer
    job.data.pop("review", None)
    job.data["outputs"] = [o for o in job.data.get("outputs", [])
                           if not o.get("final") and not o["path"].startswith("review/")]
    job.clear_approvals()
    job.save()


def resume_all() -> list[str]:
    """On startup, continue jobs that were mid-flight. Never resubmits a saved request."""
    resumed = []
    for job in jobs.all_jobs(limit=500):
        if job.data.get("state") in (RUNNING, "queued") and not is_active(job.id):
            if job.stop_requested():  # stopped from the CLI while nothing was running it
                job.clear_stop()
                job.status("Stopped.", STOPPED)
                continue
            start(job)
            resumed.append(job.id)
    return resumed


__all__ = ["WORKFLOWS", "estimate", "check_start", "run", "start", "stop", "retry", "redo", "resume_all",
           "NeedsConfirmation", "DONE", "ERROR", "WAITING"]
