"""Text-to-video and image-to-video, with an optional cheap draft before the final."""
from __future__ import annotations

import shutil

from .. import catalog, media
from ..jobs import Job
from .common import first_input, first_of_kind, generate, line, total


def _kind(has_image: bool) -> str:
    return "image_to_video" if has_image else "video"


def _params(params: dict, model: dict, resolution_key: str = "resolution") -> dict:
    out = {k: params.get(k) for k in ("prompt", "aspect_ratio", "seed", "negative_prompt")}
    out["duration"] = catalog.pick_duration(model, float(params["duration"]) if params.get("duration") else None)
    resolution = params.get(resolution_key)
    if resolution and resolution in (model.get("resolutions") or []):
        out["resolution"] = resolution
    elif model.get("default_resolution"):
        out["resolution"] = model["default_resolution"]
    if "audio" in params:
        out["audio"] = bool(params["audio"])
    return out


def _final_model(params: dict, has_image: bool) -> dict | None:
    if not (params.get("final_model") or params.get("final_tier")):
        return None
    return catalog.resolve(_kind(has_image), params.get("final_tier") or "premium", params.get("final_model") or None)


def estimate(params: dict, counts: dict) -> dict:
    has_image = counts.get("image", 0) > 0
    model = catalog.resolve(_kind(has_image), params.get("tier"), params.get("model") or None)
    items = [line("Draft" if _final_model(params, has_image) else "Video", model,
                  catalog.estimate(model, _params(params, model)))]
    final = _final_model(params, has_image)
    if final:
        items.append(line("Final (after your approval)", final,
                          catalog.estimate(final, _params(params, final, "final_resolution"))))
    return total(items)


def run(job: Job) -> None:
    params = job.params
    if not (params.get("prompt") or "").strip():
        raise ValueError("Write a prompt.")
    image = first_input(job, "image")
    model = catalog.resolve(_kind(bool(image)), params.get("tier"), params.get("model") or None)
    final = _final_model(params, bool(image))
    request = _params(params, model)
    if image:
        request["image"] = str(image)
    files = generate(job, "draft", model, request, label="Draft video" if final else "Video")
    clip = job.path("draft.mp4" if final else "video.mp4")
    shutil.copyfile(first_of_kind(files, "video"), clip)
    job.add_output(clip, "Draft" if final else "Video", "video", final=not final)
    if not final:
        media.thumbnail(clip, job.path("thumbnail.jpg"))
        return

    final_request = _params(params, final, "final_resolution")
    if image:
        final_request["image"] = str(image)
    if not job.approved("final"):
        cost = catalog.estimate(final, final_request)
        job.wait_for("final", f"Draft ready. Approve to render the final with {final['name']} (~${cost:.2f}).",
                     estimate=round(cost, 4))
        return
    files = generate(job, "final", final, final_request, label="Final video")
    out = job.path("final.mp4")
    shutil.copyfile(first_of_kind(files, "video"), out)
    job.add_output(out, "Final", "video", final=True)
    media.thumbnail(out, job.path("thumbnail.jpg"))
