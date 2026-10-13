"""fal.ai queue API: one key, hundreds of image/video/audio models.

Get a key at https://fal.ai/dashboard/keys and set FAL_KEY in .env.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .. import config, hosting
from .base import AmbiguousError, Provider, ProviderError, StillRunning, data_uri, http_error

QUEUE = "https://queue.fal.run/"
INLINE_LIMIT = 8 * 1024 * 1024  # larger files go through a media host


class FalProvider(Provider):
    name = "fal"

    def _headers(self) -> dict:
        return {"Authorization": "Key " + config.credential("FAL_KEY")}

    def prepare_media(self, path: Path) -> str:
        if Path(path).stat().st_size <= INLINE_LIMIT:
            return data_uri(path)
        return hosting.upload(path)

    def submit(self, model: dict, body: dict, workdir: Path) -> dict:
        headers = self._headers()
        try:
            r = requests.post(QUEUE + model["endpoint"], headers=headers, json=body, timeout=120)
        except requests.Timeout as exc:
            raise AmbiguousError("fal did not answer in time; the request may still have been queued. "
                                 "Check https://fal.ai/dashboard/requests before retrying.") from exc
        except requests.ConnectionError as exc:
            raise ProviderError(f"Could not reach fal: {exc}") from exc
        if not r.ok:
            raise http_error("fal", r)
        data = r.json()
        if not data.get("request_id"):
            raise AmbiguousError("fal accepted the call but returned no request_id: " + r.text[:300])
        return {
            "request_id": data["request_id"],
            "status_url": data.get("status_url") or f"{QUEUE}{model['endpoint']}/requests/{data['request_id']}/status",
            "response_url": data.get("response_url") or f"{QUEUE}{model['endpoint']}/requests/{data['request_id']}",
        }

    def wait(self, model: dict, handle: dict, status, timeout: float = 1800) -> dict:
        headers = self._headers()
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                r = requests.get(handle["status_url"], headers=headers, timeout=30)
                r.raise_for_status()
                state = r.json()
            except requests.RequestException:
                time.sleep(5)  # polling is free; keep going
                continue
            current = state.get("status", "")
            if current == "COMPLETED":
                if state.get("error"):
                    raise ProviderError(f"fal failed: {state['error']}")
                result = requests.get(handle["response_url"], headers=headers, timeout=60)
                if not result.ok:
                    raise ProviderError(f"fal failed ({result.status_code}): {result.text[:500]}")
                return result.json()
            if current in ("FAILED", "ERROR", "CANCELLED"):
                raise ProviderError(f"fal {current.lower()}: {state.get('error') or state}")
            label = "queued" if current == "IN_QUEUE" else "generating"
            if state.get("queue_position") is not None:
                label += f" (position {state['queue_position']})"
            if label != last:
                status(f"{model['name']}: {label}")
                last = label
            time.sleep(3)
        raise StillRunning(f"fal request {handle['request_id']} is still running. Resume the job later.")
