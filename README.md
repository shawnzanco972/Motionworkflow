# MotionWorkflow

A local studio for making AI **images, videos, narrated short-form videos, and character swaps** — on the cheapest models that still look good, with a hard spending guard.

It's plug-and-play: it runs end-to-end **today with no API keys** (free images + offline placeholder media), and every real model switches on the moment you paste a key into Settings or `.env`.

## Built on two skills

- **[Genjutsu](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow)** — "your scene, new characters". Character Swap runs Genjutsu's own preparation (Demucs vocals pitched +3, colored depth, SAM 3 masks, or a face mesh), stops for its mandatory full-clip review, then sends the prepared clip to Seedance (draft → approved 1080p) and puts the complete original audio back on the result.
- **[Take One](https://github.com/talsiach/take-one)** — "a whole creative studio in one skill" for Claude Code. Use `/take-one` for directed, studio-grade films; it can use this app for cheap pictures, moving shots and voice ([how](.claude/skills/motionworkflow/TAKE-ONE.md)). Its craft is built into Short Maker: one takeaway, words written for one hearing at ~2 words/s, whole-line captions with the key word lit (muted viewers), no still held past ~4 s, image-to-video prompts that lock / move / ban, posts per platform, and a **fresh-eyes reviewer** that scores every finished short from frames alone (PASS only at 8+ on every axis).

`./setup.sh` fetches both at pinned commits into `.claude/skills/take-one` and `vendor/genjutsu` (`bash scripts/install-skills.sh` to refresh; add `--with-genjutsu-env` to build Genjutsu's own environment, which needs Python 3.12+ and `rubberband`). They're fetched rather than copied because their names, logos and media aren't covered by their licences. See [THIRD-PARTY.md](THIRD-PARTY.md).

## What you can make

| Page / command | What it does | Typical cost (budget tier) |
|---|---|---|
| **Presenter** · `mw presenter` | **You** talking to camera about any topic: Claude writes the script, it's spoken in **your cloned voice**, and **your photo or short video** is animated saying it, with captions, optional cutaways and posts | **~$0.77** per minute (your video, lip-synced) · **~$1.75** per 30 s (photo) |
| **Short Maker** · `mw short` | Idea → script → keyframes → voiceover → captions → finished 9:16 MP4 + post caption/hashtags | **~$0.08** for 5 narrated shots · **~$0.18** animated (budget) to ~$1.60 (standard) |
| **Image** · `mw image` | Text-to-image, batches, reference-image edits / consistent characters | **~$0.003** per image |
| **Video** · `mw video` | Text-to-video or animate a still; optional cheap draft → approved premium final | **~$0.02–0.25** per clip |
| **Character Swap** · `mw swap` | Replace the person in a clip with your character, keep the original audio; optional Genjutsu depth/SAM 3 or face-mesh prep | **~$0.80–1.20** for 10 s, draft + final (+~$0.30 Genjutsu prep) |
| **Voice** · `mw voice` | Voiceover from text (Kokoro, ElevenLabs) | **~$0.002** per line |

Costs are estimates from [`motionworkflow/models.json`](motionworkflow/models.json) and include the script and the reviewer where they apply; providers change prices often, so check their pages (see [docs/PROVIDERS.md](docs/PROVIDERS.md)). The app's **Price guide** (Spending page, or `mw prices`) recomputes this table from the catalog for every tier.

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

## The app

`./start.sh` opens a local studio at http://127.0.0.1:8770 with one page per service:

- **Home** — what's waiting for your approval, recent projects, a setup checklist and today's spend.
- **Create** — Presenter, Short Maker, Image, Video, Voiceover, Character Swap. Each page is a short numbered form with a live price on the right, and shows where it will stop for your approval.
- **Projects** — everything you've made: search, filter by status and type, and see what each cost. A project page plays the result, lets you approve the next step, edit and re-voice a single script line or redo a single shot, and shows the reviewer's score, the parts and the files. From its **⋯** menu: **Run again** (same inputs, new takes), **Edit as new** (the form, prefilled), **Download everything** (one zip). While it runs you can **Stop** it, and **Resume** later without paying twice.
- **Spending** — today / 7 / 30 days / all time, spend per day (chart or table), by service and by model, every charge and refund linked to its project, and the **Price guide**: what typical projects cost at each tier.
- **Avatars & voices** — save your face (a photo, or 10-20 s of video looking at the camera) and your voice (record it in the browser reading a short text, or upload a file) once, and reuse them everywhere. Each needs a "this is me / they agreed" confirmation; they stay in `library/` on your computer.
- **Settings** — API keys, budget limits and default tier, every model with its price, skill/tool status, light/dark theme.

It works on a phone-sized window too (menu drawer, sticky price bar), and tells you (a toast, and a count in the tab title) when a project needs your approval, finishes or fails.

## Pricing you can see

- **Before**: every form shows a live estimate, line by line, for the tier you pick; the Price guide compares tiers for typical projects; Home shows a "from" price on each service.
- **During**: each approval button shows what the next step costs (e.g. "Approve · $1.69"), and anything above your "ask me" amount needs a confirmation.
- **After**: each project has a cost card (spent vs estimate, per step, every charge and refund); project cards and the Projects list show spend; the Spending page adds it all up. The sidebar meter turns amber past 80% of today's budget.

## Your avatar and voice

The Presenter video is built in two paid stages so you never pay to animate a bad take:

1. **Script + voice** (cents): Claude writes a hook-first script for the length you pick (~2.3 words/s); each line is spoken in your cloned voice (Chatterbox or F5-TTS from your 10-20 s sample) or a stock voice. You listen, edit any line and **re-voice just that line**.
2. **Your avatar talks** (the expensive part, after you approve): a **photo** is animated by a talking-head model (Kling AI Avatar, VEED Fabric, OmniHuman), or **your own short video** is lip-synced to the new audio (Sync Lipsync; most lifelike and cheapest). Long scripts are split at line breaks to fit each model's limit, then joined.

Then captions, optional cutaway pictures on about one line in three, ducked music, `POSTS.md` and the fresh-eyes score. Only use your own face and voice, or someone's who agreed, and label AI-generated people when you post.

```bash
mw avatars add me.mp4 --name "Me, desk" --consent
mw voices add my-voice.m4a --name "My voice" --consent --transcript "what I say in it"
mw presenter "Why compound interest feels slow, then fast" --avatar <id> --voice-sample <id> --seconds 45
mw approve <job>      # after listening to the voice track
```

## Tiers

Pick **Cheapest / Budget / Standard / Premium** on any form ("Cheapest" uses free models where they exist). The app chooses the best model in that tier that you have a key for, falling back to cheaper tiers and finally to free/mock models so nothing breaks. You can also pick an exact model.

| Kind | Budget (default) | Standard | Premium |
|---|---|---|---|
| Image | FLUX schnell ~$0.003 | Nano Banana ~$0.039 | FLUX 1.1 pro ultra ~$0.06 |
| Image edit / character | Seedream 4 edit ~$0.03 | Nano Banana edit | FLUX Kontext pro |
| Text-to-video | LTX-Video ~$0.02/clip, Wan 2.5 ~$0.05/s | Seedance Lite, Kling 2.5 Turbo | Veo 3.1 Fast (with sound) |
| Image-to-video | LTX-Video, Wan 2.5 | Hailuo 02, Seedance Lite | Kling 2.5 Turbo, Veo 3.1 Fast |
| Voice | Kokoro ~$0.02/1k chars | Kokoro | ElevenLabs Turbo v2.5 |
| Swap | Wan 2.2 Animate Replace | Seedance 2.5 Edit (Enhancor) | Seedance 2.5 Edit |
| Voice clone | Chatterbox ~$0.025/1k chars | F5-TTS ~$0.05/1k chars | F5-TTS |
| Talking photo | Kling AI Avatar v2 Std ~$0.056/s | VEED Fabric ~$0.08/s | Kling Avatar Pro ~$0.115/s, OmniHuman 1.5 ~$0.16/s |
| Lip-sync your video | Sync Lipsync 1.9 ~$0.012/s | Sync Lipsync 2.0 ~$0.05/s | Sync Lipsync 2.0 |

## Money safety

- **Estimate first, always.** Every form shows a live cost estimate; the CLI prints it before running.
- **Caps.** `MW_MAX_COST_PER_JOB`, `MW_DAILY_BUDGET`, and a confirmation prompt above `MW_CONFIRM_ABOVE` (defaults $5 / $10 / $0.50).
- **Approval gates before the expensive part.** Animated shorts stop at the storyboard; drafts stop before the premium/1080p final. Editing or redoing anything withdraws the approval.
- **Never pays twice.** Request IDs are saved the moment a provider accepts them. Restarting resumes *collection*; a request whose outcome is unclear (timeout) is never auto-resubmitted — you check the provider dashboard and retry with `--force`.
- **Stop any time.** Stop sends nothing new; requests already sent may still finish (and be billed) and Resume collects them.
- **Settings are checked.** A budget typed as text, a negative or absurd amount, or an unknown tier is refused with a reason instead of being silently ignored.
- Rejected requests are refunded in the local ledger; the Spending page and `mw spend` show the totals. Your provider bill is the source of truth.

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
mw swap clip.mp4 --ref c.png --model enhancor:seedance-edit --prep genjutsu-depth   # Genjutsu prep + mask review
mw voice "Nobody suspects the pigeon." --voice af_heart
mw review <job>                                                       # fresh-eyes score (Claude)
mw --json image "..."                                                 # machine-readable, for agents / Take One
mw stop <job>                                                         # stop at the next checkpoint; mw resume <job> later
mw prices                                                             # price guide: typical projects × tiers
mw models --kind video        mw jobs        mw status <job>        mw spend
```

Add `--estimate` to any generation command to see the price without running it, `--yes` to skip the prompt.

## Use it from Claude Code

This repo ships a skill at [`.claude/skills/motionworkflow/SKILL.md`](.claude/skills/motionworkflow/SKILL.md) and agent rules in [AGENTS.md](AGENTS.md). Open the folder in Claude Code and ask, for example:

> Make me a funny 6-shot short about a cat who thinks he's a CEO, budget tier. Show me the script and storyboard before animating.

## Where things go

Each job is a folder in `runs/<job-id>/` with `job.json`, inputs, every model output, and the final files (`final.mp4`, `captions.srt`, `POSTS.md`, `thumbnail.jpg`, `plan.json`). `runs/ledger.jsonl` is the spend log. Both are git-ignored.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests     # offline: no keys, no network, no spend
```

The browser tests in `tests/test_browser.py` run when Playwright and Chromium are installed (`.venv/bin/pip install playwright && .venv/bin/playwright install chromium`); set `AXE_JS` to an `axe.min.js` to add an accessibility audit. See [CHANGELOG.md](CHANGELOG.md) for what changed and [docs/ROADMAP.md](docs/ROADMAP.md) for known limits and what's next.

## Responsible use

Only swap or depict real people with their permission, don't impersonate anyone, and label AI-generated or AI-edited content where platforms require it. Respect each model's license and content policy. Uploading to `tmpfiles`/`catbox` (used for Enhancor and very large files) makes that file public to anyone with the link.

More: [docs/PROVIDERS.md](docs/PROVIDERS.md) (keys, models, adding new ones) · [docs/PLAYBOOK.md](docs/PLAYBOOK.md) (cheap recipes, content ideas, monetization notes) · [AGENTS.md](AGENTS.md).

MIT licensed.
