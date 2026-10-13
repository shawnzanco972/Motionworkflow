"""Persistent jobs. Each job is a folder in runs/ with a job.json.

Steps record provider request IDs the moment a request is accepted, so a
crash or restart resumes *collection* and never pays for the same request
twice.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

_ID = re.compile(r"^[0-9a-f]{12}$")
_locks: dict[str, threading.RLock] = {}
_live: dict[str, "Job"] = {}  # one in-memory instance per job in this process
listeners: list = []  # callables(job, message), e.g. the CLI's progress printer
_locks_guard = threading.Lock()

# States a job can be in.
QUEUED, RUNNING, WAITING, DONE, ERROR = "queued", "running", "awaiting_approval", "done", "error"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lock(job_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(job_id, threading.RLock())


class Job:
    def __init__(self, data: dict):
        self.data = data

    # -- identity and storage -------------------------------------------
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def folder(self) -> Path:
        return config.RUNS / self.id

    @property
    def params(self) -> dict:
        return self.data["params"]

    def path(self, name: str) -> Path:
        return self.folder / name

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.folder.resolve()))

    def save(self) -> None:
        with _lock(self.id):
            self.data["updated"] = now()
            tmp = self.folder / "job.json.tmp"
            tmp.write_text(json.dumps(self.data, indent=2))
            tmp.replace(self.folder / "job.json")

    # -- state ------------------------------------------------------------
    def status(self, message: str, state: str | None = None) -> None:
        with _lock(self.id):
            self.data["status"] = message
            if state:
                self.data["state"] = state
            self.data.setdefault("log", []).append(f"{now()} {message}")
            self.data["log"] = self.data["log"][-200:]
            self.save()
        for listener in listeners:
            listener(self, message)

    def step(self, key: str) -> dict:
        with _lock(self.id):
            return self.data.setdefault("steps", {}).setdefault(key, {"state": "pending"})

    def update_step(self, key: str, **fields) -> dict:
        with _lock(self.id):
            step = self.step(key)
            step.update(fields)
            self.save()
            return step

    # Approvals live in their own file so the CLI and the web app can both
    # approve a job without overwriting each other's job.json.
    def approvals(self) -> dict:
        path = self.folder / "approvals.json"
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    def approved(self, stage: str) -> bool:
        return stage in self.approvals()

    def approve(self, stage: str, note: str = "") -> None:
        with _lock(self.id):
            data = self.approvals()
            data[stage] = {"at": now(), "note": note}
            (self.folder / "approvals.json").write_text(json.dumps(data, indent=2))
            self.data.pop("awaiting", None)
            self.data["state"] = QUEUED
            self.data["status"] = f"Approved: {stage}"
            self.save()

    def clear_approvals(self) -> None:
        (self.folder / "approvals.json").unlink(missing_ok=True)

    def wait_for(self, stage: str, message: str, **extra) -> None:
        """Pause the workflow until the user approves `stage`."""
        with _lock(self.id):
            self.data["awaiting"] = {"stage": stage, "message": message, **extra}
        self.status(message, WAITING)

    def add_output(self, path: Path, label: str, kind: str, final: bool = False) -> None:
        with _lock(self.id):
            rel = self.rel(path)
            outputs = self.data.setdefault("outputs", [])
            if not any(o["path"] == rel for o in outputs):
                outputs.append({"path": rel, "label": label, "kind": kind, "final": final})
            self.save()

    def public(self) -> dict:
        data = {k: v for k, v in self.data.items() if k != "log"}
        data["approvals"] = self.approvals()
        data["log"] = self.data.get("log", [])[-30:]
        data["outputs"] = [dict(o, url=f"/files/{self.id}/{o['path']}") for o in self.data.get("outputs", [])]
        return data


def create(workflow: str, params: dict, files: dict[str, list[Path]] | None = None) -> Job:
    job_id = uuid.uuid4().hex[:12]
    folder = config.RUNS / job_id
    (folder / "inputs").mkdir(parents=True)
    stored: dict[str, list[str]] = {}
    for field, paths in (files or {}).items():
        for i, src in enumerate(paths):
            src = Path(src)
            dest = folder / "inputs" / f"{field}-{i}{src.suffix.lower()}"
            shutil.copy2(src, dest)
            stored.setdefault(field, []).append(str(dest.relative_to(folder)))
    job = Job({
        "id": job_id,
        "workflow": workflow,
        "state": QUEUED,
        "status": "Queued",
        "created": now(),
        "params": params,
        "inputs": stored,
        "steps": {},
        "outputs": [],
        "estimate": None,
    })
    job.save()
    _live[job_id] = job
    return job


def valid_id(job_id: str) -> bool:
    return bool(_ID.match(job_id or ""))


def load(job_id: str) -> Job:
    if not valid_id(job_id):
        raise KeyError(job_id)
    if job_id in _live:
        return _live[job_id]
    path = config.RUNS / job_id / "job.json"
    if not path.exists():
        raise KeyError(job_id)
    job = Job(json.loads(path.read_text()))
    _live[job_id] = job
    return job


def all_jobs(limit: int = 100) -> list[Job]:
    if not config.RUNS.exists():
        return []
    found = []
    for path in config.RUNS.glob("*/job.json"):
        try:
            found.append(load(path.parent.name))
        except (KeyError, ValueError, OSError):
            continue
    found.sort(key=lambda j: j.data.get("created", ""), reverse=True)
    return found[:limit]
