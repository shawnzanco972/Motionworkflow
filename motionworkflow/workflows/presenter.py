"""Presenter: you, talking to camera about any topic.

topic (or your script) -> script -> your cloned voice, line by line ->
[you approve the script and the voice] -> your avatar speaks it (a photo via a
talking-head model, or your own short video via lip-sync) -> optional B-roll
cutaways -> captions, music, posts, fresh-eyes score.

The expensive step (animating the avatar) only starts after you have heard
the voice and read the script.
"""
from __future__ import annotations

import json
import shutil

from .. import budget, catalog, media, planner, reviewer
from ..jobs import Job
from ..providers.base import VIDEO_EXT
from .common import first_input, first_of_kind, generate, line, parallel, total

GAP = 0.28           # pause between lines, seconds
WORDS_PER_SECOND = 2.3
CHARS_PER_WORD = 5.6


def _flag(params: dict, name: str, default: bool) -> bool:
    value = params.get(name, default)
    return value not in (False, "false", "0", 0, "off", None)


def _settings(params: dict) -> dict:
    return {
        "seconds": max(10.0, min(180.0, float(params.get("seconds") or 30))),
        "aspect": params.get("aspect_ratio") or "9:16",
        "broll": _flag(params, "broll", False),
        "captions": _flag(params, "captions", True),
        "review": _flag(params, "review", True),
        "score": _flag(params, "review_cut", True),
        "tier": params.get("tier"),
    }


def _avatar_is_video(job_or_counts) -> bool:
    if isinstance(job_or_counts, dict):
        return bool(job_or_counts.get("avatar_is_video"))
    avatar = first_input(job_or_counts, "avatar")
    return bool(avatar and avatar.suffix.lower() in VIDEO_EXT)


def _models(params: dict, has_sample: bool, avatar_video: bool) -> dict:
    s = _settings(params)
    models = {
        "voice": catalog.resolve("voice_clone" if has_sample else "tts", s["tier"], params.get("voice_model") or None),
        "face": catalog.resolve("lipsync" if avatar_video else "talking_head", s["tier"], params.get("avatar_model") or None),
    }
    if s["broll"]:
        models["image"] = catalog.resolve("image", s["tier"], params.get("image_model") or None)
    return models


def _face_cost(model: dict, seconds: float) -> float:
    if model.get("price", {}).get("unit") == "video":
        parts = max(1, -(-int(seconds) // int(model.get("max_seconds") or 60)))
        return parts * catalog.unit_price(model, {})
    return catalog.estimate(model, {"source_seconds": seconds, "resolution": model.get("default_resolution")})


def estimate(params: dict, counts: dict) -> dict:
    s = _settings(params)
    models = _models(params, counts.get("voice_sample", 0) > 0 or bool(params.get("voice_id")),
                     _avatar_is_video(counts))
    chars = int(s["seconds"] * WORDS_PER_SECOND * CHARS_PER_WORD)
    items = []
    from .. import config

    if not (params.get("script") or "").strip() and config.has_key("ANTHROPIC_API_KEY"):
        items.append({"label": "Script (Claude)", "model": "claude", "model_name": "Claude", "usd": 0.02, "mock": False})
    items.append(line("Your voice", models["voice"], catalog.estimate(models["voice"], {"text": "x" * chars})))
    items.append(line(f"Animate your avatar (~{s['seconds']:.0f} s, after you approve)", models["face"],
                      _face_cost(models["face"], s["seconds"])))
    if "image" in models:
        n = max(1, round(s["seconds"] / 10))
        items.append(line(f"{n} B-roll pictures", models["image"], n * catalog.estimate(models["image"], {"aspect_ratio": s["aspect"]})))
    if s["score"] and reviewer.available() and models["face"]["provider"] != "mock":
        items.append({"label": "Fresh-eyes review (Claude)", "model": "claude", "model_name": "Claude",
                      "usd": reviewer.ESTIMATE_USD, "mock": False})
    return total(items)


# -- stages -------------------------------------------------------------------

def _plan(job: Job) -> dict:
    path = job.path("plan.json")
    s = _settings(job.params)
    if path.exists():
        plan = json.loads(path.read_text())
    else:
        job.status("Writing your script")
        plan, warning = planner.presenter_plan(
            topic=job.params.get("topic") or "", seconds=s["seconds"], tone=job.params.get("tone") or "friendly expert",
            language=job.params.get("language") or "English", tier=s["tier"] or "budget",
            script=job.params.get("script") or "", broll=s["broll"], audience=job.params.get("audience") or "")
        if warning:
            job.data["warning"] = warning
        path.write_text(json.dumps(plan, indent=2))
        job.add_output(path, "Script (plan.json)", "file")
    for index, edits in (job.params.get("overrides") or {}).items():
        i = int(index)
        if 0 <= i < len(plan["lines"]):
            plan["lines"][i].update({k: v for k, v in edits.items() if isinstance(v, str)})
    job.data["plan"] = plan
    job.save()
    return plan


def _voice(job: Job, plan: dict, model: dict) -> tuple:
    """One TTS call per line (exact timings, cheap redo of a single line)."""
    sample = first_input(job, "voice_sample")
    limit = int(model.get("max_chars") or 600)

    def one(index):
        text = plan["lines"][index]["text"].strip()[:limit]
        request = {"text": text}
        if sample:
            request["voice_sample"] = str(sample)
            if job.params.get("voice_transcript"):
                request["ref_text"] = job.params["voice_transcript"]
        else:
            request["voice"] = job.params.get("voice") or model.get("default_voice")
        files = generate(job, f"voice-{index}", model, request, label=f"Voice line {index + 1}")
        return first_of_kind(files, "audio")

    parts = parallel(one, list(range(len(plan["lines"]))))
    work = job.path("assemble")
    work.mkdir(exist_ok=True)
    pieces, times, t = [], [], 0.0
    for i, part in enumerate(parts):
        seconds = media.probe(part)["duration"]
        fitted = media.fit_audio(part, work / f"line-{i}.wav", seconds + GAP)
        pieces.append(fitted)
        times.append((round(t, 3), round(t + seconds, 3)))
        t += seconds + GAP
    voice = media.concat_audio(pieces, job.path("voice.wav"))
    job.data["line_times"] = times
    job.add_output(voice, "Your voice track", "audio")
    job.save()
    return voice, times


def _segments(times: list, max_seconds: float) -> list[tuple[float, float]]:
    """Group whole lines into pieces the avatar model can take in one call."""
    segments, start = [], 0.0
    end_of = [times[i + 1][0] if i + 1 < len(times) else times[i][1] + GAP for i in range(len(times))]
    for i, end in enumerate(end_of):
        if end - start > max_seconds and i > 0 and end_of[i - 1] > start:
            segments.append((start, end_of[i - 1]))
            start = end_of[i - 1]
    segments.append((start, end_of[-1]))
    # A single line longer than the limit is cut at the limit.
    out = []
    for a, b in segments:
        while b - a > max_seconds:
            out.append((a, a + max_seconds))
            a += max_seconds
        out.append((a, b))
    return out


def _animate(job: Job, voice, times: list, model: dict) -> list:
    avatar = first_input(job, "avatar")
    is_video = avatar.suffix.lower() in VIDEO_EXT
    work = job.path("assemble")
    pieces = _segments(times, float(model.get("max_seconds") or 60))

    def one(item):
        k, (a, b) = item
        audio = work / f"segment-{k}.wav"
        if not audio.exists():
            media.run(["-i", voice, "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", audio])
        request = {"audio_file": str(audio), "source_seconds": round(b - a, 2),
                   "prompt": "The person speaks naturally to the camera with small, natural head movements."}
        request["video" if is_video else "image"] = str(avatar)
        files = generate(job, f"face-{k}", model, request, label=f"Animate part {k + 1}",
                         estimate=_face_cost(model, b - a))
        return first_of_kind(files, "video"), b - a

    return parallel(one, list(enumerate(pieces)))


def _broll(job: Job, plan: dict, model: dict | None) -> dict[int, object]:
    if not model:
        return {}
    s = _settings(job.params)
    wanted = [i for i, ln in enumerate(plan["lines"]) if ln.get("broll", "").strip()]

    def one(i):
        prompt = f"{plan['lines'][i]['broll']}. Clean, uncluttered lower third; no text or lettering."
        files = generate(job, f"broll-{i}", model, {"prompt": prompt, "aspect_ratio": s["aspect"], "num_images": 1},
                         label=f"B-roll for line {i + 1}")
        return i, first_of_kind(files, "image")

    return dict(parallel(one, wanted))


def _assemble(job: Job, plan: dict, voice, times: list, faces: list, broll: dict) -> None:
    s = _settings(job.params)
    size = media.size_for(s["aspect"])
    work = job.path("assemble")
    job.status("Editing: your presenter, cutaways, captions and music")
    # One continuous presenter track at the target size.
    normalized = [media.normalize_clip(clip, work / f"face-{k}.mp4", size, seconds) for k, (clip, seconds) in enumerate(faces)]
    presenter = media.concat(normalized, work / "presenter.mp4")
    total_seconds = media.probe(voice)["duration"]
    # Cut it into line windows, swapping in B-roll where the script asks for it.
    windows = []
    for i, (start, _end) in enumerate(times):
        end = times[i + 1][0] if i + 1 < len(times) else total_seconds
        if end - start < 0.05:
            continue
        clip = work / f"window-{i}.mp4"
        if i in broll:
            media.still_to_clip(broll[i], clip, end - start, size, ["zoom_in", "pan_right", "zoom_out"][i % 3])
        else:
            media.run(["-ss", f"{start:.3f}", "-i", presenter, "-t", f"{end - start:.3f}", "-an",
                       "-vf", f"fps={media.FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", clip])
        windows.append(clip)
    silent = media.concat(windows, work / "cut.mp4")
    mixed = media.mix(silent, work / "mixed.mp4", voice=voice, music=first_input(job, "music"),
                      music_volume=float(job.params.get("music_volume") or 0.12))
    final = job.path("final.mp4")
    cues = []
    if s["captions"]:
        for i, (start, end) in enumerate(times):
            cues += media.caption_chunks(plan["lines"][i]["text"], start, end,
                                         row_chars=16 if s["aspect"] in ("9:16", "3:4") else 26)
    if cues:
        srt = media.write_srt(cues, work / "captions.srt")
        media.burn_captions(mixed, srt, final, job.params.get("caption_style") or "bold", s["aspect"])
        shutil.copyfile(srt, job.path("captions.srt"))
        job.add_output(job.path("captions.srt"), "Captions (.srt)", "file")
    else:
        shutil.copyfile(mixed, final)
    media.thumbnail(final, job.path("thumbnail.jpg"), at=min(1.0, total_seconds / 3))
    posts = plan.get("posts") or {}
    tags = " ".join("#" + t.replace(" ", "") for t in plan.get("hashtags", []))
    job.path("POSTS.md").write_text("\n".join([
        f"# {plan.get('title', '')}", "", f"Takeaway: {plan.get('takeaway', '')}", "",
        "## TikTok / Reels / Shorts", "", posts.get("tiktok") or plan.get("caption", ""), "",
        "## X", "", posts.get("x") or plan.get("caption", ""), "",
        "## LinkedIn", "", posts.get("linkedin") or plan.get("caption", ""), "",
        "## Hashtags", "", tags, "", "Your voice and face are AI-generated in this video: label it where the platform asks.", ""]))
    job.add_output(job.path("POSTS.md"), "Posts (TikTok, X, LinkedIn)", "file")
    job.add_output(job.path("thumbnail.jpg"), "Thumbnail", "image")
    job.add_output(final, "Final video", "video", final=True)
    job.data["shot_times"] = [t[0] for t in times]
    job.save()
    _score(job, final, plan, times)


def _score(job: Job, final, plan: dict, times: list) -> None:
    s = _settings(job.params)
    folder = job.path("review")
    if not s["score"] or (folder / "review.json").exists():
        return
    if job.data.get("used_mock"):
        job.data["review"] = {"skipped": "Not scored: this cut used placeholder (mock) media."}
        return
    if not reviewer.available():
        job.data["review"] = {"skipped": "Add ANTHROPIC_API_KEY to get a fresh-eyes score."}
        return
    job.status("Reviewer: scoring the cut with fresh eyes")
    budget.charge(job.id, "claude:review", reviewer.ESTIMATE_USD, note="review")
    words = [(a, b, plan["lines"][i]["text"]) for i, (a, b) in enumerate(times)]
    try:
        result = reviewer.review(final, words, folder, locked="the presenter's face and voice (they are the owner's)",
                                 tier=s["tier"] or "budget")
    except reviewer.ReviewError as exc:
        job.data["warning"] = f"Review skipped: {exc}"
        return
    job.data["review"] = result
    job.add_output(folder / "REVIEW.md", f"Reviewer: {result['verdict']} (overall {result['scores'].get('overall', '?')}/10)", "file")


def run(job: Job) -> None:
    params = job.params
    if not ((params.get("topic") or "").strip() or (params.get("script") or "").strip()):
        raise ValueError("Say what the video is about, or paste your script.")
    if not first_input(job, "avatar"):
        raise ValueError("Choose an avatar: a clear photo of you, or 10-20 s of video looking at the camera.")
    s = _settings(params)
    models = _models(params, bool(first_input(job, "voice_sample")), _avatar_is_video(job))
    plan = _plan(job)
    voice, times = _voice(job, plan, models["voice"])
    seconds = media.probe(voice)["duration"]
    job.data["voice_seconds"] = round(seconds, 2)

    if s["review"] and not job.approved("voice"):
        cost = _face_cost(models["face"], seconds)
        job.wait_for("voice", f"Script and voice ready ({seconds:.0f} s). Listen and read it through, fix any line, "
                     f"then approve to animate your avatar with {models['face']['name']} (~${cost:.2f}).",
                     estimate=round(cost, 4))
        return

    broll = _broll(job, plan, models.get("image"))
    faces = _animate(job, voice, times, models["face"])
    _assemble(job, plan, voice, times, faces, broll)
