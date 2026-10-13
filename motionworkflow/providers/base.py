"""Provider interface.

A provider turns a request body into files. Paid providers split this into
`submit` (one billed request, returns a JSON-serialisable handle that is
saved immediately) and `wait` (polling, safe to repeat after a restart).
"""
from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path
from typing import Callable

import requests

StatusFn = Callable[[str], None]

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class ProviderError(RuntimeError):
    """The provider definitely did not accept or complete the request."""


class RejectedError(ProviderError):
    """The submit call was refused (bad input, auth, quota). Nothing was billed."""


class AmbiguousError(RuntimeError):
    """We could not tell whether a paid request was accepted. Never auto-retry."""


class StillRunning(RuntimeError):
    """Polling gave up while the provider is still working. Resume later."""


def media_kind(path_or_url: str, content_type: str = "") -> str:
    suffix = Path(re.sub(r"[?#].*$", "", path_or_url)).suffix.lower()
    if suffix in IMAGE_EXT or content_type.startswith("image/"):
        return "image"
    if suffix in VIDEO_EXT or content_type.startswith("video/"):
        return "video"
    if suffix in AUDIO_EXT or content_type.startswith("audio/"):
        return "audio"
    return "file"


def is_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://", "data:"))


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def find_urls(payload) -> list[str]:
    """Every media URL in a provider response, in order, without duplicates."""
    found: list[str] = []

    def walk(node, key=""):
        if isinstance(node, str):
            if node.startswith("https://") and (key in ("url", "", "output", "result", "video", "image", "audio", "audio_url")
                                                or media_kind(node) != "file"):
                found.append(node)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k in ("logs", "input", "urls", "metrics", "timings", "error"):
                    continue
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)

    walk(payload)
    return list(dict.fromkeys(found))


_EXT_FOR_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/ogg": ".ogg",
}


def download(url: str, dest_stem: Path, headers: dict | None = None) -> Path:
    """Save a URL next to `dest_stem`, picking the extension from the response."""
    if url.startswith("data:"):
        header, _, body = url.partition(",")
        mime = header[5:].split(";")[0]
        path = dest_stem.with_suffix(_EXT_FOR_TYPE.get(mime, ".bin"))
        path.write_bytes(base64.b64decode(body))
        return path
    last = None
    for attempt in range(3):  # downloads are free to retry
        try:
            with requests.get(url, stream=True, timeout=300, headers=headers or {}) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
                suffix = Path(re.sub(r"[?#].*$", "", url)).suffix.lower()
                if suffix not in IMAGE_EXT | VIDEO_EXT | AUDIO_EXT:
                    suffix = _EXT_FOR_TYPE.get(ctype, ".bin")
                path = dest_stem.with_suffix(suffix)
                with path.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                return path
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise ProviderError(f"Download failed: {last}")


class Provider:
    name = "base"
    #: True when `submit` already produces the files (no remote queue).
    synchronous = False

    def prepare_media(self, path: Path) -> str:
        """Make a local file reachable by the provider (data URI or upload)."""
        return data_uri(path)

    def submit(self, model: dict, body: dict, workdir: Path) -> dict:
        raise NotImplementedError

    def wait(self, model: dict, handle: dict, status: StatusFn, timeout: float = 1800) -> dict:
        """Block until the request finishes; return the raw result payload."""
        return handle.get("result", {})

    def collect(self, model: dict, handle: dict, result: dict, dest_stem: Path) -> list[Path]:
        """Download outputs. Synchronous providers list local files in the handle."""
        if handle.get("files"):
            return [Path(p) for p in handle["files"]]
        urls = find_urls(result)
        if not urls:
            raise ProviderError("Provider finished but returned no media URL.")
        return [download(u, dest_stem.with_name(f"{dest_stem.name}-{i}")) for i, u in enumerate(urls)]


def http_error(provider: str, response: requests.Response) -> RejectedError:
    text = response.text[:600]
    if response.status_code in (401, 403):
        hint = " Check the API key in .env."
    elif response.status_code == 402:
        hint = " Your account may need credits."
    elif response.status_code == 422:
        hint = " The model rejected an input; check models.json field names for this model."
    else:
        hint = ""
    return RejectedError(f"{provider} rejected the request ({response.status_code}): {text}{hint}")
