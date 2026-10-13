"""Providers that need no API key: Pollinations (free images) and Mock (offline).

Mock output is clearly labelled placeholder media so every workflow, the UI
and the tests can run end-to-end before any paid key is added.
"""
from __future__ import annotations

import hashlib
import random
import textwrap
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

from .. import media
from .base import Provider, ProviderError, RejectedError

POLLINATIONS_SIZES = {"1:1": (1024, 1024), "16:9": (1280, 720), "9:16": (720, 1280), "4:3": (1024, 768), "3:4": (768, 1024)}


class PollinationsProvider(Provider):
    name = "pollinations"
    synchronous = True

    def prepare_media(self, path):
        raise RejectedError("Pollinations takes text prompts only.")

    def submit(self, model, body, workdir):
        w, h = POLLINATIONS_SIZES.get(body.get("aspect_ratio") or "1:1", (1024, 1024))
        seed = body.get("seed") or random.randint(1, 2**31 - 1)
        url = (f"https://image.pollinations.ai/prompt/{quote(body['prompt'])}"
               f"?width={w}&height={h}&seed={seed}&model={model['endpoint']}&nologo=true&private=true")
        last = None
        for attempt in range(3):  # free endpoint, retrying costs nothing
            try:
                r = requests.get(url, timeout=180)
                if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
                    ext = ".png" if "png" in r.headers["Content-Type"] else ".jpg"
                    path = workdir / f"pollinations-{seed}{ext}"
                    path.write_bytes(r.content)
                    return {"request_id": f"pollinations-{seed}", "files": [str(path)]}
                last = f"HTTP {r.status_code}"
            except requests.RequestException as exc:
                last = type(exc).__name__
            time.sleep(3 * (attempt + 1))
        raise ProviderError(f"Pollinations is unavailable right now ({last}). Try again or add a FAL_KEY.")


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def placeholder(prompt: str, size: tuple[int, int], dest: Path, label: str = "MOCK", base: Path | None = None) -> Path:
    """A deterministic card: gradient from the prompt hash, prompt text on top."""
    w, h = size
    digest = hashlib.sha256(prompt.encode()).digest()
    if base:
        img = Image.open(base).convert("RGB")
        img = img.resize((w, h))
    else:
        top, bottom = digest[:3], digest[3:6]
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    draw = ImageDraw.Draw(img)
    size_px = max(16, w // 24)
    font = _font(size_px)
    small = _font(max(14, w // 34))
    # On top of a real picture, only add the label so the picture stays readable.
    lines = [] if base else textwrap.wrap(prompt, width=max(10, int(w * 0.85 / (size_px * 0.6))))[:8]
    y = h // 2 - len(lines) * int(size_px * 1.3) // 2
    for line in lines:
        draw.text((w // 2, y), line, font=font, fill="white", anchor="ma", stroke_width=3, stroke_fill="black")
        y += int(size_px * 1.3)
    draw.rounded_rectangle([16, 16, 16 + w // 3, 16 + w // 14], radius=10, fill=(0, 0, 0))
    draw.text((28, 22), label, font=small, fill=(255, 220, 0))
    img.save(dest)
    return dest


class MockProvider(Provider):
    name = "mock"
    synchronous = True

    def prepare_media(self, path):
        return str(path)

    def submit(self, model, body, workdir):
        kind = model["endpoint"]
        stem = f"mock-{hashlib.sha1(repr(sorted(body.items())).encode()).hexdigest()[:8]}-{int(time.time() * 1000) % 100000}"
        aspect = body.get("aspect_ratio") or "9:16"
        size = media.size_for(aspect)
        prompt = body.get("prompt") or body.get("text") or "placeholder"
        files: list[str] = []
        if kind in ("image", "image_edit"):
            ref = (body.get("images") or [None])[0]
            for i in range(int(body.get("num_images") or 1)):
                path = placeholder(prompt, size, workdir / f"{stem}-{i}.png", "MOCK IMAGE", base=Path(ref) if ref else None)
                files.append(str(path))
        elif kind in ("video", "image_to_video"):
            seconds = float(body.get("duration") or 2)
            image = body.get("image")
            if image:
                with Image.open(image) as im:
                    size = (max(2, im.width // 2 * 2), max(2, im.height // 2 * 2))
            still = placeholder(prompt, size, workdir / f"{stem}.png", "MOCK VIDEO", base=Path(image) if image else None)
            files.append(str(media.still_to_clip(still, workdir / f"{stem}.mp4", seconds, size)))
        elif kind == "swap":
            source = Path(body["video"])
            info = media.probe(source)
            ref = Path(body["image"])
            card = placeholder("character swap preview", (max(2, info["width"] // 4 // 2 * 2), max(2, info["height"] // 4 // 2 * 2)),
                               workdir / f"{stem}-ref.png", "MOCK SWAP", base=ref)
            out = workdir / f"{stem}.mp4"
            media.run(["-i", source, "-i", card, "-filter_complex", "[0:v][1:v]overlay=W-w-16:16,format=yuv420p",
                       "-an", "-c:v", "libx264", "-preset", "veryfast", out])
            files.append(str(out))
        elif kind == "talking_head":
            audio = Path(body["audio_file"])
            seconds = media.probe(audio)["duration"]
            with Image.open(body["image"]) as im:
                size = (max(2, min(720, im.width) // 2 * 2), max(2, int(min(720, im.width) * im.height / im.width) // 2 * 2))
            card = placeholder("talking", size, workdir / f"{stem}.png", "MOCK PRESENTER", base=Path(body["image"]))
            silent = media.still_to_clip(card, workdir / f"{stem}-silent.mp4", seconds, size, "zoom_in", max_hold=999)
            out = workdir / f"{stem}.mp4"
            media.run(["-i", silent, "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", out])
            files.append(str(out))
        elif kind == "lipsync":
            audio = Path(body["audio_file"])
            seconds = media.probe(audio)["duration"]
            out = workdir / f"{stem}.mp4"
            media.run(["-stream_loop", "-1", "-i", body["video"], "-i", audio, "-map", "0:v", "-map", "1:a",
                       "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", out])
            files.append(str(out))
        elif kind == "tts":
            words = max(1, len(prompt.split()))
            seconds = round(words / 2.6 + 0.4, 2)
            files.append(str(media.silence(workdir / f"{stem}.wav", seconds)))
        else:
            raise RejectedError(f"Mock cannot produce '{kind}'.")
        return {"request_id": stem, "files": files}
