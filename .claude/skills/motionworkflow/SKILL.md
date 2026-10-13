---
name: motionworkflow
description: Make AI images, videos, voiceovers, narrated short-form videos (TikTok/Reels/Shorts) and Genjutsu character swaps with this repo's `mw` CLI, on cheap models with cost estimates, budget caps, approval gates and a fresh-eyes reviewer score. Also the cheap asset engine (pictures, moving shots, voice) for the Take One film skill. Use when the user asks to generate, animate, script, caption, voice or swap characters in media, or asks what it would cost.
---

# MotionWorkflow

Run everything from the repo root with `.venv/bin/mw` (run `./setup.sh` first if `.venv` is missing). Read `AGENTS.md` for the spending and consent rules; they override convenience.

## 1. Check what's available

```bash
.venv/bin/mw doctor              # keys present, default model per kind for the tier
.venv/bin/mw models --kind video # prices and ids
```

If a step resolves to a `mock:` model, tell the user it will be placeholder media and which key unlocks the real one (usually `FAL_KEY`).

## 2. Quote, then run

Every generation command takes `--estimate` (prints the quote, spends nothing). Show the quote, then run without `--estimate`. Add `--yes` only when the user approved that amount.

| Request | Command |
|---|---|
| You talking to camera | `mw presenter "TOPIC" --avatar ID --voice-sample ID --seconds 30` → pauses after script + voice |
| Save your face / voice | `mw avatars add FILE --name N --consent` · `mw voices add FILE --name N --consent [--transcript ...]` |
| Narrated short, cheapest | `mw short "IDEA" --shots 6` (slideshow: keyframes + voice + captions) |
| Narrated short, AI motion | `mw short "IDEA" --mode animated --tier budget` → pauses at storyboard |
| Own script | `mw short --script-file script.txt` (lines: `narration \| visual \| motion`) |
| Consistent character | `--character face.png` (short) / `--ref face.png` (image) |
| Images | `mw image "PROMPT" -n 4 --aspect 9:16` |
| Video from text / still | `mw video "PROMPT"` / `mw video "MOTION" --image still.png` |
| Cheap draft then premium | `mw video "PROMPT" --final-tier premium` → pauses after draft |
| Character swap | `mw swap clip.mp4 --ref character.png [--prompt ...]` → pauses after draft |
| Genjutsu swap (depth + SAM 3) | `mw swap clip.mp4 --ref c.png --model enhancor:seedance-edit --prep genjutsu-depth` → pauses for full-clip mask review |
| One render, no draft | add `--direct` to `mw swap` (a Seedance draft costs extra overall) |
| Voiceover | `mw voice "LINE" [--voice af_heart]` or `--text-file lines.txt` |
| Score a finished video | `mw review JOB` (Claude sees only frames + timed words; PASS needs 8+ on every axis) |

Put `--json` before the command (`mw --json image ...`) for machine-readable results with absolute output paths.

Tiers: `--tier free|budget|standard|premium` (default from `MW_DEFAULT_TIER`). Pick an exact model with `--model ID` (see `mw models`).

## 3. Approval gates

When a job prints `awaiting_approval`:

1. `mw status JOB` — shows the shots and output paths. Look at the keyframes/draft (open the image or extract a frame with ffmpeg) and describe them to the user.
2. Fix weak shots cheaply: `mw redo JOB --shot N --visual "new prompt" key-N` (also `--narration`, `--motion`). Redo withdraws approval.
3. Only after the user agrees (or pre-authorized): `mw approve JOB --yes`.

## 4. Deliver

Final files live in `runs/JOB/`: `final.mp4`, `thumbnail.jpg`, `captions.srt`, `POSTS.md` (TikTok, X and LinkedIn posts, hashtags), `plan.json`. Report the paths, the logged spend (`mw spend`), and anything that used mock output.

## Failures

- `error` with a provider rejection: fix the cause (key, credits, input), then `mw retry JOB` (spends again — say so).
- "still running": `mw resume JOB` later; it only polls, never resubmits.
- "unclear whether the provider accepted": ask the user to check the provider dashboard before `mw retry JOB --force`.
- Budget errors: report them; don't raise caps without the user's say-so.

## Fresh-eyes score (from the Take One skill)

With `ANTHROPIC_API_KEY`, every finished short gets a reviewer report (`runs/JOB/review/REVIEW.md`): retell, seven axes, the three worst problems with times (mapped to shot numbers in the app). Report it as it is. A RETURN means fix the named shots (`mw redo`) and re-score (`mw review JOB`), at most three rounds; never call a RETURN a pass.

## Take One films

For a directed, studio-grade film use the Take One skill (`/take-one ...`). When it needs real-looking pictures, moving shots or a voice and the person has keys here, follow `TAKE-ONE.md` in this folder.

## Character swap specifics (Genjutsu)

- Enhancor Seedance needs `ENHANCOR_API_KEY` and a webhook: `./start.sh` auto-starts a callback-only cloudflared tunnel, or set `ENHANCOR_WEBHOOK_URL`. CLI-only runs need the app (or tunnel) running.
- Image reference → Seedance Edit; video identity reference → multi_reference (Omni). Draft first; the approved final completes the draft at 1080p via `draft_id`.
- The output always carries the source clip's untouched original audio. Clips over 30 s are trimmed.
- Genjutsu prep (`--prep genjutsu-depth|genjutsu-face-mesh|genjutsu-depth-mesh`, `--subject person`) runs the upstream Genjutsu preparation in `vendor/genjutsu` (install: `bash scripts/install-skills.sh --with-genjutsu-env`; needs `REPLICATE_API_TOKEN` and rubberband). Its rule is mandatory: watch the WHOLE prepared clip (`runs/JOB/genjutsu/`: mask, composite, prepared input), check hair, hands, clothing, edges, background spill and flicker (face tracking and pitched vocals for face mesh), and only then `mw approve JOB` (stage `mask`). If you cannot inspect video, ask the user to review it. A bad mask: `mw redo JOB prep` (withdraws all approvals).
- Already prepared elsewhere: pass Genjutsu's `seedance-input.mp4` with `--prepared --original untouched.mp4`.
- The upstream Genjutsu skill is also installed as `tein-video-workflow` for running Genjutsu on its own.
- Only swap people the user has the right to depict.
