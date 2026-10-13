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

Genjutsu prep (`prep`: genjutsu-depth / genjutsu-face-mesh / genjutsu-depth-mesh)
runs the upstream Genjutsu preparation from vendor/genjutsu, then stops for
its mandatory full-clip review before anything is generated. You can also
prepare elsewhere and upload its seedance-input.mp4 with "prepared" on.

`direct` skips the draft: one render at the final quality. A Seedance draft
costs extra overall (completing it costs the same as rendering directly), so
draft only when you want to see it before paying for the final.
"""
from __future__ import annotations

import shutil

from .. import budget, catalog, genjutsu, media
from ..jobs import Job
from ..providers.base import VIDEO_EXT
from .common import first_input, first_of_kind, generate, input_paths, line, total

MAX_SECONDS = 30
OMNI_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}


def _model(params: dict) -> dict:
    if not params.get("model") and (params.get("prep") or "none") != "none":
        seedance = catalog.get("enhancor:seedance-edit")  # Genjutsu prep is made for Seedance
        if catalog.available(seedance):
            return seedance
    return catalog.resolve("swap", params.get("tier"), params.get("model") or None)


def _seconds(params: dict, counts: dict) -> float:
    return min(MAX_SECONDS, float(params.get("source_seconds") or counts.get("source_seconds") or 10))


def _flag(params: dict, name: str) -> bool:
    return params.get(name) in (True, "true", "1", 1, "on")


def _prep_mode(params: dict) -> str | None:
    prep = params.get("prep") or "none"
    if prep == "none":
        return None
    if prep not in genjutsu.MODES:
        raise ValueError(f"Unknown prep '{prep}'. Use none or one of {', '.join(genjutsu.MODES)}.")
    return genjutsu.MODES[prep]


def estimate(params: dict, counts: dict) -> dict:
    model = _model(params)
    seconds = _seconds(params, counts)
    items = []
    mode = _prep_mode(params)
    if mode:
        items.append({"label": f"Genjutsu prep ({mode}, Replicate)", "model": "genjutsu", "model_name": "Genjutsu",
                      "usd": genjutsu.PREP_ESTIMATE[mode], "mock": False})
    final_res = params.get("final_resolution") or (model.get("resolutions") or [None])[-1]
    final = catalog.estimate(model, {"source_seconds": seconds, "resolution": final_res})
    if _flag(params, "direct"):
        items.append(line("Final (no draft)", model, final))
    else:
        draft = catalog.estimate(model, {"source_seconds": seconds, "resolution": params.get("draft_resolution")})
        items += [line("Draft", model, draft), line("Final (after your approval)", model, final)]
    return total(items)


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


def _enhancor_body(job: Job, provider, source, refs: list, info: dict, draft: bool = True) -> dict:
    prompt = (job.params.get("prompt") or "Replace the main person with the character from the reference.").strip()
    mode = _prep_mode(job.params)
    prepared_input = _flag(job.params, "prepared") or mode is not None
    video_ref = refs[0] if refs[0].suffix.lower() in VIDEO_EXT else None
    image_refs = [r for r in refs if r is not video_ref]
    urls = {str(p): provider.prepare_media(p) for p in [source, *refs]}
    body = {"resolution": "1080p", "output_format": "mp4", "pass_faces": True, "is_draft": draft, "audios": []}
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
    if mode in ("face_mesh", "depth_mesh"):
        description = "depth composite with face mesh overlay" if mode == "depth_mesh" else "original video with face mesh overlay"
        body["prompt"] = body["prompt"].replace("prepared Genjutsu composite", f"prepared Genjutsu {description}")
        body["prompt"] += genjutsu.MESH_PROMPT
    return body


def _genjutsu_prep(job: Job, source, mode: str):
    """Run Genjutsu's preparation once, then hold for its full-clip review."""
    step = job.step("prep")
    if step.get("state") != "done":
        gj = step.get("genjutsu_job")
        if gj and genjutsu.finished(gj):
            job.update_step("prep", state="done")
        elif step.get("state") == "running":
            job.update_step("prep", state="unknown", error="Interrupted while Genjutsu was preparing.")
            raise ValueError("Genjutsu prep was interrupted and may have used Replicate credits. "
                             "Check replicate.com/predictions, then Retry with force to prepare again.")
        elif step.get("state") in ("failed", "unknown"):
            raise ValueError(f"Genjutsu prep: {step.get('error')}. Use Retry to prepare again.")
        else:
            cost = genjutsu.PREP_ESTIMATE[mode]
            genjutsu.check(mode)  # before any spend
            budget.charge(job.id, "genjutsu:" + mode, cost, note="prep")
            job.update_step("prep", state="running", model="genjutsu:" + mode, estimate=cost, label="Genjutsu prep")
            try:
                genjutsu.prepare(source, mode, job.params.get("subject") or "person",
                                 on_job=lambda ident: job.update_step("prep", genjutsu_job=ident),
                                 on_status=job.status)
            except genjutsu.GenjutsuError as exc:
                if not exc.started:
                    budget.refund(job.id, "genjutsu:" + mode, cost, note="prep did not start")
                job.update_step("prep", state="failed", error=str(exc))
                raise ValueError(str(exc)) from exc
            job.update_step("prep", state="done")
    folder = genjutsu.run_folder(job.step("prep")["genjutsu_job"])
    copies = {}
    prep_dir = job.path("genjutsu")
    prep_dir.mkdir(exist_ok=True)
    labels = {"input": "Prepared input (what Seedance gets)", "mask": "Genjutsu mask", "composite": "Genjutsu composite",
              "depth": "Colored depth"}
    for name, src in genjutsu.artifacts(folder).items():
        dest = prep_dir / src.name
        if not dest.exists():
            shutil.copyfile(src, dest)
        copies[name] = dest
        job.add_output(dest, labels[name], "video")
    return copies["input"]


def run(job: Job) -> None:
    params = job.params
    refs = input_paths(job, "refs")
    if not refs:
        raise ValueError("Upload at least one character reference (image, or a short video for identity).")
    model = _model(params)
    source, audio_source, info = _prepare_source(job)
    seconds = info["duration"]
    is_enhancor = model["provider"] == "enhancor"
    direct = _flag(params, "direct")
    final_res = params.get("final_resolution") or (model.get("resolutions") or [None])[-1]
    final_cost = catalog.estimate(model, {"source_seconds": seconds, "resolution": final_res})

    # 0. Genjutsu prep and its mandatory full-clip review
    mode = _prep_mode(params)
    send = source
    if mode:
        if model["provider"] not in ("enhancor", "mock"):
            raise ValueError("Genjutsu prep is made for Seedance: choose the Enhancor Seedance engine.")
        send = _genjutsu_prep(job, source, mode)
        if not job.approved("mask"):
            what = "mask coverage (hair, hands, clothing, edges, background spill, flicker)" if mode != "face_mesh" \
                else "face tracking and the pitched vocals"
            next_cost = final_cost if direct else catalog.estimate(model, {"source_seconds": seconds,
                                                                           "resolution": params.get("draft_resolution")})
            job.wait_for("mask", f"Genjutsu prep ready. Watch the WHOLE prepared clip and check {what}. "
                         f"Approve to generate (~${next_cost:.2f}), or redo the prep.", estimate=round(next_cost, 4))
            return

    if is_enhancor:
        from .. import providers

        provider = providers.get("enhancor")

    # 1. Draft (skipped when direct)
    if not direct:
        if is_enhancor:
            step = job.step("draft")
            body = None if step.get("handle") or step.get("state") == "done" else \
                _enhancor_body(job, provider, send, refs, info)
            draft_files = generate(job, "draft", model, {"source_seconds": seconds}, label="Seedance draft", body=body)
        else:
            if refs[0].suffix.lower() in VIDEO_EXT:
                raise ValueError(f"{model['name']} needs an image reference; video identity references need Enhancor Seedance.")
            draft_res = params.get("draft_resolution") or model.get("default_resolution")
            draft_files = generate(job, "draft", model, {
                "prompt": params.get("prompt"), "video": str(send), "image": str(refs[0]),
                "resolution": draft_res, "source_seconds": seconds}, label="Swap draft")
        draft = first_of_kind(draft_files, "video")
        preview = job.path("draft-preview.mp4")
        if not preview.exists():
            job.status("Restoring the original soundtrack on the draft")
            job.data["audio"] = media.restore_audio(draft, audio_source, preview, limit=seconds)
        job.add_output(preview, "Draft (original audio)", "video")

        # 2. Approval
        if not job.approved("final"):
            job.wait_for("final", f"Draft ready. Approve to render the final (~${final_cost:.2f}).",
                         estimate=round(final_cost, 4))
            return

    # 3. Final
    if is_enhancor:
        if direct:
            step = job.step("final")
            body = None if step.get("handle") or step.get("state") == "done" else \
                _enhancor_body(job, provider, send, refs, info, draft=False)
        else:
            body = {"draft_id": job.step("draft")["handle"]["request_id"]}
        final_files = generate(job, "final", model, {"source_seconds": seconds}, label="Seedance 1080p",
                               body=body, estimate=final_cost)
    else:
        if refs[0].suffix.lower() in VIDEO_EXT:
            raise ValueError(f"{model['name']} needs an image reference; video identity references need Enhancor Seedance.")
        final_files = generate(job, "final", model, {
            "prompt": params.get("prompt"), "video": str(send), "image": str(refs[0]),
            "resolution": final_res, "source_seconds": seconds}, label="Swap final")
    final = first_of_kind(final_files, "video")
    out = job.path("final.mp4")
    if not out.exists():
        job.status("Restoring the original soundtrack on the final")
        job.data["audio"] = media.restore_audio(final, audio_source, out, limit=seconds)
    media.thumbnail(out, job.path("thumbnail.jpg"))
    job.add_output(out, "Final (original audio)", "video", final=True)
