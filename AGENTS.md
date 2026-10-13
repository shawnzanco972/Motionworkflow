# Agent guide

Rules for any coding agent (Claude Code, Codex, …) operating MotionWorkflow for the user. The skill in `.claude/skills/motionworkflow/SKILL.md` has the step-by-step recipes.

## Setup requests

1. Run `./setup.sh`. It creates `.venv`, installs the package, and creates `.env` from `.env.example` only if `.env` is absent. Never overwrite an existing `.env`.
2. Ask the user to put keys into `.env` or the app's Settings tab themselves. Never ask for keys in chat, print them, or commit `.env`.
3. Verify with `.venv/bin/mw doctor` and `.venv/bin/python -m unittest discover -s tests`. Neither spends money.
4. Start the app with `./start.sh` (port 8770; `PORT=8771 ./start.sh` if busy) and report the URL.
5. Do not generate paid media during setup.

## Spending rules

- Always show the estimate first (`--estimate`), and get the user's go-ahead for anything above `MW_CONFIRM_ABOVE`. An explicit "go ahead, up to $X" counts; don't ask again within that scope.
- Never raise `MW_DAILY_BUDGET` / `MW_MAX_COST_PER_JOB` or pass `--yes` on the user's behalf beyond what they authorized.
- Approval gates (`storyboard`, `final`) belong to the user. Show them the storyboard / draft (paths are printed by `mw status`) and wait for approval unless they already said to proceed without review.
- Never resubmit to dodge a failure. `mw resume` only polls. `mw retry` resubmits failed steps (spends again). `mw retry --force` is only for steps whose outcome was unclear, and only after the user checked the provider dashboard.

## Creative rules

- Avatars and voices are personal biometric data. Add them only with the owner's confirmation (`--consent` means the person said this is them, or that the depicted person agreed); never clone someone's voice or face from a file the user found elsewhere. `library/` is git-ignored: never commit it.
- Presenter: show the script and let the user hear the voice track before approving the `voice` stage; to change a line, `mw redo JOB voice-N --shot N --text "new words"` (or edit it on the project page), which re-voices only that line and withdraws the approval.

- Show the script (`mw status <job>` prints shots) before animating.
- Keep characters consistent with `--character` (Short Maker) or `--ref` (Image).
- For Character Swap, use only people the user has the right to depict; image references use Seedance Edit, a video identity reference uses Seedance multi_reference (Omni). The final always carries the source's original audio.
- Look at outputs before calling them done. If a frame is wrong, `mw redo <job> key-N` (with `--shot N --visual ...` to change the prompt) instead of regenerating the whole job.

## Skills this project builds on

- **Take One** (`.claude/skills/take-one`): studio-style films rendered from code. Use it for directed films; it uses `mw` for paid pictures, moving shots and voice (see `.claude/skills/motionworkflow/TAKE-ONE.md`). Its craft rules are built into Short Maker (whole-line captions for muted viewers, about two words a second, one takeaway, no still held past ~4 s, image-to-video prompts that lock, move and ban, posts per platform, the fresh-eyes reviewer).
- **Genjutsu** (`vendor/genjutsu`, skill `tein-video-workflow`): depth + SAM 3 / face-mesh preparation for Seedance character swaps, with mandatory full-clip review. Character Swap runs it with `--prep`.
- Both are fetched by `scripts/install-skills.sh` at pinned commits (their names, logos and media are not ours to redistribute). Never copy their files into this repo.

## Code map

- `motionworkflow/models.json` — model catalog, tier defaults, price estimates. `models.local.json` overrides it.
- `motionworkflow/catalog.py` — tier resolution, param mapping, cost estimates.
- `motionworkflow/providers/` — fal, Replicate, Enhancor, Pollinations, Mock.
- `motionworkflow/workflows/common.py` — `generate()`: the only code path that spends money; idempotent per step.
- `motionworkflow/workflows/{image,video,short,swap,voice}.py` — the workflows.
- `motionworkflow/library.py` — saved avatars and voices (normalised once, consent recorded).
- `motionworkflow/workflows/presenter.py` — script → cloned voice per line → approval → talking head / lip-sync in chunks → cutaways, captions, posts, score.
- `motionworkflow/genjutsu.py` — runs Genjutsu's `workflow.py prepare` from `vendor/genjutsu`.
- `motionworkflow/reviewer.py` — Take One-style fresh-eyes review (frames + timed words only; PASS computed from the bar).
- `motionworkflow/media.py` — ffmpeg editing (Ken Burns, concat, mix/ducking, captions, audio restore).
- `motionworkflow/server.py` — local API. `static/` — the web app: `index.html` (shell + icon sprite), `app.css` (design tokens and components), `js/app.js` (router), `js/forms.js` (create-page engine), `js/services.js` (each service declared as data), `js/pages.js`, `js/modals.js`. No build step.
- `cli.py` — `mw` command.
- Tests in `tests/` run offline with the mock provider.
