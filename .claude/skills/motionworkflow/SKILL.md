---
name: motionworkflow
description: Make AI images, videos, narrated short-form videos (TikTok/Reels/Shorts) and Genjutsu-style character swaps with this repo's `mw` CLI, on cheap models with cost estimates, budget caps and approval gates. Use when the user asks to generate, animate, script, caption or swap characters in media, or asks what it would cost.
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
| Narrated short, cheapest | `mw short "IDEA" --shots 6` (slideshow: keyframes + voice + captions) |
| Narrated short, AI motion | `mw short "IDEA" --mode animated --tier budget` → pauses at storyboard |
| Own script | `mw short --script-file script.txt` (lines: `narration \| visual \| motion`) |
| Consistent character | `--character face.png` (short) / `--ref face.png` (image) |
| Images | `mw image "PROMPT" -n 4 --aspect 9:16` |
| Video from text / still | `mw video "PROMPT"` / `mw video "MOTION" --image still.png` |
| Cheap draft then premium | `mw video "PROMPT" --final-tier premium` → pauses after draft |
| Character swap | `mw swap clip.mp4 --ref character.png [--prompt ...]` → pauses after draft |

Tiers: `--tier free|budget|standard|premium` (default from `MW_DEFAULT_TIER`). Pick an exact model with `--model ID` (see `mw models`).

## 3. Approval gates

When a job prints `awaiting_approval`:

1. `mw status JOB` — shows the shots and output paths. Look at the keyframes/draft (open the image or extract a frame with ffmpeg) and describe them to the user.
2. Fix weak shots cheaply: `mw redo JOB --shot N --visual "new prompt" key-N` (also `--narration`, `--motion`). Redo withdraws approval.
3. Only after the user agrees (or pre-authorized): `mw approve JOB --yes`.

## 4. Deliver

Final files live in `runs/JOB/`: `final.mp4`, `thumbnail.jpg`, `captions.srt`, `post.txt` (title, caption, hashtags), `plan.json`. Report the paths, the logged spend (`mw spend`), and anything that used mock output.

## Failures

- `error` with a provider rejection: fix the cause (key, credits, input), then `mw retry JOB` (spends again — say so).
- "still running": `mw resume JOB` later; it only polls, never resubmits.
- "unclear whether the provider accepted": ask the user to check the provider dashboard before `mw retry JOB --force`.
- Budget errors: report them; don't raise caps without the user's say-so.

## Character swap specifics (Genjutsu)

- Enhancor Seedance needs `ENHANCOR_API_KEY` and a webhook: `./start.sh` auto-starts a callback-only cloudflared tunnel, or set `ENHANCOR_WEBHOOK_URL`. CLI-only runs need the app (or tunnel) running.
- Image reference → Seedance Edit; video identity reference → multi_reference (Omni). Draft first; the approved final completes the draft at 1080p via `draft_id`.
- The output always carries the source clip's untouched original audio. Clips over 30 s are trimmed.
- For the full Genjutsu depth + SAM 3 mask prep, prepare with the upstream repo and pass its `seedance-input.mp4` with `--prepared --original untouched.mp4`.
- Only swap people the user has the right to depict.
