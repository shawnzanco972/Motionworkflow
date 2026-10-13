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
    },
    "required": ["title", "style_bible", "shots", "caption", "hashtags"],
    "additionalProperties": False,
}

SYSTEM = """You write scripts for short vertical videos (TikTok, Reels, Shorts) that get watched to the end.

Rules:
- Shot 1 is the hook: a surprising image and a first line that makes people stay.
- Each later shot escalates; the last shot pays off with a twist or punchline.
- `visual` is a complete, self-contained image-generation prompt: subject, action, setting, lighting, camera framing. Never refer to other shots ("same as before").
- Put the recurring look in `style_bible`: art style plus a precise description of any recurring character (age, build, hair, clothing, colors). It is appended to every visual prompt, so do not repeat it inside `visual`.
- `motion` describes movement for an image-to-video model: one clear action plus a camera move, under 25 words.
- `narration` is the voiceover for that shot: conversational, at most 22 words, no stage directions or emoji.
- `caption` is the post description (1-2 lines); `hashtags` are 3-6 relevant tags without '#'.
- Keep it original: no real celebrities, brands, or copyrighted characters."""

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
    return {"title": title or shots[0]["narration"][:60], "style_bible": style, "shots": shots,
            "caption": title or shots[0]["narration"], "hashtags": [], "planner": "script"}


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
    return {"title": idea[:80], "style_bible": style, "shots": plan_shots, "caption": idea,
            "hashtags": ["funny", "aivideo", "shorts"], "planner": "template"}


def claude_plan(idea: str, style: str, shots: int, tone: str, tier: str) -> dict:
    import anthropic

    model = config.setting("MW_PLANNER_MODEL_BUDGET" if tier in ("free", "budget") else "MW_PLANNER_MODEL")
    client = anthropic.Anthropic(api_key=config.credential("ANTHROPIC_API_KEY"))
    prompt = (f"Video idea: {idea}\nVisual style: {style}\nTone: {tone}\nNumber of shots: exactly {shots}\n"
              "Write the plan.")
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
              script: str = "") -> tuple[dict, str | None]:
    """Return (plan, warning). Never spends money on media."""
    style = style or "vibrant 3D animated film style, soft lighting"
    if script.strip():
        return _clean(from_script(script, style, idea), 100), None
    if not idea.strip():
        raise PlannerError("Describe the video idea or paste a script.")
    if config.has_key("ANTHROPIC_API_KEY"):
        try:
            return _clean(claude_plan(idea, style, shots, tone, tier), shots), None
        except PlannerError as exc:
            return _clean(template(idea, style, shots), shots), f"Claude planning failed ({exc}); used the built-in template."
    return _clean(template(idea, style, shots), shots), (
        "No ANTHROPIC_API_KEY: used the built-in template. Add a key for real scripts, or paste your own script.")
