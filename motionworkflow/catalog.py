"""Model catalog: which models exist, what they cost, and how to call them.

The data lives in models.json. Drop a `models.local.json` next to `.env`
with the same shape to add models or override prices without touching the
shipped file; entries with the same id replace the shipped ones.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

from . import config

KINDS = ("image", "image_edit", "video", "image_to_video", "swap", "tts", "voice_clone", "talking_head", "lipsync")
TIERS = ("free", "budget", "standard", "premium")

# Approximate output megapixels for fal's image_size presets, used for pricing.
_MEGAPIXELS = {"1:1": 1.05, "16:9": 0.59, "9:16": 0.59, "4:3": 0.79, "3:4": 0.79}


class CatalogError(ValueError):
    pass


@lru_cache(maxsize=1)
def _load() -> dict:
    data = json.loads((config.PACKAGE / "models.json").read_text())
    local = config.ROOT / "models.local.json"
    if local.exists():
        extra = json.loads(local.read_text())
        by_id = {m["id"]: m for m in data["models"]}
        for model in extra.get("models", []):
            by_id[model["id"]] = {**by_id.get(model["id"], {}), **model}
        data["models"] = list(by_id.values())
        for kind, tiers in extra.get("defaults", {}).items():
            data["defaults"].setdefault(kind, {}).update(tiers)
    return data


def reload() -> None:
    _load.cache_clear()


def models() -> list[dict]:
    return _load()["models"]


def get(model_id: str) -> dict:
    for model in models():
        if model["id"] == model_id:
            return model
    raise CatalogError(f"Unknown model '{model_id}'. See Settings → Models & prices (or `mw models`).")


def kinds_of(model: dict) -> list[str]:
    return [model["kind"], *model.get("also", [])]


def for_kind(kind: str) -> list[dict]:
    return [m for m in models() if kind in kinds_of(m)]


def available(model: dict) -> bool:
    return config.providers_status().get(model["provider"], False)


def resolve(kind: str, tier: str | None = None, model_id: str | None = None) -> dict:
    """Pick an explicit model, or the first model in the tier whose provider has a key.

    Falls back to cheaper tiers, then to free/mock models, so the app always
    runs end-to-end even before any API key is added.
    """
    if kind not in KINDS:
        raise CatalogError(f"Unknown kind '{kind}'.")
    if model_id:
        model = get(model_id)
        if kind not in kinds_of(model):
            raise CatalogError(f"{model_id} is a {model['kind']} model, not {kind}.")
        if not available(model):
            raise config.MissingKey(_key_for(model["provider"]))
        return model
    tier = tier or config.setting("MW_DEFAULT_TIER")
    if tier not in TIERS:
        raise CatalogError(f"Unknown tier '{tier}'. Use one of {', '.join(TIERS)}.")
    defaults = _load()["defaults"].get(kind, {})
    order = list(TIERS[TIERS.index(tier)::-1]) + list(TIERS[TIERS.index(tier) + 1:])
    for candidate_tier in order:
        for candidate in defaults.get(candidate_tier, []):
            model = get(candidate)
            if available(model):
                return model
    mock = f"mock:{kind.replace('_', '-')}"
    if config.providers_status().get("mock"):
        return get(mock)
    raise CatalogError(f"No configured provider can run '{kind}'. Add an API key in .env.")


def _key_for(provider: str) -> str:
    for key, name in config.KEYS.items():
        if name == provider:
            return key
    return provider.upper() + "_API_KEY"


def unit_price(model: dict, params: dict) -> float:
    price = model.get("price", {})
    by_res = price.get("by_resolution")
    resolution = params.get("resolution") or model.get("default_resolution")
    if by_res and resolution in by_res:
        return float(by_res[resolution])
    return float(price.get("usd", 0))


def pick_duration(model: dict, seconds: float | None) -> int:
    """Snap a requested length to what the model supports."""
    if model.get("duration_range"):
        low, high = model["duration_range"]
        return int(min(high, max(low, round(seconds or low))))
    allowed = model.get("durations")
    if not allowed:
        return max(1, round(seconds or 5))
    if seconds is None:
        return int(allowed[0])
    return int(min(allowed, key=lambda d: (abs(d - seconds), -d)))


def estimate(model: dict, params: dict) -> float:
    """Best-effort USD estimate for one call. Errs on the high side."""
    price = model.get("price", {})
    unit = price.get("unit", "image")
    rate = unit_price(model, params)
    count = int(params.get("num_images") or 1)
    if unit == "image":
        return rate * count
    if unit == "megapixel":
        mp = _MEGAPIXELS.get(params.get("aspect_ratio") or "1:1", 1.05)
        return rate * math.ceil(mp) * count
    if unit == "second":
        seconds = params.get("duration")
        if seconds is None and params.get("source_seconds"):
            seconds = params["source_seconds"]
        if model.get("max_seconds") and not model.get("durations"):
            return rate * float(seconds or 5)  # output length follows the input audio/video
        return rate * pick_duration(model, float(seconds) if seconds else None)
    if unit == "video":
        return rate
    if unit == "1k_chars":
        return rate * max(100, len(params.get("text") or "")) / 1000
    return rate


def build_input(model: dict, params: dict) -> dict:
    """Translate generic params into the provider's request body."""
    body = dict(model.get("fixed", {}))
    for generic, spec in model.get("inputs", {}).items():
        value = params.get(generic)
        if value is None or value == "":
            continue
        if isinstance(spec, str):
            body[spec] = value
            continue
        field = spec["field"]
        if "map" in spec:
            if value not in spec["map"]:
                continue
            value = spec["map"][value]
        if spec.get("type") == "str":
            value = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        elif spec.get("type") == "int":
            value = int(value)
        if spec.get("suffix"):
            value = f"{value}{spec['suffix']}"
        body[field] = value
    return body


def summary(model: dict) -> dict:
    price = model.get("price", {})
    return {
        "id": model["id"],
        "name": model["name"],
        "provider": model["provider"],
        "kind": model["kind"],
        "kinds": kinds_of(model),
        "tier": model["tier"],
        "price": price,
        "price_label": price_label(model),
        "durations": model.get("durations"),
        "resolutions": model.get("resolutions"),
        "default_resolution": model.get("default_resolution"),
        "voices": model.get("voices"),
        "max_seconds": model.get("max_seconds"),
        "notes": model.get("notes", ""),
        "available": available(model),
    }


def price_label(model: dict) -> str:
    price = model.get("price", {})
    usd = float(price.get("usd", 0))
    if usd == 0 and not price.get("by_resolution"):
        return "free"
    unit = {"image": "/image", "megapixel": "/MP", "second": "/sec", "video": "/video", "1k_chars": "/1k chars"}
    label = f"~${usd:.3f}{unit.get(price.get('unit'), '')}"
    if price.get("by_resolution"):
        low = min(price["by_resolution"].values())
        label = f"~${low:.3f}+{unit.get(price.get('unit'), '')}"
    return label
