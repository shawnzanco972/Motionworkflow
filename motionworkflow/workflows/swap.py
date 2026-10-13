"""Character Swap (Genjutsu-style): your scene, a new character.

Source video + character reference -> cheap draft -> your approval -> final.
The final always carries the source's complete original soundtrack, as in
the Genjutsu workflow (generated audio is discarded).

Engines:
- enhancor:seedance-edit - Seedance 2.5 Edit via Enhancor. Draft, then the
  approved draft is completed at 1080p (`draft_id`), exactly like Genjutsu.
  An image reference uses Edit; a video identity reference uses
  multi_reference (Omni).
- fal:wan-animate-replace - Wan 2.2 Animate Replace. Draft at 480p, final
  re-rendered at a higher resolution.

For Genjutsu's advanced depth + SAM 3 mask preparation, prepare the clip with
the upstream repo and upload its seedance-input.mp4 here with
"prepared input" on, plus the untouched original for audio restoration.
"""
from __future__ import annotations

from .. import catalog, media
from ..jobs import Job
from ..providers.base import VIDEO_EXT
from .common import first_input, first_of_kind, generate, input_paths, line, total

MAX_SECONDS = 30
OMNI_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}


def _model(params: dict) -> dict:
    return catalog.resolve("swap", params.get("tier"), params.get("model") or None)


def _seconds(params: dict, counts: dict) -> float:
    return min(MAX_SECONDS, float(params.get("source_seconds") or counts.get("source_seconds") or 10))


def estimate(params: dict, counts: dict) -> dict:
    model = _model(params)
    seconds = _seconds(params, counts)
    draft = catalog.estimate(model, {"source_seconds": seconds, "resolution": params.get("draft_resolution")})
    final_res = params.get("final_resolution") or (model.get("resolutions") or [None])[-1]
    final = catalog.estimate(model, {"source_seconds": seconds, "resolution": final_res})
    return total([line("Draft", model, draft), line("Final (after your approval)", model, final)])


def _prepare_source(job: Job) -> tuple:
    source = first_input(job, "video")
    if not source:
        raise ValueError("Upload the source video.")
    prepared = job.path("source.mp4")
    if not prepared.exists():
        info = media.probe(source)
        if not info["has_video"]:
            raise ValueError("The source file has no video track.")
        seconds = min(MAX_SECONDS, info["duration"])
        if info["duration"] > MAX_SECONDS + 0.05:
            job.data["warning"] = f"Source trimmed to the first {MAX_SECONDS} seconds."
        job.status("Preparing the source clip")
        # Cap the long side at 1280 px, keep the audio, H.264/AAC for every provider.
        scale = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
        media.run(["-i", source, "-t", f"{seconds:.3f}", "-vf", f"{scale},format=yuv420p",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", prepared])
    audio_source = first_input(job, "original") or prepared
    return prepared, audio_source, media.probe(prepared)


def _enhancor_body(job: Job, provider, source, refs: list, info: dict) -> dict:
    prompt = (job.params.get("prompt") or "Replace the main person with the character from the reference.").strip()
    prepared_input = job.params.get("prepared") in (True, "true", "1", 1)
    video_ref = refs[0] if refs[0].suffix.lower() in VIDEO_EXT else None
    image_refs = [r for r in refs if r is not video_ref]
    urls = {str(p): provider.prepare_media(p) for p in [source, *refs]}
    body = {"resolution": "1080p", "output_format": "mp4", "pass_faces": True, "is_draft": True, "audios": []}
    about_source = ("@Video1 contains the prepared Genjutsu composite with embedded vocals; use its embedded audio for "
                    "performance and lip synchronization." if prepared_input else
                    "@Video1 is the source performance: keep its timing, camera movement, framing and lip movement; "
                    "use its audio for lip synchronization.")
    if video_ref:
        ratio = info["width"] / max(1, info["height"])
        body.update(
            mode="multi_reference",
            videos=[urls[str(source)], urls[str(video_ref)]],
            images=[urls[str(p)] for p in image_refs],
            duration=str(max(4, min(30, round(info["duration"])))),
            aspect_ratio=min(OMNI_RATIOS, key=lambda r: abs(OMNI_RATIOS[r] - ratio)),
            prompt=f"{prompt}\n{about_source} @Video2 is only the character's visual identity reference. "
                   "Use only @Video1 audio for speech timing.",
        )
    else:
        refs_text = ("@Image1 is the primary character reference; @Image2 is the secondary character reference."
                     if len(image_refs) > 1 else "@Image1 is the only replacement character reference.")
        body.update(mode="edit", aspect_ratio="adaptive", videos=[urls[str(source)]],
                    images=[urls[str(p)] for p in image_refs[:2]], prompt=f"{prompt}\n{about_source} {refs_text}")
    return body


def run(job: Job) -> None:
    params = job.params
    refs = input_paths(job, "refs")
    if not refs:
        raise ValueError("Upload at least one character reference (image, or a short video for identity).")
    model = _model(params)
    source, audio_source, info = _prepare_source(job)
    seconds = info["duration"]
    is_enhancor = model["provider"] == "enhancor"

    # 1. Draft
    if is_enhancor:
        from .. import providers

        provider = providers.get("enhancor")
        step = job.step("draft")
        body = None if step.get("handle") or step.get("state") == "done" else _enhancor_body(job, provider, source, refs, info)
        draft_files = generate(job, "draft", model, {"source_seconds": seconds}, label="Seedance draft", body=body)
    else:
        if refs[0].suffix.lower() in VIDEO_EXT:
            raise ValueError(f"{model['name']} needs an image reference; video identity references need Enhancor Seedance.")
        draft_res = params.get("draft_resolution") or model.get("default_resolution")
        draft_files = generate(job, "draft", model, {
            "prompt": params.get("prompt"), "video": str(source), "image": str(refs[0]),
            "resolution": draft_res, "source_seconds": seconds}, label="Swap draft")
    draft = first_of_kind(draft_files, "video")
    preview = job.path("draft-preview.mp4")
    if not preview.exists():
        job.status("Restoring the original soundtrack on the draft")
        result = media.restore_audio(draft, audio_source, preview, limit=seconds)
        job.data["audio"] = result
    job.add_output(preview, "Draft (original audio)", "video")

    # 2. Approval
    final_res = params.get("final_resolution") or (model.get("resolutions") or [None])[-1]
    final_cost = catalog.estimate(model, {"source_seconds": seconds, "resolution": final_res})
    if not job.approved("final"):
        job.wait_for("final", f"Draft ready. Approve to render the final (~${final_cost:.2f}).",
                     estimate=round(final_cost, 4))
        return

    # 3. Final
    if is_enhancor:
        draft_id = job.step("draft")["handle"]["request_id"]
        final_files = generate(job, "final", model, {}, label="Seedance 1080p",
                               body={"draft_id": draft_id}, estimate=final_cost)
    else:
        final_files = generate(job, "final", model, {
            "prompt": params.get("prompt"), "video": str(source), "image": str(refs[0]),
            "resolution": final_res, "source_seconds": seconds}, label="Swap final")
    final = first_of_kind(final_files, "video")
    out = job.path("final.mp4")
    if not out.exists():
        job.status("Restoring the original soundtrack on the final")
        media.restore_audio(final, audio_source, out, limit=seconds)
    media.thumbnail(out, job.path("thumbnail.jpg"))
    job.add_output(out, "Final (original audio)", "video", final=True)
