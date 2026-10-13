"""Command line: `mw <command>` (or `python -m motionworkflow <command>`).

Every generation command shows its cost estimate first. Add --estimate to
only print the quote, and --yes to skip the confirmation prompt.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import budget, catalog, config, jobs, media, workflows
from .jobs import DONE, ERROR, WAITING


JSON_OUTPUT = False


def _print_quote(quote: dict) -> None:
    if JSON_OUTPUT:
        return
    for item in quote["items"]:
        mock = "  [mock: no key]" if item.get("mock") else ""
        print(f"  {item['label']:<44} {item['model_name']:<42} ~${item['usd']:.3f}{mock}")
    print(f"  {'Estimated total':<87} ~${quote['total']:.3f}")


def _confirm(quote: dict, yes: bool) -> bool:
    if not quote["needs_confirmation"] or yes:
        return True
    if not sys.stdin.isatty():
        print("Estimated cost is above MW_CONFIRM_ABOVE; re-run with --yes to approve it.")
        return False
    return input(f"Spend ~${quote['total']:.2f}? [y/N] ").strip().lower() in ("y", "yes")


def _files(**fields) -> dict:
    out = {}
    for name, value in fields.items():
        if not value:
            continue
        paths = [Path(v).expanduser() for v in (value if isinstance(value, list) else [value])]
        for p in paths:
            if not p.is_file():
                raise SystemExit(f"File not found: {p}")
            try:
                from .validation import InputError, check_media

                check_media(p, name)
            except InputError as exc:
                raise SystemExit(f"Error: {exc}") from None
        out[name] = paths
    return out


def _report(job: jobs.Job) -> int:
    state = job.data["state"]
    if JSON_OUTPUT:
        out = {
            "job": job.id,
            "state": state,
            "status": job.data["status"],
            "error": job.data.get("error"),
            "awaiting": job.data.get("awaiting"),
            "outputs": [{"label": o["label"], "kind": o["kind"], "final": o.get("final", False),
                         "path": str(job.folder / o["path"])} for o in job.data.get("outputs", [])],
            "spent_usd": round(budget.spent_on_job(job.id), 4),
            "used_mock": bool(job.data.get("used_mock")),
            "review": job.data.get("review"),
        }
        print(json.dumps(out, indent=2))
        return 1 if state == ERROR else 0
    print(f"\nJob {job.id}: {state} - {job.data['status']}")
    if job.data.get("warning"):
        print("Note:", job.data["warning"])
    for output in job.data.get("outputs", []):
        marker = "*" if output.get("final") else "-"
        print(f"  {marker} {output['label']}: {job.folder / output['path']}")
    if state == WAITING:
        stage = job.data["awaiting"]["stage"]
        print(f"\nApprove with:  mw approve {job.id}    (stage: {stage})")
        print(f"Redo a step:   mw redo {job.id} key-0 ...   then approve again")
    if state == ERROR:
        print(f"\nAfter fixing the cause:  mw retry {job.id}")
        return 1
    return 0


def _launch(workflow: str, params: dict, files: dict, args) -> int:
    counts = {k: len(v) for k, v in files.items()}
    counts.update(params.pop("_counts", {}))
    if workflow == "swap" and files.get("video"):
        params["source_seconds"] = round(media.probe(files["video"][0])["duration"], 2)
    try:
        from . import validation

        validation.coerce(workflow, params)
        validation.require(workflow, params, counts)
        quote = workflows.estimate(workflow, params, counts)
    except (ValueError, config.MissingKey) as exc:
        print("Error:", exc)
        return 2
    if JSON_OUTPUT and args.estimate:
        print(json.dumps({"estimate": quote["total"], "items": quote["items"], "mock": quote["mock"]}, indent=2))
        return 0
    if not JSON_OUTPUT:
        print(f"{workflow} estimate:")
    _print_quote(quote)
    if quote["mock"] and not JSON_OUTPUT:
        print("  Some steps use offline mock output because no API key is set for them.")
    if args.estimate:
        return 0
    try:
        budget.check_job(quote["total"])
    except budget.BudgetExceeded as exc:
        print("Error:", exc)
        return 2
    if not _confirm(quote, args.yes):
        print("Cancelled; nothing was spent.")
        return 1
    job = jobs.create(workflow, params, files)
    job.data["estimate"] = quote
    job.save()
    if not JSON_OUTPUT:
        print(f"Job {job.id} started. Files: {job.folder}")
    workflows.run(job)
    return _report(job)


def _progress(job, message):
    print(f"  [{job.id}] {message}", file=sys.stderr if JSON_OUTPUT else sys.stdout, flush=True)


# -- commands -------------------------------------------------------------------

def cmd_serve(args):
    from . import server, webhook

    if (args.tunnel and config.has_key("ENHANCOR_API_KEY") and not config.setting("ENHANCOR_WEBHOOK_URL")
            and webhook.available()):
        webhook.start_tunnel()
    server.main(port=args.port)


def cmd_doctor(args):
    ok = True
    print(f"Python {sys.version.split()[0]}")
    try:
        print("ffmpeg:", media.ffmpeg())
    except media.MediaError as exc:
        print("ffmpeg: MISSING -", exc)
        ok = False
    status = config.providers_status()
    print("\nProviders:")
    for key, provider in config.KEYS.items():
        state = "ready" if status[provider] else "no key"
        print(f"  {provider:<12} {key:<22} {state}")
    print(f"  {'pollinations':<12} {'(no key needed)':<22} ready (free images)")
    from . import webhook

    if config.has_key("ENHANCOR_API_KEY"):
        has_hook = bool(config.setting("ENHANCOR_WEBHOOK_URL")) or webhook.available()
        print("\nEnhancor webhook:", "ok" if has_hook else "MISSING - install cloudflared or set ENHANCOR_WEBHOOK_URL")
    report = budget.report()
    print(f"\nBudget: ${report['spent_today']:.2f} of ${report['daily_budget']:.2f} today, "
          f"max ${report['max_cost_per_job']:.2f}/job, confirm above ${report['confirm_above']:.2f}")
    print("\nDefault models for tier", config.setting("MW_DEFAULT_TIER") + ":")
    for kind in catalog.KINDS:
        try:
            model = catalog.resolve(kind)
            print(f"  {kind:<15} {model['name']} ({catalog.price_label(model)})")
        except Exception as exc:  # noqa: BLE001
            print(f"  {kind:<15} unavailable: {exc}")
    if args.require_keys and not any(status[p] for p in ("fal", "replicate", "enhancor")):
        print("\nNo paid provider key set. Add FAL_KEY (recommended) to .env.")
        ok = False
    return 0 if ok else 1


def cmd_models(args):
    rows = catalog.for_kind(args.kind) if args.kind else catalog.models()
    if args.tier:
        rows = [m for m in rows if m["tier"] == args.tier]
    for m in sorted(rows, key=lambda m: (m["kind"], catalog.TIERS.index(m["tier"]), catalog.unit_price(m, {}))):
        mark = "ready" if catalog.available(m) else "no key"
        print(f"{m['kind']:<15} {m['tier']:<9} {catalog.price_label(m):<18} {m['id']:<32} {mark:<7} {m['name']}")
    return 0


def cmd_image(args):
    params = {"prompt": args.prompt, "num_images": args.n, "aspect_ratio": args.aspect, "tier": args.tier,
              "model": args.model, "seed": args.seed}
    return _launch("image", params, _files(refs=args.ref), args)


def cmd_video(args):
    params = {"prompt": args.prompt, "duration": args.duration, "aspect_ratio": args.aspect, "resolution": args.resolution,
              "tier": args.tier, "model": args.model, "final_tier": args.final_tier, "final_model": args.final_model,
              "seed": args.seed}
    if args.audio is not None:
        params["audio"] = args.audio
    return _launch("video", params, _files(image=args.image), args)


def cmd_short(args):
    script = Path(args.script_file).read_text() if args.script_file else ""
    params = {"idea": args.idea or "", "script": script, "shots": args.shots, "shot_seconds": args.seconds,
              "mode": args.mode, "aspect_ratio": args.aspect, "style": args.style, "tone": args.tone,
              "voiceover": not args.no_voice, "voice": args.voice, "captions": not args.no_captions,
              "caption_style": args.caption_style, "review": not args.no_review, "tier": args.tier,
              "image_model": args.image_model, "video_model": args.video_model, "tts_model": args.tts_model,
              "resolution": args.resolution}
    return _launch("short", params, _files(character=args.character, music=args.music), args)


def cmd_swap(args):
    params = {"prompt": args.prompt, "tier": args.tier, "model": args.model, "prepared": args.prepared,
              "draft_resolution": args.draft_resolution, "final_resolution": args.final_resolution,
              "prep": args.prep, "subject": args.subject, "direct": args.direct}
    return _launch("swap", params, _files(video=args.video, refs=args.ref, original=args.original), args)


def _library_or_file(kind: str, value: str | None):
    """An id from the library, or a path to a file."""
    from . import library

    if not value:
        return None, None
    if Path(value).expanduser().is_file():
        return None, Path(value).expanduser()
    try:
        item = library.get(kind, value)
    except library.LibraryError:
        raise SystemExit(f"'{value}' is neither a file nor an item in `mw {kind}`.") from None
    return item, Path(item["reference_path"] if kind == "voices" else item["path"])


def cmd_presenter(args):
    from . import library

    script = Path(args.script_file).read_text() if args.script_file else ""
    avatar_item, avatar = _library_or_file("avatars", args.avatar)
    voice_item, sample = _library_or_file("voices", args.voice_sample)
    if not avatar:
        raise SystemExit("Choose an avatar: --avatar <id from `mw avatars` or a photo/video file>.")
    params = {"topic": args.topic or "", "script": script, "seconds": args.seconds, "aspect_ratio": args.aspect,
              "tone": args.tone, "language": args.language, "audience": args.audience, "broll": args.broll,
              "captions": not args.no_captions, "caption_style": args.caption_style, "review": not args.no_review,
              "tier": args.tier, "voice": args.voice, "voice_model": args.voice_model, "avatar_model": args.avatar_model}
    if voice_item and voice_item.get("transcript") and voice_item["duration"] <= library.REF_SECONDS + 0.5:
        params["voice_transcript"] = voice_item["transcript"]
    files = _files(avatar=str(avatar), voice_sample=str(sample) if sample else None, music=args.music)
    counts_hint = {"avatar_is_video": avatar.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv")}
    params["_counts"] = counts_hint
    return _launch("presenter", params, files, args)


def cmd_library(args):
    from . import library

    kind = args.command  # avatars | voices
    if args.action == "add":
        if not args.file:
            raise SystemExit(f"mw {kind} add FILE --name NAME --consent")
        try:
            if kind == "avatars":
                item = library.add_avatar(Path(args.file), args.name or Path(args.file).stem, args.consent)
            else:
                item = library.add_voice(Path(args.file), args.name or Path(args.file).stem, args.consent, args.transcript or "")
        except (library.LibraryError, media.MediaError) as exc:
            print("Error:", exc)
            return 2
        print(json.dumps(item, indent=2) if JSON_OUTPUT else f"Added {item['name']} ({item['id']}).")
        return 0
    if args.action == "rm":
        library.delete(kind, args.file)
        print("Deleted", args.file)
        return 0
    rows = library.items(kind)
    if JSON_OUTPUT:
        print(json.dumps(rows, indent=2))
    for row in rows:
        detail = f"{row['kind']} {row['width']}x{row['height']}" if kind == "avatars" else f"{row['duration']:.1f}s"
        print(f"{row['id']}  {row['name']:<28} {detail}")
    if not rows:
        print(f"No {kind} yet. Add one: mw {kind} add FILE --name NAME --consent")
    return 0


def cmd_voice(args):
    text = Path(args.text_file).read_text() if args.text_file else (args.text or "")
    params = {"text": text, "voice": args.voice, "tier": args.tier, "model": args.model}
    return _launch("voice", params, {}, args)


def cmd_review(args):
    from . import reviewer

    job = _load(args.job)
    final = next((job.folder / o["path"] for o in job.data.get("outputs", []) if o.get("final") and o["kind"] == "video"), None)
    if not final:
        print("This job has no finished video to review.")
        return 1
    if not reviewer.available():
        print("The reviewer needs ANTHROPIC_API_KEY.")
        return 2
    plan = job.data.get("plan") or {}
    times = job.data.get("shot_times") or []
    words = [(times[i] if i < len(times) else 0.0, (times[i + 1] if i + 1 < len(times) else times[i] + 4) if times else 4.0,
              shot["narration"]) for i, shot in enumerate(plan.get("shots", [])) if shot.get("narration")]
    if not args.yes and not _confirm({"needs_confirmation": True, "total": reviewer.ESTIMATE_USD}, False):
        return 1
    budget.charge(job.id, "claude:review", reviewer.ESTIMATE_USD, note="review")
    result = reviewer.review(final, words, job.path("review"), tier=job.params.get("tier") or "budget")
    job.data["review"] = result
    job.add_output(job.path("review/REVIEW.md"), f"Reviewer: {result['verdict']}", "file")
    print(json.dumps(result, indent=2) if JSON_OUTPUT else reviewer.as_markdown(result))
    return 0


def _load(job_id):
    try:
        return jobs.load(job_id)
    except KeyError:
        raise SystemExit(f"No job {job_id}. See `mw jobs`.") from None


def cmd_jobs(args):
    for job in jobs.all_jobs(args.limit):
        spent = budget.spent_on_job(job.id)
        print(f"{job.id}  {job.data['created'][:16]}  {job.data['workflow']:<6} {job.data['state']:<18} "
              f"${spent:.3f}  {job.data['status'][:60]}")
    return 0


def cmd_status(args):
    job = _load(args.job)
    if args.json:
        print(json.dumps(job.public(), indent=2))
        return 0
    for key, step in job.data.get("steps", {}).items():
        print(f"  step {key:<12} {step.get('state'):<10} {step.get('model', '')} {step.get('error', '')}")
    if job.data.get("plan"):
        for i, shot in enumerate(job.data["plan"]["shots"]):
            print(f"  shot {i}: {shot['narration']}")
    return _report(job)


def cmd_approve(args):
    job = _load(args.job)
    awaiting = job.data.get("awaiting")
    if job.data["state"] != WAITING or not awaiting:
        print("This job is not waiting for approval.")
        return 1
    print(awaiting["message"])
    if not args.yes and sys.stdin.isatty() and input("Approve? [y/N] ").strip().lower() not in ("y", "yes"):
        return 1
    job.approve(awaiting["stage"], args.note or "")
    workflows.run(job)
    return _report(job)


def cmd_retry(args):
    job = _load(args.job)
    workflows.retry(job, force=args.force)
    workflows.run(job)
    return _report(job)


def cmd_redo(args):
    job = _load(args.job)
    overrides = {}
    if args.shot is not None:
        overrides[str(args.shot)] = {"visual": args.visual, "narration": args.narration, "motion": args.motion,
                                     "text": args.text}
    workflows.redo(job, args.steps, overrides)
    workflows.run(job)
    return _report(job)


def cmd_resume(args):
    job = _load(args.job)
    workflows.run(job)
    return _report(job)


def cmd_stop(args):
    job = _load(args.job)
    if job.data["state"] not in ("running", "queued"):
        print("This job isn't running.")
        return 1
    job.request_stop()  # the process running it (web app or another mw) stops at its next checkpoint
    print("Stop requested. Requests already sent may still finish (and be billed); `mw resume` collects them.")
    return 0


def cmd_spend(args):
    data = budget.summary(14)
    if JSON_OUTPUT:
        data.pop("recent")
        print(json.dumps(data, indent=2))
        return 0
    lim = data["limits"]
    print(f"Today      ${data['today']:.2f} of ${lim['daily_budget']:.2f} daily budget")
    print(f"7 days     ${data['week']:.2f}")
    print(f"30 days    ${data['month']:.2f}")
    print(f"All time   ${data['all_time']:.2f}  ({data['charges']} charges)")
    if data["by_model"]:
        print("\nBy model")
        for row in data["by_model"][:8]:
            print(f"  ${row['usd']:>7.3f}  {row['model']}")
    print(f"\nLimits: ${lim['max_cost_per_job']:.2f} per project, asks above ${lim['confirm_above']:.2f}. "
          "Estimates from catalog prices; your provider's bill is the source of truth.")
    return 0


def cmd_prices(args):
    from . import pricing

    guide = pricing.guide()
    if JSON_OUTPUT:
        print(json.dumps(guide, indent=2))
        return 0
    labels = {"free": "Cheapest", "budget": "Budget", "standard": "Standard", "premium": "Premium"}
    print(f"{'':32}" + "".join(f"{labels[t]:>11}" for t in guide["tiers"]))
    for row in guide["rows"]:
        cells = []
        for tier in guide["tiers"]:
            p = row["prices"][tier]
            text = "-" if not p else "same" if p.get("same_as_cheaper") else "free" if p["usd"] == 0 else f"${p['usd']:.{3 if p['usd'] < 0.1 else 2}f}"
            cells.append(f"{text + ('!' if p and p.get('over_cap') else ''):>11}")
        print(f"{row['title'][:31]:32}" + "".join(cells))
    print(f"\n! = over your per-project limit (${guide['max_cost_per_job']:.2f}). Priced as if every key were set.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mw", description="MotionWorkflow: cheap AI images, videos and shorts.")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="machine-readable result (for agents such as the Take One skill); progress goes to stderr")
    sub = p.add_subparsers(dest="command", required=True)

    def paid(cmd):
        cmd.add_argument("--tier", choices=catalog.TIERS, help="free, budget (default), standard, premium")
        cmd.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
        cmd.add_argument("--estimate", action="store_true", help="print the cost estimate and exit")
        return cmd

    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--no-tunnel", dest="tunnel", action="store_false", help="don't start the Enhancor callback tunnel")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("doctor", help="check setup, keys and default models")
    s.add_argument("--require-keys", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("models", help="list models with prices")
    s.add_argument("--kind", choices=catalog.KINDS)
    s.add_argument("--tier", choices=catalog.TIERS)
    s.set_defaults(fn=cmd_models)

    s = paid(sub.add_parser("image", help="text-to-image, or edit with --ref"))
    s.add_argument("prompt")
    s.add_argument("-n", type=int, default=1, help="number of images (max 8)")
    s.add_argument("--aspect", default="1:1", choices=list(media.SIZES))
    s.add_argument("--ref", action="append", help="reference image (repeatable)")
    s.add_argument("--model")
    s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_image)

    s = paid(sub.add_parser("video", help="text-to-video, or image-to-video with --image"))
    s.add_argument("prompt")
    s.add_argument("--image")
    s.add_argument("--duration", type=float, default=5)
    s.add_argument("--aspect", default="9:16", choices=list(media.SIZES))
    s.add_argument("--resolution")
    s.add_argument("--model")
    s.add_argument("--final-tier", choices=catalog.TIERS, help="render a cheap draft, then this tier after approval")
    s.add_argument("--final-model")
    s.add_argument("--audio", action=argparse.BooleanOptionalAction, default=None)
    s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_video)

    s = paid(sub.add_parser("short", help="idea -> script -> finished vertical video"))
    s.add_argument("idea", nargs="?")
    s.add_argument("--script-file", help="lines of: narration | visual prompt | motion")
    s.add_argument("--shots", type=int, default=5)
    s.add_argument("--seconds", type=float, default=5, help="seconds per shot")
    s.add_argument("--mode", choices=["slideshow", "animated"], default="slideshow")
    s.add_argument("--aspect", default="9:16", choices=list(media.SIZES))
    s.add_argument("--style", default="")
    s.add_argument("--tone", default="funny")
    s.add_argument("--character", help="reference image to keep one character consistent")
    s.add_argument("--music", help="background music file (ducked under the voice)")
    s.add_argument("--voice")
    s.add_argument("--no-voice", action="store_true")
    s.add_argument("--no-captions", action="store_true")
    s.add_argument("--caption-style", default="bold", choices=list(media.CAPTION_STYLES))
    s.add_argument("--no-review", action="store_true", help="animate without pausing at the storyboard")
    s.add_argument("--resolution")
    s.add_argument("--image-model")
    s.add_argument("--video-model")
    s.add_argument("--tts-model")
    s.set_defaults(fn=cmd_short)

    s = paid(sub.add_parser("swap", help="replace the person in a video with your character"))
    s.add_argument("video")
    s.add_argument("--ref", action="append", required=True, help="character image (or video for Seedance Omni)")
    s.add_argument("--prompt", default="")
    s.add_argument("--original", help="untouched original whose audio goes on the final")
    s.add_argument("--prepared", action="store_true", help="video is a Genjutsu seedance-input.mp4")
    s.add_argument("--prep", default="none", choices=["none", "genjutsu-depth", "genjutsu-face-mesh", "genjutsu-depth-mesh"],
                   help="run Genjutsu's preparation first (Seedance engine; pauses for the full-clip review)")
    s.add_argument("--subject", default="person", help="what SAM 3 should segment for Genjutsu depth prep")
    s.add_argument("--direct", action="store_true", help="skip the draft: one render at final quality")
    s.add_argument("--model")
    s.add_argument("--draft-resolution")
    s.add_argument("--final-resolution")
    s.set_defaults(fn=cmd_swap)

    s = paid(sub.add_parser("presenter", help="you talking to camera: topic -> script -> your voice -> your avatar"))
    s.add_argument("topic", nargs="?")
    s.add_argument("--script-file", help="your own words instead of a topic")
    s.add_argument("--avatar", help="avatar id (mw avatars) or a photo / short video of you")
    s.add_argument("--voice-sample", help="voice id (mw voices) or a recording of you; omit for a stock voice")
    s.add_argument("--voice", help="stock voice name when there is no voice sample")
    s.add_argument("--seconds", type=float, default=30)
    s.add_argument("--aspect", default="9:16", choices=list(media.SIZES))
    s.add_argument("--tone", default="friendly expert")
    s.add_argument("--language", default="English")
    s.add_argument("--audience", default="")
    s.add_argument("--broll", action="store_true", help="cut away to illustrative pictures on some lines")
    s.add_argument("--music")
    s.add_argument("--no-captions", action="store_true")
    s.add_argument("--caption-style", default="bold", choices=list(media.CAPTION_STYLES))
    s.add_argument("--no-review", action="store_true", help="animate without pausing to approve script and voice")
    s.add_argument("--voice-model")
    s.add_argument("--avatar-model")
    s.set_defaults(fn=cmd_presenter)

    for kind, what in (("avatars", "photo or short video of a presenter"), ("voices", "recording of a voice")):
        s = sub.add_parser(kind, help=f"your saved {kind} ({what})")
        s.add_argument("action", nargs="?", default="list", choices=["list", "add", "rm"])
        s.add_argument("file", nargs="?", help="file to add, or id to remove")
        s.add_argument("--name")
        s.add_argument("--consent", action="store_true", help="it is you, or the person agreed")
        if kind == "voices":
            s.add_argument("--transcript", help="what is said in the recording (improves cloning)")
        s.set_defaults(fn=cmd_library)

    s = paid(sub.add_parser("voice", help="text-to-speech voiceover"))
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("--voice")
    s.add_argument("--model")
    s.set_defaults(fn=cmd_voice)

    s = sub.add_parser("review", help="fresh-eyes score of a finished video (Claude, ~$0.03)")
    s.add_argument("job")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("jobs", help="list recent jobs")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_jobs)

    s = sub.add_parser("status", help="show one job")
    s.add_argument("job")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("approve", help="approve a waiting job (storyboard / final)")
    s.add_argument("job")
    s.add_argument("--note")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("retry", help="resubmit failed steps (spends again)")
    s.add_argument("job")
    s.add_argument("--force", action="store_true", help="also resubmit steps with an unclear outcome")
    s.set_defaults(fn=cmd_retry)

    s = sub.add_parser("redo", help="regenerate steps, e.g. key-2 (optionally with new shot text)")
    s.add_argument("job")
    s.add_argument("steps", nargs="*")
    s.add_argument("--shot", type=int, help="shot index to edit")
    s.add_argument("--visual")
    s.add_argument("--narration")
    s.add_argument("--motion")
    s.add_argument("--text", help="presenter: new words for line --shot")
    s.set_defaults(fn=cmd_redo)

    s = sub.add_parser("resume", help="continue a job after a restart (never resubmits)")
    s.add_argument("job")
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("stop", help="stop a running job at its next checkpoint (resume later)")
    s.add_argument("job")
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("spend", help="what you've spent: today, 7 and 30 days, by model")
    s.set_defaults(fn=cmd_spend)

    s = sub.add_parser("prices", help="price guide: typical projects at each quality tier")
    s.set_defaults(fn=cmd_prices)
    return p


def main(argv: list[str] | None = None) -> int:
    global JSON_OUTPUT
    args = parser().parse_args(argv)
    JSON_OUTPUT = args.as_json
    if args.command not in ("serve",) and _progress not in jobs.listeners:
        jobs.listeners.append(_progress)
    try:
        return args.fn(args) or 0
    except config.MissingKey as exc:
        print("Error:", exc)
        return 2
    except catalog.CatalogError as exc:
        print("Error:", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
