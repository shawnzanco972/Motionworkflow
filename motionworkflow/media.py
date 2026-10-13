"""Local video/audio processing with ffmpeg. No paid calls in this module."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

SIZES = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (1080, 1080),
    "4:3": (960, 720),
    "3:4": (720, 960),
}
FPS = 24


class MediaError(RuntimeError):
    pass


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # optional pip fallback

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise MediaError("ffmpeg is required. macOS: brew install ffmpeg · Ubuntu/WSL: sudo apt install ffmpeg") from exc


def run(args: list, cwd: Path | None = None) -> None:
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise MediaError("ffmpeg failed: " + (result.stderr.strip().splitlines() or ["unknown error"])[-1])


def probe(path: Path) -> dict:
    """Duration, size and audio presence for a media file."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise MediaError(f"Cannot read {Path(path).name}: {out.stderr.strip()[:200]}")
        data = json.loads(out.stdout)
        video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
        audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
        duration = float(data["format"].get("duration") or (video or {}).get("duration") or 0)
        return {
            "duration": duration,
            "width": int(video["width"]) if video else 0,
            "height": int(video["height"]) if video else 0,
            "has_video": video is not None,
            "has_audio": audio is not None,
        }
    # Fallback: parse ffmpeg's banner.
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else 0.0
    return {
        "duration": duration,
        "width": int(size[1]) if size else 0,
        "height": int(size[2]) if size else 0,
        "has_video": "Video:" in out,
        "has_audio": "Audio:" in out,
    }


def size_for(aspect: str) -> tuple[int, int]:
    return SIZES.get(aspect, SIZES["9:16"])


def aspect_of(width: int, height: int) -> str:
    ratio = width / max(1, height)
    return min(SIZES, key=lambda a: abs(SIZES[a][0] / SIZES[a][1] - ratio))


def _fill(w: int, h: int) -> str:
    """Scale to cover, then center-crop: no letterboxing."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def normalize_clip(src: Path, dst: Path, size: tuple[int, int], seconds: float | None = None, keep_audio: bool = False) -> Path:
    w, h = size
    args = ["-i", src]
    if seconds:
        # Hold the last frame if the clip is short; trim if it is long.
        args += ["-vf", f"{_fill(w, h)},fps={FPS},tpad=stop_mode=clone:stop_duration={seconds}", "-t", f"{seconds:.3f}"]
    else:
        args += ["-vf", f"{_fill(w, h)},fps={FPS}"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-b:a", "160k"] if keep_audio else ["-an"]
    run([*args, dst])
    return dst


def still_to_clip(image: Path, dst: Path, seconds: float, size: tuple[int, int], motion: str = "zoom_in",
                  max_hold: float = 4.0) -> Path:
    """Ken Burns move over a still image: the cheapest way to make 'video'.

    A still is never held longer than `max_hold` seconds: longer shots cut to a
    punch-in on the same picture halfway (Take One: no still past about 4 s).
    """
    if seconds > max_hold + 0.5:
        first = _move(image, dst.with_name(dst.stem + "-a.mp4"), seconds / 2, size, motion)
        second = _move(image, dst.with_name(dst.stem + "-b.mp4"), seconds - seconds / 2, size, "punch_in")
        concat([first, second], dst)
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
        return dst
    return _move(image, dst, seconds, size, motion)


def _move(image: Path, dst: Path, seconds: float, size: tuple[int, int], motion: str) -> Path:
    w, h = size
    frames = max(1, round(seconds * FPS))
    big_w, big_h = w * 2, h * 2  # oversample so the zoom is smooth
    step = 0.15 / frames
    zoom = {
        "zoom_in": f"z='min(1+{step}*on,1.15)'",
        "zoom_out": f"z='max(1.15-{step}*on,1)'",
        "pan_left": "z='1.12'",
        "pan_right": "z='1.12'",
        "punch_in": f"z='1.32+{step / 2}*on'",
    }.get(motion, f"z='min(1+{step}*on,1.15)'")
    x = {
        "pan_left": f"x='(iw-iw/zoom)*(1-on/{frames})'",
        "pan_right": f"x='(iw-iw/zoom)*on/{frames}'",
    }.get(motion, "x='iw/2-(iw/zoom/2)'")
    # The punch-in favours the upper middle, where faces usually are.
    y = "y='(ih-ih/zoom)*0.3'" if motion == "punch_in" else "y='ih/2-(ih/zoom/2)'"
    vf = f"{_fill(big_w, big_h)},zoompan={zoom}:{x}:{y}:d={frames}:s={w}x{h}:fps={FPS},setsar=1"
    run(["-loop", "1", "-i", image, "-vf", vf, "-frames:v", frames, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-an", dst])
    return dst


def concat(clips: list[Path], dst: Path) -> Path:
    """Join clips that already share size/fps (see normalize_clip)."""
    if not clips:
        raise MediaError("Nothing to join.")
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(c).resolve()}'\n" for c in clips))
    run(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", dst])
    listing.unlink(missing_ok=True)
    return dst


def fit_audio(src: Path, dst: Path, seconds: float) -> Path:
    """Pad with silence or trim so the audio is exactly `seconds` long."""
    run(["-i", src, "-af", f"apad=whole_dur={seconds:.3f}", "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "2", dst])
    return dst


def silence(dst: Path, seconds: float) -> Path:
    run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.3f}", dst])
    return dst


def concat_audio(parts: list[Path], dst: Path) -> Path:
    inputs = []
    for p in parts:
        inputs += ["-i", p]
    graph = "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]"
    run([*inputs, "-filter_complex", graph, "-map", "[a]", "-ar", "44100", "-ac", "2", dst])
    return dst


def mix(video: Path, dst: Path, voice: Path | None = None, music: Path | None = None,
        music_volume: float = 0.18, keep_clip_audio: bool = False) -> Path:
    """Lay voice and (ducked) music under a video. Output length = video length."""
    info = probe(video)
    total = f"{info['duration']:.3f}"
    inputs = ["-i", video]
    labels = []
    graph = []
    idx = 1
    if keep_clip_audio and info["has_audio"]:
        labels.append("[0:a]")
    if voice:
        inputs += ["-i", voice]
        split = ",asplit=2[voice][key]" if music else "[voice]"
        graph.append(f"[{idx}:a]aresample=44100,apad=whole_dur={total}{split}")
        labels.append("[voice]")
        idx += 1
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        bed = "[bed0]" if voice else "[bed]"
        graph.append(f"[{idx}:a]aresample=44100,atrim=0:{total},volume={music_volume}{bed}")
        if voice:
            # Duck the music under the narration.
            graph.append("[bed0][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bed]")
        labels.append("[bed]")
        idx += 1
    if not labels:
        shutil.copyfile(video, dst)
        return dst
    graph.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                 f"atrim=0:{total},alimiter=limit=0.95[out]")
    run([*inputs, "-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[out]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", total, dst])
    return dst


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


STOP_WORDS = {"the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "with", "is", "it", "this",
              "that", "he", "she", "they", "we", "you", "i", "his", "her", "my", "your", "our", "was", "are", "be"}


BREAK_BEFORE = {"because", "but", "and", "so", "when", "while", "until", "then", "which", "who", "or", "if"}


def _phrases(words: list[str], limit: int = 7) -> list[list[str]]:
    """Whole lines up to `limit` words; longer lines split where a speaker would pause."""
    if len(words) <= limit:
        return [words]
    best, best_score = None, 0
    for i in range(2, min(len(words) - 1, limit + 1) + 1):
        score = 0
        if words[i - 1][-1:] in ",.;:!?—-":
            score = 3
        elif words[i].lower().strip(",.") in BREAK_BEFORE:
            score = 2
        if score and score >= best_score:
            best, best_score = i, score
    if best:
        return [words[:best], *_phrases(words[best:], limit)]
    parts = -(-len(words) // limit)
    size = -(-len(words) // parts)
    return [words[i:i + size] for i in range(0, len(words), size)]


def _key_word(words: list[str]) -> int:
    """The word to light: the longest non-filler word, later words win ties."""
    best, best_len = len(words) - 1, -1
    for i, w in enumerate(words):
        core = w.strip(",.;:!?\"'").lower()
        if core not in STOP_WORDS and len(core) >= best_len:
            best, best_len = i, len(core)
    return best


def _rows(words: list[str], row_chars: int) -> list[list[str]]:
    """Pack words into rows of at most `row_chars` visible characters."""
    rows: list[list[str]] = [[]]
    for w in words:
        if rows[-1] and len(" ".join(rows[-1] + [w])) > row_chars:
            rows.append([])
        rows[-1].append(w)
    return rows


def caption_chunks(text: str, start: float, end: float, min_hold: float = 1.2,
                   highlight: str | None = "#FFE500", row_chars: int = 18) -> list[tuple[float, float, str]]:
    """Captions a muted viewer can follow (Take One words.md).

    Short lines go on screen whole, in two or three big rows, with their key
    word lit; each caption holds at least `min_hold` seconds.
    """
    words = text.split()
    if not words:
        return []
    phrases = _phrases(words)
    span = max(0.1, end - start)

    def share(phrase):
        return span * len(" ".join(phrase)) / (sum(len(" ".join(p)) for p in phrases) or 1)

    # Merge phrases that would flash by too fast.
    while len(phrases) > 1 and min(share(p) for p in phrases) < min_hold:
        i = min(range(len(phrases)), key=lambda k: len(" ".join(phrases[k])))
        j = i + 1 if i + 1 < len(phrases) else i - 1
        a, b = sorted((i, j))
        phrases[a:b + 1] = [phrases[a] + phrases[b]]
    out, t = [], start
    for phrase in phrases:
        dur = share(phrase)
        key = _key_word(phrase) if highlight and len(phrase) > 1 else -1
        rows, index = [], 0
        for row in _rows(phrase, row_chars):
            shown = []
            for w in row:
                shown.append(f'<font color="{highlight}">{w}</font>' if index == key else w)
                index += 1
            rows.append(" ".join(shown))
        out.append((t, t + dur, "\n".join(rows)))
        t += dur
    return out


def write_srt(cues: list[tuple[float, float, str]], dst: Path) -> Path:
    lines = []
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{_ts(a)} --> {_ts(b)}", text, ""]
    dst.write_text("\n".join(lines))
    return dst


CAPTION_STYLES = {
    # Big words in the lower third, the short-form social look. Alignment 2
    # (bottom centre) means the same thing in SSA and ASS numbering.
    "bold": "FontName=DejaVu Sans,Bold=1,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=2.5,Shadow=0,Alignment=2,MarginV=70",
    "yellow": "FontName=DejaVu Sans,Bold=1,FontSize=22,PrimaryColour=&H0000E5FF,OutlineColour=&H00000000,"
              "BorderStyle=1,Outline=2.5,Shadow=0,Alignment=2,MarginV=70",
    # Classic subtitles at the bottom.
    "classic": "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
               "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=30",
}


def burn_captions(video: Path, srt: Path, dst: Path, style: str = "bold", aspect: str = "16:9") -> Path:
    """Burn subtitles in. Runs inside the folder so no path escaping is needed."""
    folder = Path(video).resolve().parent
    srt_name = Path(srt).resolve().relative_to(folder)
    force = CAPTION_STYLES.get(style, CAPTION_STYLES["bold"])
    if aspect in ("9:16", "3:4"):
        # Smaller type for the narrow frame (about 50 px rows at 720 wide), and clear of the
        # apps' button column on the right (Take One vertical.md safe zone).
        force = force.replace("FontSize=22", "FontSize=12") + ",MarginL=20,MarginR=50"
    elif aspect == "1:1":
        force = force.replace("FontSize=22", "FontSize=16")
    run(["-i", Path(video).name, "-vf", f"subtitles={srt_name}:force_style='{force}'",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy",
         Path(dst).resolve()], cwd=folder)
    return dst


def restore_audio(generated: Path, source: Path, dst: Path, max_pad: float = 1.0, limit: float | None = None) -> dict:
    """Put the source's complete, untouched soundtrack under a generated video.

    The generated clip is trimmed if long, or its last frame held if it is up
    to `max_pad` seconds short. The source audio is never stretched; it is
    only cut at `limit` (when the clip sent to the model was trimmed).
    """
    gen = probe(generated)
    src = probe(source)
    if not src["has_audio"]:
        shutil.copyfile(generated, dst)
        return {"audio": "none in source", "adjustment": None}
    target = min(src["duration"], limit) if limit else src["duration"]
    gap = target - gen["duration"]
    if gap > max_pad:
        raise MediaError(
            f"Generated video is {gap:.2f}s shorter than the source; refusing to cut the original audio. "
            "Use a shorter source clip or a model that supports the full length."
        )
    vf = f"tpad=stop_mode=clone:stop_duration={max(gap, 0) + 0.05:.3f}" if gap > 0.04 else "null"
    base = ["-i", generated, "-i", source, "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    try:
        # Copy the original compressed audio packets: bit-for-bit the source mix.
        run([*base, "-c:a", "copy", "-t", f"{target:.3f}", dst])
        audio = "original source audio, copied untouched"
    except MediaError:
        # e.g. PCM or Opus audio that MP4 can't carry as-is.
        run([*base, "-c:a", "aac", "-b:a", "256k", "-t", f"{target:.3f}", dst])
        audio = "original source audio, re-encoded to AAC for MP4"
    adjustment = None
    if gap > 0.04:
        adjustment = f"held last frame {gap:.2f}s"
    elif gap < -0.04:
        adjustment = f"trimmed {-gap:.2f}s of generated video"
    return {"audio": audio, "adjustment": adjustment}


def trim(src: Path, dst: Path, seconds: float) -> Path:
    run(["-i", src, "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac", dst])
    return dst


def thumbnail(video: Path, dst: Path, at: float = 0.5) -> Path:
    run(["-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=480:-2", dst])
    return dst


def last_frame(video: Path, dst: Path) -> Path:
    """Grab the final frame, e.g. to chain shots for continuity."""
    run(["-sseof", "-0.1", "-i", video, "-frames:v", "1", "-update", "1", dst])
    return dst


def seconds_label(seconds: float) -> str:
    return f"{math.floor(seconds // 60)}:{seconds % 60:04.1f}"
