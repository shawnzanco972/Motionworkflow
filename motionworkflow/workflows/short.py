"""Short Maker: idea -> script -> keyframes -> (review) -> clips -> voice -> captions -> final MP4.

Two modes:
- slideshow: keyframes with Ken Burns motion made locally. Costs only the
  images and voice (a 6-shot short is a few cents on the budget tier).
- animated: each keyframe is animated by an image-to-video model. The
  storyboard is shown for approval first, because animation is the
  expensive part.
"""
from __future__ import annotations

import json
import shutil

from .. import budget, catalog, media, planner, reviewer
from ..jobs import Job
from .common import first_input, first_of_kind, generate, line, parallel, total

MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
CHARS_PER_SHOT = 130  # estimate for narration length before the script exists


def _settings(params: dict) -> dict:
    return {
        "shots": max(1, min(12, int(params.get("shots") or 5))),
        "seconds": max(2.0, min(10.0, float(params.get("shot_seconds") or 5))),
        "aspect": params.get("aspect_ratio") or "9:16",
        "mode": params.get("mode") or "slideshow",
        "voiceover": params.get("voiceover", True) not in (False, "false", "0", 0),
        "captions": params.get("captions", True) not in (False, "false", "0", 0),
        "review": params.get("review", True) not in (False, "false", "0", 0),
        "score": params.get("review_cut", True) not in (False, "false", "0", 0),
        "tier": params.get("tier"),
    }


def _models(params: dict, has_character: bool) -> dict:
    s = _settings(params)
    models = {
        "image": catalog.resolve("image_edit" if has_character else "image", s["tier"], params.get("image_model") or None),
    }
    if s["mode"] == "animated":
        models["video"] = catalog.resolve("image_to_video", s["tier"], params.get("video_model") or None)
    if s["voiceover"]:
        models["tts"] = catalog.resolve("tts", s["tier"], params.get("tts_model") or None)
    return models


def _clip_params(params: dict, model: dict) -> dict:
    s = _settings(params)
    out = {"duration": catalog.pick_duration(model, s["seconds"]), "aspect_ratio": s["aspect"]}
    resolution = params.get("resolution")
    if resolution in (model.get("resolutions") or []):
        out["resolution"] = resolution
    elif model.get("default_resolution"):
        out["resolution"] = model["default_resolution"]
    return out


def estimate(params: dict, counts: dict) -> dict:
    s = _settings(params)
    models = _models(params, counts.get("character", 0) > 0)
    n = s["shots"]
    items = []
    if not (params.get("script") or "").strip():
        from .. import config

        if config.has_key("ANTHROPIC_API_KEY"):
            items.append({"label": "Script (Claude)", "model": "claude", "model_name": "Claude", "usd": 0.02, "mock": False})
    items.append(line(f"{n} keyframes", models["image"], n * catalog.estimate(models["image"], {"aspect_ratio": s["aspect"]})))
    if "video" in models:
        clip = catalog.estimate(models["video"], _clip_params(params, models["video"]))
        items.append(line(f"Animate {n} shots (after storyboard approval)", models["video"], n * clip))
    if "tts" in models:
        items.append(line("Voiceover", models["tts"], n * catalog.estimate(models["tts"], {"text": "x" * CHARS_PER_SHOT})))
    if s["score"] and reviewer.available() and models["image"]["provider"] != "mock":
        items.append({"label": "Fresh-eyes review (Claude)", "model": "claude", "model_name": "Claude",
                      "usd": reviewer.ESTIMATE_USD, "mock": False})
    return total(items)


def motion_prompt(shot: dict) -> str:
    """Image-to-video prompt shaped like Take One's real-shots.md: lock, change, bans."""
    motion = shot["motion"].strip().rstrip(".")
    return (f"Everyone and everything stays exactly as in the picture: same faces, same clothes, same place. "
            f"{motion}, in real time, already in motion from the first frame. "
            "No new objects, no text, no morphing, no flicker.")


# -- stages ---------------------------------------------------------------

def _plan(job: Job) -> dict:
    path = job.path("plan.json")
    if path.exists():
        plan = json.loads(path.read_text())
    else:
        params = job.params
        s = _settings(params)
        job.status("Writing the script")
        plan, warning = planner.make_plan(
            idea=params.get("idea") or "", style=params.get("style") or "", shots=s["shots"],
            tone=params.get("tone") or "funny", tier=s["tier"] or "budget", script=params.get("script") or "",
            seconds=s["seconds"])
        if warning:
            job.data["warning"] = warning
        path.write_text(json.dumps(plan, indent=2))
        job.add_output(path, "Script (plan.json)", "file")
    # Per-shot edits made from the storyboard screen.
    for index, edits in (job.params.get("overrides") or {}).items():
        i = int(index)
        if 0 <= i < len(plan["shots"]):
            plan["shots"][i].update({k: v for k, v in edits.items() if v})
    job.data["plan"] = plan
    job.save()
    return plan


def _keyframes(job: Job, plan: dict, model: dict) -> list:
    s = _settings(job.params)
    character = first_input(job, "character")
    shots_dir = job.path("shots")
    shots_dir.mkdir(exist_ok=True)

    def one(index):
        shot = plan["shots"][index]
        prompt = f"{shot['visual']}. Style: {plan['style_bible']}. Clean, uncluttered lower third; no text or lettering."
        request = {"prompt": prompt, "aspect_ratio": s["aspect"], "num_images": 1}
        if character:
            request["prompt"] = f"Keep the character from the reference image identical. {prompt}"
            request["images"] = [str(character)]
            request["image"] = str(character)
        files = generate(job, f"key-{index}", model, request, label=f"Keyframe {index + 1}")
        image = first_of_kind(files, "image")
        dest = shots_dir / f"key-{index}{image.suffix}"
        shutil.copyfile(image, dest)
        job.add_output(dest, f"Shot {index + 1} keyframe", "image")
        return dest

    return parallel(one, list(range(len(plan["shots"]))))


def _voices(job: Job, plan: dict, model: dict | None) -> list:
    if not model:
        return [None] * len(plan["shots"])
    voice = job.params.get("voice") or model.get("default_voice")

    def one(index):
        text = plan["shots"][index]["narration"].strip()
        if not text:
            return None
        files = generate(job, f"voice-{index}", model, {"text": text, "voice": voice}, label=f"Voice {index + 1}")
        return first_of_kind(files, "audio")

    return parallel(one, list(range(len(plan["shots"]))))


def _clips(job: Job, plan: dict, keyframes: list, model: dict | None, targets: list[float]) -> list:
    s = _settings(job.params)
    size = media.size_for(s["aspect"])
    work = job.path("assemble")
    work.mkdir(exist_ok=True)

    def one(index):
        if model is None:
            return media.still_to_clip(keyframes[index], work / f"still-{index}.mp4", targets[index], size,
                                       MOTIONS[index % len(MOTIONS)])
        shot = plan["shots"][index]
        request = {"prompt": motion_prompt(shot), "image": str(keyframes[index]),
                   **_clip_params(job.params, model)}
        files = generate(job, f"clip-{index}", model, request, label=f"Animate shot {index + 1}")
        return first_of_kind(files, "video")

    return parallel(one, list(range(len(keyframes))))


def _assemble(job: Job, plan: dict, clips: list, voices: list, targets: list[float]) -> None:
    s = _settings(job.params)
    size = media.size_for(s["aspect"])
    work = job.path("assemble")
    work.mkdir(exist_ok=True)
    job.status("Editing: joining shots, voice, music and captions")
    normalized, audio_parts, cues, spoken_lines = [], [], [], []
    start = 0.0
    for i, clip in enumerate(clips):
        seconds = targets[i]
        normalized.append(media.normalize_clip(clip, work / f"shot-{i}.mp4", size, seconds))
        if voices[i]:
            audio_parts.append(media.fit_audio(voices[i], work / f"voice-{i}.wav", seconds))
        else:
            audio_parts.append(media.silence(work / f"voice-{i}.wav", seconds))
        narration = plan["shots"][i]["narration"]
        spoken = media.probe(voices[i])["duration"] if voices[i] else seconds - 0.3
        if narration:
            spoken_lines.append((start + 0.1, start + min(seconds, spoken + 0.1), narration))
        if narration and s["captions"]:
                cues += media.caption_chunks(narration, start + 0.1, start + min(seconds, spoken + 0.1),
                                         row_chars=16 if s["aspect"] in ("9:16", "3:4") else 26,
                                         highlight="#FFFFFF" if job.params.get("caption_style") == "yellow" else "#FFE500")
        start += seconds

    silent = media.concat(normalized, work / "joined.mp4")
    voice_track = media.concat_audio(audio_parts, work / "voice.wav") if any(voices) else None
    music = first_input(job, "music")
    mixed = media.mix(silent, work / "mixed.mp4", voice=voice_track, music=music,
                      music_volume=float(job.params.get("music_volume") or 0.18))
    final = job.path("final.mp4")
    if cues:
        srt = media.write_srt(cues, work / "captions.srt")
        media.burn_captions(mixed, srt, final, job.params.get("caption_style") or "bold", s["aspect"])
        shutil.copyfile(srt, job.path("captions.srt"))
        job.add_output(job.path("captions.srt"), "Captions (.srt)", "file")
    else:
        shutil.copyfile(mixed, final)
    media.thumbnail(final, job.path("thumbnail.jpg"), at=min(1.0, start / 2))
    posts = plan.get("posts") or {}
    tags = " ".join("#" + t.replace(" ", "") for t in plan.get("hashtags", []))
    lines = [f"# {plan.get('title', '')}", "", f"Takeaway: {plan.get('takeaway', '')}", "",
             "## TikTok / Reels / Shorts", "", posts.get("tiktok") or f"{plan.get('caption', '')} {tags}", "",
             "## X", "", posts.get("x") or plan.get("caption", ""), "",
             "## LinkedIn", "", posts.get("linkedin") or plan.get("caption", ""), "",
             "## Hashtags", "", tags, "",
             "Label this as AI-generated where the platform asks."]
    job.path("POSTS.md").write_text("\n".join(lines) + "\n")
    job.add_output(job.path("POSTS.md"), "Posts (TikTok, X, LinkedIn)", "file")
    job.add_output(job.path("thumbnail.jpg"), "Thumbnail", "image")
    job.add_output(final, "Final video", "video", final=True)
    job.data["shot_times"] = [round(sum(targets[:i]), 2) for i in range(len(targets))]
    job.save()
    _score(job, final, spoken_lines)


def _score(job: Job, final, spoken_lines: list) -> None:
    """Take One's fresh reviewer: a stranger's score from frames and timed words only."""
    s = _settings(job.params)
    folder = job.path("review")
    if not s["score"]:
        return
    if job.data.get("used_mock"):
        job.data["review"] = {"skipped": "Not scored: this cut used placeholder (mock) media."}
        return
    if not reviewer.available():
        job.data["review"] = {"skipped": "Add ANTHROPIC_API_KEY to get a fresh-eyes score of every short."}
        return
    if (folder / "review.json").exists():
        return
    job.status("Reviewer: scoring the cut with fresh eyes")
    budget.charge(job.id, "claude:review", reviewer.ESTIMATE_USD, note="review")
    route = "still pictures with camera moves (slideshow)" if s["mode"] == "slideshow" else "AI-animated shots"
    try:
        result = reviewer.review(final, spoken_lines, folder, locked=f"the route: {route}; the narration voice",
                                 tier=s["tier"] or "budget")
    except reviewer.ReviewError as exc:
        job.data["warning"] = f"Review skipped: {exc}"
        return
    job.data["review"] = result
    job.add_output(folder / "REVIEW.md", f"Reviewer: {result['verdict']} (overall {result['scores'].get('overall', '?')}/10)", "file")
    job.add_output(folder / "contact-sheet.jpg", "Contact sheet the reviewer saw", "image")


def run(job: Job) -> None:
    s = _settings(job.params)
    if not ((job.params.get("idea") or "").strip() or (job.params.get("script") or "").strip()):
        raise ValueError("Describe the video idea or paste a script.")
    models = _models(job.params, bool(first_input(job, "character")))
    plan = _plan(job)
    keyframes = _keyframes(job, plan, models["image"])

    if s["mode"] == "animated" and s["review"] and not job.approved("storyboard"):
        n = len(plan["shots"])
        cost = n * catalog.estimate(models["video"], _clip_params(job.params, models["video"]))
        job.wait_for("storyboard", f"Storyboard ready. Approve to animate {n} shots with "
                     f"{models['video']['name']} (~${cost:.2f}), or redo any shot first.", estimate=round(cost, 4))
        return

    voices = _voices(job, plan, models.get("tts"))
    lengths = [media.probe(v)["duration"] if v else 0.0 for v in voices]
    if s["mode"] == "animated":
        # Clip length is set by the model; hold the last frame if the line runs longer.
        clip_seconds = catalog.pick_duration(models["video"], s["seconds"])
        targets = [max(clip_seconds, length + 0.35) for length in lengths]
        clips = _clips(job, plan, keyframes, models["video"], targets)
    else:
        targets = [max(s["seconds"] if not voices[i] else 2.0, lengths[i] + 0.45) for i in range(len(keyframes))]
        clips = _clips(job, plan, keyframes, None, targets)
    _assemble(job, plan, clips, voices, targets)
