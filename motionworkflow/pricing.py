"""The price guide: what typical things cost at each quality tier.

Prices come from the same estimators the forms use, priced as if every
provider key were set, so the guide shows real model prices even before you
add a key. Like every estimate here, they come from catalog prices; your
provider's bill is the source of truth.
"""
from __future__ import annotations

from . import catalog, config

TIERS = ("free", "budget", "standard", "premium")

# id, workflow, title, what it includes, params, counts
RECIPES = [
    ("image-1", "image", "One image", "A single picture from a prompt", {"prompt": "x", "num_images": 1}, {}),
    ("image-4", "image", "Four images", "Four takes to pick from", {"prompt": "x", "num_images": 4}, {}),
    ("voice-1m", "voice", "1 minute voiceover", "About 150 words, in your cloned voice",
     {"text": "x" * 900}, {"voice_sample": 1}),
    ("short-slides", "short", "Narrated short, 5 shots", "Script, 5 pictures with gentle motion, voice, captions",
     {"idea": "x", "shots": 5, "mode": "slideshow"}, {}),
    ("short-animated", "short", "Animated short, 5 shots", "As above, with every shot animated (5 s each)",
     {"idea": "x", "shots": 5, "mode": "animated", "shot_seconds": 5}, {}),
    ("video-5", "video", "5 second video clip", "Text-to-video, with a cheap draft first",
     {"prompt": "x", "duration": 5}, {}),
    ("presenter-30", "presenter", "30 s presenter video", "You talking: script, your voice, your photo animated",
     {"topic": "x", "seconds": 30, "avatar_id": "x"}, {"avatar": 1, "voice_sample": 1}),
    ("presenter-60", "presenter", "60 s presenter video", "Same, one minute",
     {"topic": "x", "seconds": 60, "avatar_id": "x"}, {"avatar": 1, "voice_sample": 1}),
    ("presenter-60-video", "presenter", "60 s presenter, video avatar",
     "Your own 10-20 s clip lip-synced instead of a photo animated: much cheaper",
     {"topic": "x", "seconds": 60, "avatar_id": "x"}, {"avatar": 1, "voice_sample": 1, "avatar_is_video": True}),
    ("swap-10", "swap", "10 s character swap", "Replace the person in a clip with your character",
     {"source_seconds": 10}, {"video": 1, "refs": 1}),
]


def _price(workflow: str, params: dict, counts: dict, tier: str) -> dict | None:
    from . import workflows

    try:
        quote = workflows.estimate(workflow, {**params, "tier": tier}, counts)
    except (ValueError, catalog.CatalogError, config.MissingKey):
        return None
    return {
        "usd": round(quote["total"], 4),
        "models": sorted({i.get("model_name") or i.get("model") for i in quote["items"]}),
    }


def guide() -> dict:
    cap = config.number("MW_MAX_COST_PER_JOB")
    rows = []
    with config.assume_all_keys():
        for rid, workflow, title, detail, params, counts in RECIPES:
            prices = {tier: _price(workflow, dict(params), counts, tier) for tier in TIERS}
            # A tier that resolves to the same models as a cheaper one adds nothing: hide the repeat.
            seen = []
            for tier in TIERS:
                p = prices[tier]
                if p is not None:
                    key = (p["usd"], tuple(p["models"]))
                    if key in seen:
                        prices[tier] = {**p, "same_as_cheaper": True}
                    seen.append(key)
                    p = prices[tier]
                    p["over_cap"] = p["usd"] > cap
            rows.append({"id": rid, "workflow": workflow, "title": title, "detail": detail, "prices": prices})
    return {"tiers": list(TIERS), "rows": rows, "max_cost_per_job": cap}


def starting_prices() -> dict[str, float]:
    """The cheapest paid way into each service, for the home page cards."""
    out: dict[str, float] = {}
    for row in guide()["rows"]:
        for tier in TIERS:
            p = row["prices"][tier]
            if p and p["usd"] > 0:
                out[row["workflow"]] = min(out.get(row["workflow"], p["usd"]), p["usd"])
                break
    return out
