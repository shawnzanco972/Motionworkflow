"""Text-to-speech: a voiceover line or a full narration as one audio file."""
from __future__ import annotations

import shutil

from .. import catalog
from ..jobs import Job
from .common import first_of_kind, generate, line, total


def _model(params: dict) -> dict:
    return catalog.resolve("tts", params.get("tier"), params.get("model") or None)


def estimate(params: dict, counts: dict) -> dict:
    model = _model(params)
    return total([line("Voice", model, catalog.estimate(model, {"text": params.get("text") or ""}))])


def run(job: Job) -> None:
    text = (job.params.get("text") or "").strip()
    if not text:
        raise ValueError("Write the words to speak.")
    model = _model(job.params)
    voice = job.params.get("voice") or model.get("default_voice")
    files = generate(job, "voice", model, {"text": text, "voice": voice}, label="Voice")
    audio = first_of_kind(files, "audio")
    dest = job.path("voice" + audio.suffix)
    shutil.copyfile(audio, dest)
    job.add_output(dest, "Voice", "audio", final=True)
