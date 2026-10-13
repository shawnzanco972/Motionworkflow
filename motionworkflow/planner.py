"""Turn a video idea into a shot list.

With ANTHROPIC_API_KEY set, Claude writes the script (hook, shots,
narration, post caption). Without it, a built-in template produces a usable
plan, or you can supply your own script lines.
"""
from __future__ import annotations

import json
import re

from . import config

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "takeaway": {"type": "string"},
        "style_bible": {"type": "string"},
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "visual": {"type": "string"},
                    "motion": {"type": "string"},
                    "narration": {"type": "string"},
                },
                "required": ["visual", "motion", "narration"],
                "additionalProperties": False,
            },
        },
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "posts": {
            "type": "object",
            "properties": {"tiktok": {"type": "string"}, "x": {"type": "string"}, "linkedin": {"type": "string"}},
            "required": ["tiktok", "x", "linkedin"],
            "additionalProperties": False,
        },
    },
    "required": ["title", "takeaway", "style_bible", "shots", "caption", "hashtags", "posts"],
    "additionalProperties": False,
}

# Craft rules adapted from the Take One skill (talsiach/take-one, MIT): words.md,
# captions.md, real-shots.md, concept-check.md. The viewer sees it once, on a
# phone, often muted.
SYSTEM = """You write scripts for short vertical videos (TikTok, Reels, Shorts) that people watch to the end. The viewer sees it once, at full speed, on a phone, often muted.

The idea
- One idea and one takeaway: the single sentence a viewer should remember. Every shot sets it up or pays it off.
- Shot 1 is the hook: a striking picture and a first line that make people stay. The last shot is the payoff (a twist or punchline) worth rewatching.
- Comedy: a line is funny when it contradicts what is on screen, not when it is a familiar phrase.
- Use only what the person gave you. No real people, celebrities, brands, logos or copyrighted characters; no claims, numbers, prices or links they did not give.

The words (narration)
- Written to be understood on one hearing with no context: conversational, short sentences, one idea each, no trade words.
- Budget about two words per second of the shot (the per-shot word budget is given). Cut lines, not pace.
- After an aside, name the subject again instead of "it/this/that".
- No stage directions, emoji or hashtags in narration.

The pictures (visual)
- Each `visual` is a complete, self-contained image prompt: subject, action, setting, light, camera framing. Never refer to other shots.
- Caught, not posed: people and creatures mid-action, not smiling at the lens.
- Leave clean space in the lower third for captions; nothing important there. Never ask for text, signs, logos or lettering in the picture.
- Put the recurring look in `style_bible`: the art style plus a precise plain description of any recurring character (species/age, build, hair or fur, clothes, colours), worded the same way every time. It is appended to every visual prompt, so do not repeat it in `visual`.

The motion
- `motion` is for an image-to-video model: one small action per character or object, plus one small, slow camera move. Under 25 words. Describe the change, not the scene.

The posts
- `caption`: the post description, 1-2 lines. `hashtags`: 3-6 relevant tags without '#', no hashtag walls.
- `posts.tiktok`: a hook under 15 words plus at most one line. `posts.x`: short, hook first. `posts.linkedin`: a fuller first-person sentence or two, no hashtags. Say it is AI-made where natural; no hype words like "insane"."""

BEATS = [
    ("hook", "a surprising opening moment"),
    ("setup", "establishing the situation"),
    ("escalation", "things get more absurd"),
    ("complication", "an unexpected problem appears"),
    ("climax", "the most dramatic moment"),
    ("twist", "a surprising reveal"),
    ("payoff", "the funny final punchline"),
    ("outro", "a satisfying ending shot"),
]


class PlannerError(RuntimeError):
    pass


def _clean(plan: dict, shots: int) -> dict:
    plan["shots"] = [s for s in plan.get("shots", []) if s.get("visual")][: max(1, shots)]
    if not plan["shots"]:
        raise PlannerError("The plan has no shots.")
    plan["hashtags"] = [re.sub(r"^#", "", h).strip() for h in plan.get("hashtags", []) if h.strip()]
    plan.setdefault("takeaway", plan.get("caption", ""))
    plan.setdefault("posts", _default_posts(plan.get("title", ""), plan.get("caption", ""), plan["hashtags"]))
    return plan


def from_script(script: str, style: str, title: str = "") -> dict:
    """Each line: narration | visual prompt | motion  (visual and motion optional)."""
    shots = []
    for raw in script.splitlines():
        if not raw.strip():
            continue
        parts = [p.strip() for p in raw.split("|")]
        narration = parts[0]
        visual = parts[1] if len(parts) > 1 and parts[1] else narration
        motion = parts[2] if len(parts) > 2 and parts[2] else "subtle natural movement, slow push-in"
        shots.append({"visual": visual, "motion": motion, "narration": narration})
    if not shots:
        raise PlannerError("The script is empty.")
    caption = title or shots[0]["narration"]
    return {"title": title or shots[0]["narration"][:60], "takeaway": caption, "style_bible": style, "shots": shots,
            "caption": caption, "hashtags": [], "posts": _default_posts(caption, caption, []), "planner": "script"}


def _default_posts(title: str, caption: str, hashtags: list[str]) -> dict:
    tags = " ".join("#" + h for h in hashtags[:5])
    return {"tiktok": f"{caption} {tags}".strip(), "x": caption, "linkedin": f"{caption} Made with AI."}


def template(idea: str, style: str, shots: int) -> dict:
    """Offline fallback: a beat-sheet built from the idea itself."""
    middle = BEATS[1:6]
    if shots <= 1:
        beats = BEATS[:1]
    else:
        beats = [BEATS[0], *(middle[i % len(middle)] for i in range(shots - 2)), BEATS[6]]
    plan_shots = []
    for name, description in beats:
        plan_shots.append({
            "visual": f"{idea}, {description}, cinematic composition, expressive faces, vivid detail",
            "motion": "natural character movement, slow camera push-in",
            "narration": f"{name.capitalize()}: {idea}." if name != "hook" else f"Wait for it... {idea}.",
        })
    tags = ["funny", "aivideo", "shorts"]
    return {"title": idea[:80], "takeaway": idea, "style_bible": style, "shots": plan_shots, "caption": idea,
            "hashtags": tags, "posts": _default_posts(idea, idea, tags), "planner": "template"}


def claude_plan(idea: str, style: str, shots: int, tone: str, tier: str, seconds: float = 5) -> dict:
    import anthropic

    model = config.setting("MW_PLANNER_MODEL_BUDGET" if tier in ("free", "budget") else "MW_PLANNER_MODEL")
    client = anthropic.Anthropic(api_key=config.credential("ANTHROPIC_API_KEY"))
    words = max(4, int(seconds * 2))
    prompt = (f"Video idea: {idea}\nVisual style: {style}\nTone: {tone}\nNumber of shots: exactly {shots}\n"
              f"Each shot lasts about {seconds:g} s, so narration budget is about {words} words per shot "
              f"(total film about {shots * seconds:g} s).\nWrite the plan.")
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")):
            # Server-side fallback reruns a declined request on a suitable model.
            response = client.beta.messages.create(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise PlannerError("ANTHROPIC_API_KEY was rejected. Check the key in .env.") from exc
    except anthropic.RateLimitError as exc:
        raise PlannerError("Claude rate limit reached; try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise PlannerError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise PlannerError("Could not reach the Claude API.") from exc
    if response.stop_reason == "refusal":
        raise PlannerError("Claude declined this idea. Try rephrasing it.")
    if response.stop_reason == "max_tokens":
        raise PlannerError("The plan was cut off; ask for fewer shots.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        plan = json.loads(text)
    except ValueError as exc:
        raise PlannerError("Claude returned an unreadable plan.") from exc
    plan["planner"] = model
    return plan


def make_plan(idea: str, style: str = "", shots: int = 5, tone: str = "funny", tier: str = "budget",
              script: str = "", seconds: float = 5) -> tuple[dict, str | None]:
    """Return (plan, warning). Never spends money on media."""
    style = style or "vibrant 3D animated film style, soft lighting"
    if script.strip():
        return _clean(from_script(script, style, idea), 100), None
    if not idea.strip():
        raise PlannerError("Describe the video idea or paste a script.")
    if config.has_key("ANTHROPIC_API_KEY"):
        try:
            return _clean(claude_plan(idea, style, shots, tone, tier, seconds), shots), None
        except PlannerError as exc:
            return _clean(template(idea, style, shots), shots), f"Claude planning failed ({exc}); used the built-in template."
    return _clean(template(idea, style, shots), shots), (
        "No ANTHROPIC_API_KEY: used the built-in template. Add a key for real scripts, or paste your own script.")
