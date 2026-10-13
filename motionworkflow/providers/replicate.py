"""Replicate predictions API.

Get a token at https://replicate.com/account/api-tokens and set
REPLICATE_API_TOKEN in .env.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .. import config
from .base import AmbiguousError, Provider, ProviderError, StillRunning, http_error

API = "https://api.replicate.com/v1/"


class ReplicateProvider(Provider):
    name = "replicate"

    def _headers(self) -> dict:
        return {"Authorization": "Bearer " + config.credential("REPLICATE_API_TOKEN")}

    def prepare_media(self, path: Path) -> str:
        """Upload through Replicate's Files API; the URL works for its models."""
        with Path(path).open("rb") as f:
            r = requests.post(API + "files", headers=self._headers(), files={"content": (Path(path).name, f)}, timeout=300)
        if not r.ok:
            raise http_error("replicate", r)
        return r.json()["urls"]["get"]

    def submit(self, model: dict, body: dict, workdir: Path) -> dict:
        if model.get("version"):
            url, payload = API + "predictions", {"version": model["version"], "input": body}
        else:
            url, payload = API + f"models/{model['endpoint']}/predictions", {"input": body}
        try:
            r = requests.post(url, headers=self._headers(), json=payload, timeout=120)
        except requests.Timeout as exc:
            raise AmbiguousError("Replicate did not answer in time; a prediction may exist. "
                                 "Check https://replicate.com/predictions before retrying.") from exc
        except requests.ConnectionError as exc:
            raise ProviderError(f"Could not reach Replicate: {exc}") from exc
        if not r.ok:
            raise http_error("replicate", r)
        data = r.json()
        return {"request_id": data["id"], "get_url": data["urls"]["get"]}

    def wait(self, model: dict, handle: dict, status, timeout: float = 1800) -> dict:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            status("")  # a heartbeat: lets the job stop between polls
            try:
                r = requests.get(handle["get_url"], headers=self._headers(), timeout=30)
                r.raise_for_status()
                data = r.json()
            except requests.RequestException:
                time.sleep(5)
                continue
            current = data.get("status")
            if current == "succeeded":
                return {"output": data.get("output")}
            if current in ("failed", "canceled"):
                raise ProviderError(f"Replicate {current}: {data.get('error') or 'no detail'}")
            if current != last:
                status(f"{model['name']}: {current}")
                last = current
            time.sleep(3)
        raise StillRunning(f"Replicate prediction {handle['request_id']} is still running. Resume the job later.")

    def collect(self, model, handle, result, dest_stem):
        headers = self._headers()
        output = result.get("output")
        urls = [output] if isinstance(output, str) else [u for u in (output or []) if isinstance(u, str)]
        if isinstance(output, dict):
            urls = [v for v in output.values() if isinstance(v, str) and v.startswith("https://")]
        if not urls:
            raise ProviderError("Replicate finished but returned no output URL.")
        from .base import download

        return [download(u, dest_stem.with_name(f"{dest_stem.name}-{i}"), headers) for i, u in enumerate(urls)]
