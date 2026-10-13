"""Bridge to the Genjutsu workflow's input preparation (vendor/genjutsu).

Genjutsu prepares a clip for Seedance so the new character takes over the
performance cleanly:
- depth:      Demucs vocal isolation, +3-semitone vocals embedded, colored
              depth (Depth Anything), SAM 3 raw masks, depth subject composited
              over the original background.
- face_mesh:  local MediaPipe face mesh drawn on the original (no depth/SAM).
- depth_mesh: both.
Its rule carries over unchanged: the whole prepared clip is reviewed and
approved before any generation, and approval is withdrawn if it changes.

Install with `bash scripts/install-skills.sh --with-genjutsu-env`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config

MODES = {"genjutsu-depth": "depth", "genjutsu-face-mesh": "face_mesh", "genjutsu-depth-mesh": "depth_mesh"}
# Replicate Demucs + depth + SAM 3 for a clip of up to 30 s. An estimate: check your Replicate bill.
PREP_ESTIMATE = {"depth": 0.30, "face_mesh": 0.03, "depth_mesh": 0.30}
MESH_PROMPT = (" Remove all face mesh lines and any depth colors from the output; use them only for expression and "
               "lip motion guidance. Replace the entire original identity including hair. Preserve the exact "
               "embedded dialogue and timing.")


class GenjutsuError(RuntimeError):
    def __init__(self, message: str, started: bool = True):
        super().__init__(message)
        self.started = started  # False: no paid call can have happened


def root() -> Path:
    return Path(config.setting("MW_GENJUTSU_DIR", str(config.ROOT / "vendor" / "genjutsu")))


def python() -> Path:
    return root() / ".venv" / "bin" / "python"


def status() -> dict:
    base = root()
    return {
        "installed": (base / "workflow.py").exists(),
        "environment": python().exists(),
        "face_mesh": (base / ".venv-face" / "bin" / "python").exists(),
        "rubberband": shutil.which("rubberband") is not None,
        "replicate_key": config.has_key("REPLICATE_API_TOKEN"),
    }


def check(mode: str) -> None:
    s = status()
    if not s["installed"]:
        raise GenjutsuError("Genjutsu is not installed. Run: bash scripts/install-skills.sh --with-genjutsu-env", started=False)
    if not s["environment"]:
        raise GenjutsuError("Genjutsu's environment is missing. Run: bash scripts/install-skills.sh --with-genjutsu-env "
                            "(needs Python 3.12+ and rubberband).", started=False)
    if not s["rubberband"]:
        raise GenjutsuError("Genjutsu needs Rubber Band: macOS brew install rubberband · Ubuntu sudo apt install rubberband-cli", started=False)
    if not s["replicate_key"]:
        raise GenjutsuError("Genjutsu prep uses Replicate (vocals, depth, SAM 3): set REPLICATE_API_TOKEN.", started=False)
    if mode in ("face_mesh", "depth_mesh") and not s["face_mesh"]:
        raise GenjutsuError("Face mesh needs: cd vendor/genjutsu && bash setup-face-mesh.sh (Python 3.12).", started=False)


def run_folder(job_id: str) -> Path:
    return root() / "runs" / job_id


def finished(job_id: str) -> bool:
    return (run_folder(job_id) / "seedance-input.mp4").exists()


def prepare(video: Path, mode: str, subject: str, on_job, on_status) -> Path:
    """Run `workflow.py prepare`. Calls on_job(id) as soon as Genjutsu names its job."""
    check(mode)
    env = dict(os.environ)
    for key in ("REPLICATE_API_TOKEN", "HF_TOKEN"):
        if config.setting(key):
            env[key] = config.setting(key)
    cmd = [str(python()), "workflow.py", "prepare", str(Path(video).resolve()), "--mode", mode,
           "--subject", subject or "person", "--provider", "replicate"]
    job_id, tail = None, []
    with subprocess.Popen(cmd, cwd=root(), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            tail = (tail + [line])[-12:]
            match = re.match(r"JOB:\s*([0-9a-f]{32})", line)
            if match:
                job_id = match[1]
                on_job(job_id)
            else:
                on_status("Genjutsu: " + line[:160])
        code = proc.wait()
    detail = " | ".join(tail[-4:]) or f"exit {code}"
    if not job_id:
        raise GenjutsuError("Genjutsu did not start: " + detail, started=False)
    if code != 0 or not finished(job_id):
        raise GenjutsuError("Genjutsu prep failed: " + detail)
    return run_folder(job_id)


def artifacts(folder: Path) -> dict[str, Path]:
    """The files a reviewer must see, and the input Seedance gets."""
    names = {
        "input": "seedance-input.mp4",
        "mask": "mask.mp4",
        "composite": "composite-silent.mp4",
        "depth": "depth.mp4",
    }
    return {k: folder / v for k, v in names.items() if (folder / v).exists()}
