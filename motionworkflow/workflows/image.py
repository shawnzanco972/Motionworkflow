"""Text-to-image and reference-image edits."""
from __future__ import annotations

import shutil

from .. import catalog
from ..jobs import Job
from .common import first_input, generate, input_paths, line, parallel, total

MAX_IMAGES = 8


def _model(params: dict, has_refs: bool) -> dict:
    kind = "image_edit" if has_refs else "image"
    return catalog.resolve(kind, params.get("tier"), params.get("model") or None)


def _calls(model: dict, count: int) -> list[int]:
    """One call with num_images when the model supports it, else one call per image."""
    if "num_images" in model.get("inputs", {}):
        return [count]
    return [1] * count


def _base(params: dict) -> dict:
    return {k: params.get(k) for k in ("prompt", "aspect_ratio", "seed", "negative_prompt")}


def estimate(params: dict, counts: dict) -> dict:
    model = _model(params, counts.get("refs", 0) > 0)
    count = max(1, min(MAX_IMAGES, int(params.get("num_images") or 1)))
    usd = sum(catalog.estimate(model, {**_base(params), "num_images": n}) for n in _calls(model, count))
    return total([line(f"{count} image(s)", model, usd)])


def run(job: Job) -> None:
    params = job.params
    if not (params.get("prompt") or "").strip():
        raise ValueError("Write a prompt.")
    refs = input_paths(job, "refs")
    model = _model(params, bool(refs))
    count = max(1, min(MAX_IMAGES, int(params.get("num_images") or 1)))
    base = _base(params)
    if refs:
        base["images"] = [str(p) for p in refs]
        base["image"] = str(first_input(job, "refs"))

    def one(item):
        index, n = item
        return generate(job, f"image-{index}", model, {**base, "num_images": n}, label=f"Image batch {index + 1}")

    batches = parallel(one, list(enumerate(_calls(model, count))))
    number = 0
    for files in batches:
        for f in files:
            number += 1
            dest = job.path(f"image-{number}{f.suffix}")
            shutil.copyfile(f, dest)
            job.add_output(dest, f"Image {number}", "image", final=True)
