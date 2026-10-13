"""Fresh-eyes review of a finished video, adapted from Take One's reviewer.

The reviewer sees only what a viewer would: frames from the exported file and
the words with their times (it cannot hear). It never sees the script, the
prompts or the storyboard, so it stands in for a stranger on a phone. Its score
is the score: PASS only when every axis is 8 or more, and that rule is applied
here in code, not taken from the model's word.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from . import config, media

AXES = ["hook", "readability", "motion", "variety", "composition", "sound_sync", "overall"]
BAR = 8
ESTIMATE_USD = 0.03

SCHEMA = {
    "type": "object",
    "properties": {
        "retell": {"type": "string"},
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string", "enum": AXES},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["axis", "score", "reason"],
                "additionalProperties": False,
            },
        },
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"time": {"type": "number"}, "problem": {"type": "string"}},
                "required": ["time", "problem"],
                "additionalProperties": False,
            },
        },
        "looks_off": {"type": "string"},
    },
    "required": ["retell", "scores", "problems", "looks_off"],
    "additionalProperties": False,
}

BRIEF = """You are the reviewer for a short video. You have seen none of the work behind it, and that is the point: you stand in for a stranger who sees it once, at full speed, on a phone, possibly muted. Be honest and specific; a kind score is useless, and so is a harsh one not tied to something visible.

You get: a contact sheet with one frame per second (each labelled with its time), the first frame and the last frame at full size, and a list of every spoken line with its time (you cannot hear; the voice is narration and there may be a music bed under it).

What is locked (do not spend problems on it): {locked}
Where it posts: {audience}

Report:
1. retell: the video in one sentence, as a viewer would tell a friend. If you could not follow something, say what.
2. scores, 1-10 with one line of reason each, for every axis: hook (first 2 s: is frame 0 striking and the premise clear by 2 s), readability (every caption readable at phone size, for long enough, high contrast, not on faces), motion (does it feel alive or like a slideshow), variety (something new every 2-4 s), composition (one focal point, clean space for captions, nothing cut by an edge), sound_sync (do the words fit what is on screen at that time), overall (against what good creators post).
3. problems: the three worst problems, each with its time in seconds and exactly what is wrong.
4. looks_off: anything that looks off, cheap or wrong at full size (hands, faces, anatomy, garbled text, edges). Empty if nothing."""


class ReviewError(RuntimeError):
    pass


def available() -> bool:
    return config.has_key("ANTHROPIC_API_KEY")


def _png(image: Image.Image, max_side: int = 1568) -> str:
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def contact_sheet(video: Path, out: Path, every: float = 1.0, width: int = 360, columns: int = 5) -> Path:
    """One phone-width frame per second, labelled with its time."""
    tmp = Path(tempfile.mkdtemp(prefix="sheet-"))
    try:
        media.run(["-i", video, "-vf", f"fps=1/{every},scale={width}:-2", "-frames:v", "40", tmp / "f%03d.jpg"])
        frames = sorted(tmp.glob("f*.jpg"))
        if not frames:
            raise ReviewError("Could not read frames from the video.")
        with Image.open(frames[0]) as first:
            w, h = first.size
        rows = -(-len(frames) // columns)
        sheet = Image.new("RGB", (columns * w, rows * h), "black")
        draw = ImageDraw.Draw(sheet)
        for i, path in enumerate(frames):
            x, y = (i % columns) * w, (i // columns) * h
            with Image.open(path) as frame:
                sheet.paste(frame, (x, y))
            draw.rectangle([x, y, x + 54, y + 20], fill="black")
            draw.text((x + 4, y + 4), f"{i * every:.0f}s", fill="white")
        sheet.save(out, quality=88)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _frame(video: Path, at: float) -> Image.Image:
    tmp = Path(tempfile.mkdtemp(prefix="frame-"))
    try:
        target = tmp / "f.jpg"
        if at < 0:
            media.run(["-sseof", "-0.2", "-i", video, "-frames:v", "1", "-update", "1", target])
        else:
            media.run(["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", target])
        return Image.open(target).copy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def review(video: Path, words: list[tuple[float, float, str]], folder: Path, audience: str = "TikTok / Reels / Shorts",
           locked: str = "nothing", tier: str = "budget") -> dict:
    """Score a finished video. Writes contact-sheet.jpg, review.json and REVIEW.md into `folder`."""
    import anthropic

    folder.mkdir(parents=True, exist_ok=True)
    sheet = contact_sheet(video, folder / "contact-sheet.jpg")
    spoken = "\n".join(f"{a:5.1f}s-{b:5.1f}s  {t}" for a, b, t in words) or "(no spoken words)"
    content = [
        {"type": "text", "text": "Contact sheet, one frame per second:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _png(Image.open(sheet), 3000)}},
        {"type": "text", "text": "First frame:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _png(_frame(video, 0))}},
        {"type": "text", "text": "Last frame:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _png(_frame(video, -1))}},
        {"type": "text", "text": f"Length: {media.probe(video)['duration']:.1f} s\nSpoken lines with times:\n{spoken}"},
    ]
    model = config.setting("MW_REVIEWER_MODEL_BUDGET" if tier in ("free", "budget") else "MW_REVIEWER_MODEL")
    client = anthropic.Anthropic(api_key=config.credential("ANTHROPIC_API_KEY"))
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=BRIEF.format(locked=locked, audience=audience),
        messages=[{"role": "user", "content": content}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")):
            response = client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"],
                                                   fallbacks="default")
        else:
            response = client.messages.create(**kwargs)
    except anthropic.APIStatusError as exc:
        raise ReviewError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ReviewError("Could not reach the Claude API.") from exc
    if response.stop_reason in ("refusal", "max_tokens"):
        raise ReviewError(f"The reviewer stopped early ({response.stop_reason}).")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ReviewError("The reviewer returned an unreadable report.") from exc
    scores = {s["axis"]: max(1, min(10, int(s["score"]))) for s in data["scores"]}
    missing = [a for a in AXES if a not in scores]
    result = {
        "model": model,
        "retell": data["retell"],
        "scores": scores,
        "reasons": {s["axis"]: s["reason"] for s in data["scores"]},
        "problems": sorted(data["problems"], key=lambda p: p["time"])[:3],
        "looks_off": data.get("looks_off", ""),
        # The verdict is computed, never taken from the model.
        "verdict": "PASS" if not missing and all(scores[a] >= BAR for a in AXES) else "RETURN",
        "missing_axes": missing,
    }
    (folder / "review.json").write_text(json.dumps(result, indent=2))
    (folder / "REVIEW.md").write_text(as_markdown(result))
    return result


def as_markdown(result: dict) -> str:
    lines = [f"# Fresh-eyes review: {result['verdict']}", "", f"_{result['retell']}_", "",
             "| Axis | Score | Why |", "|---|---|---|"]
    for axis in AXES:
        if axis in result["scores"]:
            lines.append(f"| {axis} | {result['scores'][axis]} | {result['reasons'].get(axis, '')} |")
    lines += ["", "## Three worst problems", ""]
    lines += [f"- {p['time']:.1f}s: {p['problem']}" for p in result["problems"]]
    if result.get("looks_off"):
        lines += ["", "## Looks off", "", result["looks_off"]]
    lines += ["", f"Bar: {BAR} on every axis. Reviewer: {result['model']} (saw only frames and timed words)."]
    return "\n".join(lines) + "\n"
