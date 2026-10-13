"""Shared step runner used by every workflow.

`generate()` is the only place that spends money. It is idempotent per step
key: a finished step returns its files, a submitted step resumes polling,
and only a step with no saved request is ever submitted.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import budget, catalog, config, providers
from ..jobs import Job
from ..providers.base import AmbiguousError, ProviderError, RejectedError, StillRunning, is_url

MEDIA_PARAMS = ("image", "video", "audio_file", "voice_sample")


class StepFailed(RuntimeError):
    pass


def input_paths(job: Job, field: str) -> list[Path]:
    return [job.folder / p for p in job.data.get("inputs", {}).get(field, [])]


def first_input(job: Job, field: str) -> Path | None:
    paths = input_paths(job, field)
    return paths[0] if paths else None


def _prepare(provider, params: dict) -> dict:
    prepared = dict(params)
    for field in MEDIA_PARAMS:
        value = prepared.get(field)
        if value and not is_url(value):
            prepared[field] = provider.prepare_media(Path(value))
    if prepared.get("images"):
        prepared["images"] = [v if is_url(v) else provider.prepare_media(Path(v)) for v in prepared["images"]]
    return prepared


def generate(job: Job, key: str, model: dict, params: dict, label: str, body: dict | None = None,
             estimate: float | None = None) -> list[Path]:
    """Run one model call as a resumable step and return the downloaded files."""
    step = job.step(key)
    if step.get("state") == "done":
        return [job.folder / p for p in step["files"]]
    if step.get("state") == "failed":
        raise StepFailed(f"{label} failed earlier: {step.get('error')}. Use Retry to try again.")
    if step.get("state") == "submitting" and not step.get("handle"):
        # The process stopped while a paid request was in flight: we can't know if it was accepted.
        job.update_step(key, state="unknown", error="Interrupted while submitting.")
    if step.get("state") == "unknown":
        raise StepFailed(f"{label}: unclear whether the provider accepted the request. "
                         "Check the provider dashboard, then use Retry with force.")

    provider = providers.get(model["provider"])
    workdir = job.folder / "work"
    workdir.mkdir(exist_ok=True)
    handle = step.get("handle")

    if not handle:
        job.checkpoint()  # never send a new paid request after Stop
        cost = catalog.estimate(model, params) if estimate is None else estimate
        job.status(f"{label}: preparing ({model['name']}, ~${cost:.3f})")
        request_body = body if body is not None else catalog.build_input(model, _prepare(provider, params))
        budget.charge(job.id, model["id"], cost, note=key)
        job.update_step(key, state="submitting", model=model["id"], label=label, estimate=round(cost, 4))
        try:
            handle = provider.submit(model, request_body, workdir)
        except RejectedError as exc:
            budget.refund(job.id, model["id"], cost, note=f"{key}: rejected")
            job.update_step(key, state="failed", error=str(exc))
            raise StepFailed(f"{label}: {exc}") from exc
        except AmbiguousError as exc:
            job.update_step(key, state="unknown", error=str(exc))
            raise StepFailed(f"{label}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - local failure before a request was accepted
            budget.refund(job.id, model["id"], cost, note=f"{key}: {type(exc).__name__}")
            job.update_step(key, state="failed", error=str(exc))
            raise StepFailed(f"{label}: {exc}") from exc
        job.update_step(key, state="running", handle=handle)
        if model["provider"] == "mock":
            job.data["used_mock"] = True

    try:
        result = provider.wait(model, handle, lambda message: job.status(f"{label}: {message}") if message
                               else job.checkpoint())
        files = provider.collect(model, handle, result, workdir / key.replace("/", "-"))
    except StillRunning as exc:
        raise StepFailed(str(exc)) from exc
    except ProviderError as exc:
        job.update_step(key, state="failed", error=str(exc))
        raise StepFailed(f"{label}: {exc}") from exc

    rel = [job.rel(f) for f in files]
    job.update_step(key, state="done", files=rel, request_id=handle.get("request_id"))
    return files


def parallel(fn, items: list, workers: int | None = None) -> list:
    """Run independent steps concurrently; re-raise the first failure."""
    workers = workers or max(1, int(config.number("MW_MAX_PARALLEL")))
    if len(items) <= 1 or workers == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fn, item) for item in items]
        return [f.result() for f in futures]


def first_of_kind(files: list[Path], kind: str) -> Path:
    from ..providers.base import media_kind

    for f in files:
        if media_kind(str(f)) == kind:
            return f
    raise StepFailed(f"Expected a {kind} output, got: {', '.join(p.name for p in files)}")


def line(label: str, model: dict, usd: float) -> dict:
    return {"label": label, "model": model["id"], "model_name": model["name"], "usd": round(usd, 4),
            "mock": model["provider"] == "mock"}


def total(items: list[dict]) -> dict:
    return {"total": round(sum(i["usd"] for i in items), 4), "items": items}
