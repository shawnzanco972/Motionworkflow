"""Check what people send before a project exists.

Everything here runs before any job is created or any money is reserved, so a
typo or an unreadable file is a clear message on the form, not a failed
project in the library.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import media
from .providers.base import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT


class InputError(ValueError):
    """A problem the person can fix in the form."""


# workflow -> param -> (label, default, low, high, integer)
NUMBERS = {
    "image": {"num_images": ("Number of images", 1, 1, 8, True), "seed": ("Seed", None, 0, 2**31 - 1, True)},
    "video": {"duration": ("Length", 5, 1, 30, False), "seed": ("Seed", None, 0, 2**31 - 1, True)},
    "short": {"shots": ("Shots", 5, 1, 12, True), "shot_seconds": ("Seconds per shot", 5, 2, 10, False),
              "music_volume": ("Music volume", 0.18, 0, 1, False)},
    "presenter": {"seconds": ("Length", 30, 10, 180, False), "music_volume": ("Music volume", 0.12, 0, 1, False)},
    "swap": {"source_seconds": ("Clip length", None, 0, 600, False)},
    "voice": {},
}

# Text fields and their limits (characters).
TEXT_LIMITS = {"prompt": 4000, "idea": 1000, "topic": 1000, "script": 20000, "text": 20000, "style": 300,
               "tone": 100, "audience": 300, "subject": 100, "negative_prompt": 2000}


def coerce(workflow: str, params: dict) -> dict:
    """Turn form values into clean numbers (clamped to their range) and trimmed text."""
    for key, (label, default, low, high, integer) in NUMBERS.get(workflow, {}).items():
        raw = params.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if default is None:
                params.pop(key, None)
            else:
                params[key] = default
            continue
        if isinstance(raw, bool):
            raise InputError(f"{label} must be a number.")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise InputError(f"{label} must be a number (got “{str(raw)[:20]}”).") from None
        if math.isnan(value) or math.isinf(value):
            raise InputError(f"{label} must be a number.")
        value = max(low, min(high, value))
        params[key] = int(round(value)) if integer else round(value, 3)
    for key, limit in TEXT_LIMITS.items():
        value = params.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if len(value) > limit:
            raise InputError(f"{key.replace('_', ' ').capitalize()} is too long ({len(value):,} characters; the limit is {limit:,}).")
        params[key] = value
    return params


def has(params: dict, *keys: str) -> bool:
    return any(str(params.get(k) or "").strip() for k in keys)


def require(workflow: str, params: dict, counts: dict) -> None:
    """The minimum each workflow needs. Raises InputError with a plain message."""
    if workflow == "image" and not has(params, "prompt"):
        raise InputError("Write a prompt.")
    if workflow == "video" and not has(params, "prompt"):
        raise InputError("Write a prompt.")
    if workflow == "voice" and not has(params, "text"):
        raise InputError("Write the words to speak.")
    if workflow == "short" and not has(params, "idea", "script"):
        raise InputError("Describe the idea or paste a script.")
    if workflow == "presenter":
        if not has(params, "topic", "script"):
            raise InputError("Say what the video is about, or paste your script.")
        if not counts.get("avatar") and not params.get("avatar_id"):
            raise InputError("Choose an avatar: a clear photo of you, or 10-20 s of video looking at the camera.")
    if workflow == "swap":
        if not counts.get("video"):
            raise InputError("Add the source video.")
        if not counts.get("refs"):
            raise InputError("Add a character reference (an image, or a short identity video).")


def check_media(path: Path, field: str, display_name: str | None = None) -> None:
    """Make sure an uploaded file is what it claims to be, before anything uses it."""
    path = Path(path)
    name = display_name or path.name
    suffix = path.suffix.lower()
    if path.stat().st_size == 0:
        raise InputError(f"{name} is empty.")
    if suffix in IMAGE_EXT:
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                if min(im.size) < 64:
                    raise InputError(f"{name} is too small ({im.width}×{im.height}); use at least 256 px.")
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            if isinstance(exc, InputError):
                raise
            raise InputError(f"{name} isn't a readable image. Export it again as JPG or PNG.") from None
        return
    try:
        info = media.probe(path)
    except media.MediaError:
        raise InputError(f"{name} can't be read. Export it again as MP4 (video) or MP3/WAV (audio).") from None
    if suffix in VIDEO_EXT and field not in ("voice_sample", "original"):
        if not info["has_video"] or info["duration"] <= 0.1:
            raise InputError(f"{name} has no playable video.")
    if suffix in AUDIO_EXT or field in ("voice_sample", "music"):
        if not info["has_audio"]:
            raise InputError(f"{name} has no sound.")
