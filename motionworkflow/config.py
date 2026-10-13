"""Settings come from the environment first, then the project's .env file.

Nothing here ever prints or returns secret values; use `has_key()` to check
whether a credential is present.
"""
from __future__ import annotations

import math
import os
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
RUNS = Path(os.getenv("MW_RUNS_DIR", ROOT / "runs"))

# Credentials the app knows about, and which provider each one unlocks.
KEYS = {
    "FAL_KEY": "fal",
    "REPLICATE_API_TOKEN": "replicate",
    "ENHANCOR_API_KEY": "enhancor",
    "ANTHROPIC_API_KEY": "claude",
}

DEFAULTS = {
    "MW_DEFAULT_TIER": "budget",
    "MW_MAX_COST_PER_JOB": "5.00",
    "MW_DAILY_BUDGET": "10.00",
    "MW_CONFIRM_ABOVE": "0.50",
    "MW_MAX_PARALLEL": "3",
    "MW_PLANNER_MODEL": "claude-opus-5-5",
    "MW_PLANNER_MODEL_BUDGET": "claude-haiku-5-5",
    "MW_REVIEWER_MODEL": "claude-opus-5-5",
    "MW_REVIEWER_MODEL_BUDGET": "claude-haiku-5-5",
    "MEDIA_HOST": "tmpfiles",
    "MEDIA_HOST_FALLBACKS": "catbox",
    "ENHANCOR_BASE_URL": "https://apireq.enhancor.ai/api/seedance2.5/v1",
    "MW_ALLOW_MOCK": "1",
}

_loaded_mtime: float | None = None
_file_values: dict[str, str] = {}


def _read_env_file() -> dict[str, str]:
    global _loaded_mtime, _file_values
    try:
        mtime = ENV_FILE.stat().st_mtime
    except OSError:
        _loaded_mtime, _file_values = None, {}
        return _file_values
    if mtime != _loaded_mtime:
        values = {}
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip().strip('"').strip("'")
        _loaded_mtime, _file_values = mtime, values
    return _file_values


def setting(name: str, default: str | None = None) -> str:
    """Environment wins over .env so CI and shells can override safely."""
    value = os.environ.get(name)
    if value is None or value == "":
        value = _read_env_file().get(name, "")
    if value == "":
        value = default if default is not None else DEFAULTS.get(name, "")
    return value


def number(name: str) -> float:
    """A numeric setting. Anything unusable (text, NaN, negative) falls back to the safe default."""
    try:
        value = float(setting(name))
    except (TypeError, ValueError):
        return float(DEFAULTS[name])
    if not math.isfinite(value) or value < 0:
        return float(DEFAULTS[name])
    return value


_assume = threading.local()


@contextmanager
def assume_all_keys():
    """Price things as if every provider key were set (for the price guide). This thread only."""
    _assume.on = True
    try:
        yield
    finally:
        _assume.on = False


def _assuming() -> bool:
    return getattr(_assume, "on", False)


def has_key(name: str) -> bool:
    if _assuming() and name in KEYS:
        return True
    return bool(setting(name))


def credential(name: str) -> str:
    value = setting(name)
    if not value:
        raise MissingKey(name)
    return value


class MissingKey(RuntimeError):
    def __init__(self, name: str):
        super().__init__(
            f"{name} is not set. Add it to .env (see .env.example) or the Settings tab, then retry."
        )
        self.name = name


def save_keys(updates: dict[str, str]) -> None:
    """Write or replace keys in .env with owner-only permissions."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        key = line.partition("=")[0].strip()
        if key in remaining and not line.lstrip().startswith("#"):
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in remaining.items())
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(ENV_FILE, 0o600)


def providers_status() -> dict[str, bool]:
    status = {provider: has_key(key) for key, provider in KEYS.items()}
    status["pollinations"] = True  # free, no key
    status["mock"] = setting("MW_ALLOW_MOCK") not in ("0", "false", "no") and not _assuming()
    return status
