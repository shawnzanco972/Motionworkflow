# Using MotionWorkflow inside a Take One film

Take One (`.claude/skills/take-one`, installed by `scripts/install-skills.sh`) directs studio-style films rendered from code. Code draws type, motion, screens and illustration; a model is only needed for photoreal pictures, moving shots and voice. Take One reaches those services through a connector, the person's logged-in browser, or the person themselves (`references/services.md`). This repo adds a fourth way: **`mw`, with the person's own API keys, the cheapest models, a hard budget and a ledger.**

Take One's rules win where they apply: quote the real price and wait for a yes on that number, lock the story and the pictures before paying for movement, one render per shot, and keep `spend.md` in the film project. `mw` adds its own caps (`MW_MAX_COST_PER_JOB`, `MW_DAILY_BUDGET`) and never resubmits a paid request on its own.

## The services question at the pitch

Get prices from `mw` before asking (`--estimate` spends nothing), then ask Take One's one question with those numbers:

```bash
.venv/bin/mw --json image "PROMPT" --aspect 16:9 --tier standard --estimate
.venv/bin/mw --json video "PROMPT" --image approved-still.png --model fal:kling-25-turbo-i2v --duration 5 --estimate
.venv/bin/mw --json voice --text-file narration.txt --tier premium --estimate
```

Model prices in `models.json` are estimates. Take One says to read the real price: tell the person the number is a catalog estimate and point to the model's page, or check their provider dashboard.

## Pictures (Take One `real-shots.md`, Pictures)

```bash
.venv/bin/mw --json image "PROMPT" -n 1 --aspect 16:9 --tier standard --yes        # one, show it, then the set
.venv/bin/mw --json image "the exact same people ... PROMPT" --ref approved-people.png --aspect 16:9 --yes
.venv/bin/mw --json image "keep the product exactly as it is ...; change only the place ..." --ref product-clean.png --yes
```

- `--ref` routes to an edit model (Seedream / Nano Banana edit) that keeps a person or product consistent.
- Ask for free space where the type goes; never let a model draw a logo (place the real one in code).
- The JSON result lists each file's absolute `path`; copy it into the film's `assets/`.

## Moving shots (Take One `real-shots.md`, Moving shots)

Only after the picture cut works and the person has seen it. One render per shot, at the resolution it plays (a low-res draft is extra money, not a discount):

```bash
.venv/bin/mw --json video "The camera is held by hand and stays on this exact framing, a faint sway, no push, no pan. \
  She turns the page, in real time, already in motion from the first frame. Everyone stays exactly as they are. \
  No new objects, no hands entering, no text, no morphing, no flicker." \
  --image approved-still.png --model fal:kling-25-turbo-i2v --duration 5 --resolution 1080p --yes
```

Then bring it into the page with Take One's `scripts/clip.py`. Price more than one model first (`mw models --kind image_to_video`); a cheaper model at native 1080p can beat a dearer one at 720p.

## Voice (Take One `voice.md`)

```bash
.venv/bin/mw --json voice "Line one." --voice af_heart --tier budget --yes      # Kokoro, cheapest
.venv/bin/mw --json voice --text-file lines.txt --tier premium --yes            # ElevenLabs Turbo via fal
```

Cast from two or three short samples of the real lines and let the person pick by ear, then record the full script.

## Ledger

After each `mw` call, add a line to the film's `spend.md` (when, service = provider/model, what for, estimate from the JSON `spent_usd`). `mw spend` shows the total `mw` has logged today.

## When to use which

- **MotionWorkflow Short Maker** (`mw short`): a narrated vertical short in minutes for cents. Good for testing ideas and volume.
- **Take One** (`/take-one`): a directed film (brand, launch, music video, story) in one to two hours of Claude usage, with a reviewer loop. Uses `mw` for its paid assets when the person has keys here.
- **Genjutsu swap** (`mw swap --prep genjutsu-depth`): your scene, a new character, original audio kept.
