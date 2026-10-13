"""Your reusable assets: avatars (a photo or a short video of a presenter) and voices.

Uploads are normalised once (sizes, formats, a clean voice reference clip) and
then reused by any job. Every item records the owner's consent: only your own
face and voice, or someone who has said yes.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from . import config, media
from .providers.base import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT

KINDS = ("avatars", "voices")
MAX_AVATAR_VIDEO = 60.0
MAX_VOICE = 60.0
REF_SECONDS = 12.0  # cloning models work best with a 5-15 s reference
MIN_VOICE = 3.0
_ID = re.compile(r"^[0-9a-f]{10}$")


class LibraryError(ValueError):
    pass


def root() -> Path:
    path = Path(config.setting("MW_LIBRARY_DIR", str(config.ROOT / "library")))
    for kind in KINDS:
        (path / kind).mkdir(parents=True, exist_ok=True)
    return path


def _folder(kind: str, item_id: str) -> Path:
    if kind not in KINDS or not _ID.match(item_id or ""):
        raise LibraryError("Unknown item.")
    folder = root() / kind / item_id
    if not (folder / "item.json").exists():
        raise LibraryError("Unknown item.")
    return folder


def _new(kind: str, name: str, consent: bool) -> tuple[str, Path]:
    if not consent:
        raise LibraryError("Confirm this is you, or that the person agreed to be used this way.")
    name = (name or "").strip()[:60]
    if not name:
        raise LibraryError("Give it a name.")
    item_id = uuid.uuid4().hex[:10]
    folder = root() / kind / item_id
    folder.mkdir(parents=True)
    return item_id, folder


def _save(folder: Path, data: dict) -> dict:
    (folder / "item.json").write_text(json.dumps(data, indent=2))
    return data


def add_avatar(src: Path, name: str, consent: bool) -> dict:
    """A clear, front-facing photo, or a 5-60 s video looking at the camera."""
    src = Path(src)
    suffix = src.suffix.lower()
    if suffix not in IMAGE_EXT | VIDEO_EXT:
        raise LibraryError("Use a photo (JPG, PNG, WebP) or a short video (MP4, MOV, WebM).")
    item_id, folder = _new("avatars", name, consent)
    try:
        if suffix in IMAGE_EXT:
            try:
                Image.open(src).verify()
            except Exception:  # noqa: BLE001 - any decoder error means "not an image"
                raise LibraryError("That file isn't a readable image. Export it again as JPG or PNG.") from None
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                if min(im.size) < 256:
                    raise LibraryError("The photo is too small; use at least 512 px on the short side.")
                im.thumbnail((1536, 1536))
                im.save(folder / "avatar.jpg", quality=92)
                thumb = im.copy()
                thumb.thumbnail((480, 480))
                thumb.save(folder / "thumb.jpg", quality=85)
                width, height = im.size
            data = {"kind": "image", "file": "avatar.jpg", "duration": None}
        else:
            try:
                info = media.probe(src)
            except media.MediaError:
                raise LibraryError("That video can't be read. Export it again as MP4.") from None
            if not info["has_video"]:
                raise LibraryError("That file has no video.")
            if info["duration"] < 3:
                raise LibraryError("Use at least 3 seconds of video (10-20 s looking at the camera works best).")
            seconds = min(MAX_AVATAR_VIDEO, info["duration"])
            scale = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
            media.run(["-i", src, "-t", f"{seconds:.3f}", "-vf", f"{scale},fps=25,format=yuv420p", "-an",
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", folder / "avatar.mp4"])
            media.thumbnail(folder / "avatar.mp4", folder / "thumb.jpg", at=min(1.0, seconds / 2))
            out = media.probe(folder / "avatar.mp4")
            width, height = out["width"], out["height"]
            data = {"kind": "video", "file": "avatar.mp4", "duration": round(out["duration"], 2)}
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _save(folder, {
        "id": item_id, "name": name.strip()[:60], "type": "avatar", **data, "thumb": "thumb.jpg",
        "width": width, "height": height, "consent": True,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def add_voice(src: Path, name: str, consent: bool, transcript: str = "") -> dict:
    """A clean recording of one speaker: 10-30 s, no music, little room echo."""
    src = Path(src)
    if src.suffix.lower() not in AUDIO_EXT | VIDEO_EXT | {".webm"}:
        raise LibraryError("Use an audio file (MP3, WAV, M4A) or a video with your voice.")
    item_id, folder = _new("voices", name, consent)
    try:
        try:
            info = media.probe(src)
        except media.MediaError:
            raise LibraryError("That recording can't be read. Try MP3, WAV or M4A.") from None
        if not info["has_audio"]:
            raise LibraryError("That file has no sound.")
        # Mono 24 kHz, leading/trailing silence removed, level evened out.
        media.run(["-i", src, "-vn", "-ac", "1", "-ar", "24000", "-t", f"{MAX_VOICE:.0f}",
                   "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
                          "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.3,areverse,"
                          "loudnorm=I=-18:TP=-2",
                   folder / "voice.wav"])
        seconds = media.probe(folder / "voice.wav")["duration"]
        if seconds < MIN_VOICE:
            raise LibraryError("No clear speech found. Record at least 10 seconds of you talking, close to the mic."
                               if seconds < 0.5 else f"Only {seconds:.1f} s of speech found; record at least 10 seconds.")
        media.run(["-i", folder / "voice.wav", "-t", f"{min(REF_SECONDS, seconds):.2f}", folder / "reference.wav"])
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return _save(folder, {
        "id": item_id, "name": name.strip()[:60], "type": "voice", "file": "voice.wav", "reference": "reference.wav",
        "duration": round(seconds, 2), "transcript": transcript.strip()[:2000], "consent": True,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def items(kind: str) -> list[dict]:
    if kind not in KINDS:
        raise LibraryError("Unknown kind.")
    found = []
    for path in (root() / kind).glob("*/item.json"):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        base = f"/library/{kind}/{data['id']}/"
        data["url"] = base + data["file"]
        if data.get("thumb"):
            data["thumb_url"] = base + data["thumb"]
        found.append(data)
    return sorted(found, key=lambda d: d.get("created", ""), reverse=True)


def get(kind: str, item_id: str) -> dict:
    folder = _folder(kind, item_id)
    data = json.loads((folder / "item.json").read_text())
    data["path"] = str(folder / data["file"])
    if data.get("reference"):
        data["reference_path"] = str(folder / data["reference"])
    return data


def file_path(kind: str, item_id: str, name: str) -> Path:
    folder = _folder(kind, item_id)
    target = (folder / name).resolve()
    if not target.is_relative_to(folder.resolve()) or not target.is_file() or target.name == "item.json":
        raise LibraryError("Not found.")
    return target


def rename(kind: str, item_id: str, name: str) -> dict:
    folder = _folder(kind, item_id)
    data = json.loads((folder / "item.json").read_text())
    data["name"] = (name or data["name"]).strip()[:60]
    return _save(folder, data)


def delete(kind: str, item_id: str) -> None:
    shutil.rmtree(_folder(kind, item_id))
