"""Spend guard. Every paid call is checked and logged *before* it is sent.

Provider bills are the source of truth; this ledger records our estimates so
a runaway loop or a typo (60 shots instead of 6) cannot quietly drain a card.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def _ledger():
    config.RUNS.mkdir(parents=True, exist_ok=True)
    return config.RUNS / "ledger.jsonl"


def entries() -> list[dict]:
    path = _ledger()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def spent_today() -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(r.get("usd", 0) for r in entries() if r.get("at", "").startswith(today))


def spent_on_job(job_id: str) -> float:
    return sum(r.get("usd", 0) for r in entries() if r.get("job") == job_id)


def check_job(total_estimate: float) -> None:
    cap = config.number("MW_MAX_COST_PER_JOB")
    if total_estimate > cap:
        raise BudgetExceeded(
            f"Estimated ${total_estimate:.2f} is over MW_MAX_COST_PER_JOB (${cap:.2f}). "
            "Use a cheaper tier, fewer shots, or raise the cap in .env."
        )


def charge(job_id: str, model_id: str, usd: float, note: str = "") -> None:
    """Reserve spend for one paid call; raises if it would break a cap."""
    if usd <= 0:
        return
    with _lock:
        daily = config.number("MW_DAILY_BUDGET")
        today = spent_today()
        if today + usd > daily:
            raise BudgetExceeded(
                f"Daily budget reached: ${today:.2f} of ${daily:.2f} used, this call needs ~${usd:.2f}. "
                "Raise MW_DAILY_BUDGET in .env if this is intended."
            )
        job_cap = config.number("MW_MAX_COST_PER_JOB")
        job_spent = spent_on_job(job_id)
        if job_spent + usd > job_cap + 1e-9:
            raise BudgetExceeded(
                f"This job would exceed MW_MAX_COST_PER_JOB (${job_cap:.2f}); ${job_spent:.2f} already used."
            )
        row = {
            "at": datetime.now(timezone.utc).isoformat(),
            "job": job_id,
            "model": model_id,
            "usd": round(usd, 4),
            "note": note,
        }
        with _ledger().open("a") as f:
            f.write(json.dumps(row) + "\n")


def refund(job_id: str, model_id: str, usd: float, note: str = "") -> None:
    """Undo a reservation for a request the provider never accepted."""
    if usd <= 0:
        return
    with _lock:
        row = {"at": datetime.now(timezone.utc).isoformat(), "job": job_id, "model": model_id,
               "usd": -round(usd, 4), "note": note}
        with _ledger().open("a") as f:
            f.write(json.dumps(row) + "\n")


def needs_confirmation(total_estimate: float) -> bool:
    return total_estimate >= config.number("MW_CONFIRM_ABOVE")


def report() -> dict:
    return {
        "spent_today": round(spent_today(), 4),
        "daily_budget": config.number("MW_DAILY_BUDGET"),
        "max_cost_per_job": config.number("MW_MAX_COST_PER_JOB"),
        "confirm_above": config.number("MW_CONFIRM_ABOVE"),
        "all_time": round(sum(r.get("usd", 0) for r in entries()), 4),
    }
