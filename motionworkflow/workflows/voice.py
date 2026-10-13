"""Text-to-speech: a voiceover line or a full narration as one audio file."""
from __future__ import annotations

import shutil

from .. import catalog, media, planner
from ..jobs import Job
from .common import first_input, first_of_kind, generate, line, parallel, total


def _chunks(text: str, limit: int) -> list[str]:
    """Whole sentences per call, within the model's text limit."""
    out, cur = [], ""
    for sentence in planner._split_sentences(text):
        pieces = []
        while len(sentence) > limit:  # one very long sentence: cut at a space
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        pieces.append(sentence)
        for piece in pieces:
            if cur and len(cur) + 1 + len(piece) > limit:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur} {piece}".strip()
    if cur:
        out.append(cur)
    return out


def _model(params: dict, cloned: bool = False) -> dict:
    return catalog.resolve("voice_clone" if cloned else "tts", params.get("tier"), params.get("model") or None)


def estimate(params: dict, counts: dict) -> dict:
    model = _model(params, counts.get("voice_sample", 0) > 0 or bool(params.get("voice_id")))
    return total([line("Voice", model, catalog.estimate(model, {"text": params.get("text") or ""}))])


def run(job: Job) -> None:
    text = (job.params.get("text") or "").strip()
    if not text:
        raise ValueError("Write the words to speak.")
    sample = first_input(job, "voice_sample")
    model = _model(job.params, bool(sample))
    request = {"text": text}
    if sample:
        request["voice_sample"] = str(sample)
        if job.params.get("voice_transcript"):
            request["ref_text"] = job.params["voice_transcript"]
    else:
        request["voice"] = job.params.get("voice") or model.get("default_voice")
    parts = _chunks(text, int(model.get("max_chars") or 4000))
    if len(parts) == 1:
        audio = first_of_kind(generate(job, "voice", model, request, label="Voice"), "audio")
        dest = job.path("voice" + audio.suffix)
        shutil.copyfile(audio, dest)
    else:
        def one(item):
            i, chunk = item
            return first_of_kind(generate(job, f"voice-{i}", model, {**request, "text": chunk},
                                          label=f"Voice part {i + 1}"), "audio")
        audios = parallel(one, list(enumerate(parts)))
        dest = media.concat_audio(audios, job.path("voice.wav"))
    job.add_output(dest, "Voice", "audio", final=True)
