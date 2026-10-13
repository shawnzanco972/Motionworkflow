# MotionWorkflow

A local studio for making AI **images, videos, narrated short-form videos, and character swaps** — on the cheapest models that still look good, with a hard spending guard.

It's plug-and-play: it runs end-to-end **today with no API keys** (free images + offline placeholder media), and every real model switches on the moment you paste a key into Settings or `.env`.

Inspired by and partly adapted from the [Genjutsu Open Source Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow) (MIT): its Seedance character swap, draft → approve → 1080p flow, no-duplicate-billing recovery, and original-audio restoration are built in. See [THIRD-PARTY.md](THIRD-PARTY.md).

## What you can make

| Tab / command | What it does | Typical cost (budget tier) |
|---|---|---|
| **Short Maker** · `mw short` | Idea → script → keyframes → voiceover → captions → finished 9:16 MP4 + post caption/hashtags | **~$0.03** for 6 narrated slideshow shots · **~$0.15–1.50** animated |
| **Image** · `mw image` | Text-to-image, batches, reference-image edits / consistent characters | **~$0.003** per image |
| **Video** · `mw video` | Text-to-video or animate a still; optional cheap draft → approved premium final | **~$0.02–0.25** per clip |
| **Character Swap** · `mw swap` | Replace the person in a clip with your character, keep the original audio (Genjutsu-style) | **~$0.20–0.50** draft for 5 s |

Costs are estimates from [`motionworkflow/models.json`](motionworkflow/models.json); providers change prices often, so check their pages (see [docs/PROVIDERS.md](docs/PROVIDERS.md)).

## Quick start

Needs Python 3.10+ and ffmpeg (`brew install ffmpeg` / `sudo apt install ffmpeg`).

```bash
git clone https://github.com/shawnzanco972/Motionworkflow.git
cd Motionworkflow
./setup.sh          # venv, dependencies, creates .env
./start.sh          # open http://127.0.0.1:8770
```

Windows: use WSL2 and the commands above, or double-click `start.bat` (needs Python and ffmpeg on PATH).

### Add keys when you have them

Open **Settings** in the app (or edit `.env`). One key goes a long way:

1. **`FAL_KEY`** ([fal.ai](https://fal.ai/dashboard/keys)) — unlocks the cheap image, video, voice and swap models. Start here.
2. **`ANTHROPIC_API_KEY`** ([Claude](https://platform.claude.com/settings/keys)) — Claude writes your short scripts (hook, shots, narration, caption, hashtags). Without it a built-in template or your own script is used.
3. `REPLICATE_API_TOKEN` — alternative catalog (optional).
4. `ENHANCOR_API_KEY` — Seedance 2.5 character swap, the Genjutsu engine (optional; also install `cloudflared`).

Run `.venv/bin/mw doctor` to see which models each tier will use with your keys.

## Tiers

Pick **Free / Budget / Standard / Premium** on any form. The app chooses the best model in that tier that you have a key for, falling back to cheaper tiers and finally to free/mock models so nothing breaks. You can also pick an exact model.

| Kind | Budget (default) | Standard | Premium |
|---|---|---|---|
| Image | FLUX schnell ~$0.003 | Nano Banana ~$0.039 | FLUX 1.1 pro ultra ~$0.06 |
| Image edit / character | Seedream 4 edit ~$0.03 | Nano Banana edit | FLUX Kontext pro |
| Text-to-video | LTX-Video ~$0.02/clip, Wan 2.5 ~$0.05/s | Seedance Lite, Kling 2.5 Turbo | Veo 3.1 Fast (with sound) |
| Image-to-video | LTX-Video, Wan 2.5 | Hailuo 02, Seedance Lite | Kling 2.5 Turbo, Veo 3.1 Fast |
| Voice | Kokoro ~$0.02/1k chars | Kokoro | ElevenLabs Turbo v2.5 |
| Swap | Wan 2.2 Animate Replace | Seedance 2.5 Edit (Enhancor) | Seedance 2.5 Edit |

## Money safety

- **Estimate first, always.** Every form shows a live cost estimate; the CLI prints it before running.
- **Caps.** `MW_MAX_COST_PER_JOB`, `MW_DAILY_BUDGET`, and a confirmation prompt above `MW_CONFIRM_ABOVE` (defaults $3 / $10 / $0.50).
- **Approval gates before the expensive part.** Animated shorts stop at the storyboard; drafts stop before the premium/1080p final. Editing or redoing anything withdraws the approval.
- **Never pays twice.** Request IDs are saved the moment a provider accepts them. Restarting resumes *collection*; a request whose outcome is unclear (timeout) is never auto-resubmitted — you check the provider dashboard and retry with `--force`.
- Rejected requests are refunded in the local ledger; `mw spend` shows the totals. Your provider bill is the source of truth.

## CLI

```bash
mw short "A pigeon who secretly runs a hedge fund" --shots 6          # slideshow, ~$0.03
mw short "Grandma becomes a DJ" --mode animated --tier budget         # pauses at storyboard
mw approve <job>                                                      # animate it
mw redo <job> --shot 2 --visual "grandma crowd-surfing" key-2         # fix one shot
mw image "corgi giving a TED talk" -n 4 --aspect 9:16
mw image "same dog, now in space" --ref dog.png
mw video "raccoon DJ, neon rooftop" --final-tier premium              # cheap draft, then approve
mw video "slow push-in, wind in hair" --image portrait.png
mw swap clip.mp4 --ref character.png                                  # draft, then: mw approve <job>
mw models --kind video        mw jobs        mw status <job>        mw spend
```

Add `--estimate` to any generation command to see the price without running it, `--yes` to skip the prompt.

## Use it from Claude Code

This repo ships a skill at [`.claude/skills/motionworkflow/SKILL.md`](.claude/skills/motionworkflow/SKILL.md) and agent rules in [AGENTS.md](AGENTS.md). Open the folder in Claude Code and ask, for example:

> Make me a funny 6-shot short about a cat who thinks he's a CEO, budget tier. Show me the script and storyboard before animating.

## Where things go

Each job is a folder in `runs/<job-id>/` with `job.json`, inputs, every model output, and the final files (`final.mp4`, `captions.srt`, `post.txt`, `thumbnail.jpg`, `plan.json`). `runs/ledger.jsonl` is the spend log. Both are git-ignored.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests     # offline: no keys, no network, no spend
```

## Responsible use

Only swap or depict real people with their permission, don't impersonate anyone, and label AI-generated or AI-edited content where platforms require it. Respect each model's license and content policy. Uploading to `tmpfiles`/`catbox` (used for Enhancor and very large files) makes that file public to anyone with the link.

More: [docs/PROVIDERS.md](docs/PROVIDERS.md) (keys, models, adding new ones) · [docs/PLAYBOOK.md](docs/PLAYBOOK.md) (cheap recipes, content ideas, monetization notes) · [AGENTS.md](AGENTS.md).

MIT licensed.
