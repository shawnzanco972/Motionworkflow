"""Turn a local file into a public HTTPS URL for providers that only take URLs.

Adapted from the Genjutsu workflow's media_host (MIT, Sirio Berati).
WARNING: these hosts are public. Anyone with the link can download the file;
catbox links are permanent. Do not upload anything private.
"""
from __future__ import annotations

import html
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config

SUPPORTED = ("tmpfiles", "catbox")


def _upload_once(path: Path, host: str) -> str:
    with path.open("rb") as f:
        if host == "tmpfiles":
            if path.stat().st_size > 100_000_000:
                raise ValueError("tmpfiles limit is 100 MB")
            r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": (path.name, f)}, timeout=180)
            r.raise_for_status()
            page_url = r.json()["data"]["url"]
            if urlparse(page_url).hostname != "tmpfiles.org":
                raise ValueError("unexpected tmpfiles response")
            # tmpfiles returns a page; the direct link lives under /dl/.
            page = requests.get(page_url, timeout=60)
            page.raise_for_status()
            found = re.findall(r"https://tmpfiles\.org/dl/[^\"'<> ]+", page.text)
            if found:
                url = html.unescape(found[0])
            else:
                url = re.sub(r"^https?://tmpfiles\.org/", "https://tmpfiles.org/dl/", page_url, count=1)
        elif host == "catbox":
            data = {"reqtype": "fileupload"}
            if config.setting("CATBOX_USERHASH"):
                data["userhash"] = config.setting("CATBOX_USERHASH")
            r = requests.post("https://catbox.moe/user/api.php", data=data,
                              files={"fileToUpload": (path.name, f)}, timeout=180)
            r.raise_for_status()
            url = r.text.strip()
        else:
            raise ValueError(f"MEDIA_HOST must be one of {SUPPORTED}")
    if not url.startswith("https://"):
        raise ValueError("host did not return an HTTPS URL")
    _check_direct(url)
    return html.unescape(url)


def _check_direct(url: str) -> None:
    with requests.get(url, stream=True, timeout=60) as check:
        check.raise_for_status()
        if "text/html" in check.headers.get("Content-Type", ""):
            raise ValueError("URL returned a web page, not the file")
        first = next(check.iter_content(256), b"")
        if not first or re.match(rb"\s*<(!doctype|html)", first, re.I):
            raise ValueError("empty or HTML response")


def upload(path: Path) -> str:
    """Retries hosting only. A failed upload never triggers a paid call."""
    path = Path(path)
    primary = config.setting("MEDIA_HOST")
    fallbacks = [h.strip() for h in config.setting("MEDIA_HOST_FALLBACKS").split(",") if h.strip()]
    hosts = list(dict.fromkeys([primary, *fallbacks]))
    errors = []
    for host in hosts:
        if host not in SUPPORTED:
            errors.append(f"{host}: unsupported")
            continue
        for attempt in range(2):
            try:
                return _upload_once(path, host)
            except (requests.RequestException, ValueError, KeyError, StopIteration) as exc:
                errors.append(f"{host}: {type(exc).__name__}")
                if attempt == 0:
                    time.sleep(1)
    raise RuntimeError("All media hosts failed (" + ", ".join(errors) + "). Nothing was submitted.")
