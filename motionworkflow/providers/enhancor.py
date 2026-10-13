"""Enhancor's Seedance 2.5 API, as used by the Genjutsu workflow.

Request/response shapes follow the Genjutsu integration guide (MIT, Sirio
Berati): POST /queue returns {"requestId"}, POST /status returns
{"status", "result"}. A webhook URL is required by Enhancor; polling stays
authoritative. Get a key at https://app.enhancor.ai/api-dashboard.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .. import config, hosting
from .base import AmbiguousError, Provider, ProviderError, StillRunning, http_error


def base_url() -> str:
    return config.setting("ENHANCOR_BASE_URL").rstrip("/") + "/"


def webhook_url() -> str:
    url = config.setting("ENHANCOR_WEBHOOK_URL")
    if not url:
        from .. import webhook

        url = webhook.ensure() or ""
    if not url:
        raise ProviderError(
            "Enhancor requires a webhook URL. Install cloudflared (a callback-only tunnel then starts "
            "automatically), or set ENHANCOR_WEBHOOK_URL in .env."
        )
    return url


class EnhancorProvider(Provider):
    name = "enhancor"

    def _headers(self) -> dict:
        return {"x-api-key": config.credential("ENHANCOR_API_KEY")}

    def prepare_media(self, path: Path) -> str:
        return hosting.upload(path)

    def submit(self, model: dict, body: dict, workdir: Path) -> dict:
        body = dict(body)
        body.setdefault("webhook_url", webhook_url())
        (workdir / "enhancor-request.json").write_text(json.dumps(body, indent=2))
        try:
            r = requests.post(base_url() + "queue", headers=self._headers(), json=body, timeout=90)
        except requests.Timeout as exc:
            raise AmbiguousError("Enhancor did not answer in time; check your Enhancor dashboard before retrying.") from exc
        except requests.ConnectionError as exc:
            raise ProviderError(f"Could not reach Enhancor: {exc}") from exc
        if not r.ok:
            raise http_error("enhancor", r)
        data = r.json()
        ident = data.get("requestId")
        if not ident:
            raise AmbiguousError("Enhancor returned no requestId: " + r.text[:300])
        return {"request_id": ident}

    def wait(self, model: dict, handle: dict, status, timeout: float = 3600) -> dict:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            status("")  # a heartbeat: lets the job stop between polls
            try:
                r = requests.post(base_url() + "status", headers=self._headers(),
                                  json={"request_id": handle["request_id"]}, timeout=30)
                r.raise_for_status()
                data = r.json()
            except requests.RequestException:
                time.sleep(10)
                continue
            current = data.get("status")
            if current == "COMPLETED":
                url = data.get("result")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ProviderError("Seedance finished without a result URL.")
                return {"result": url}
            if current in ("FAILED", "CANCELED"):
                raise ProviderError("Seedance failed: " + str(data.get("error") or current))
            if current != last:
                status(f"Seedance: {str(current).lower()}")
                last = current
            time.sleep(10)
        raise StillRunning(f"Seedance request {handle['request_id']} is still pending. Resume the job later.")
