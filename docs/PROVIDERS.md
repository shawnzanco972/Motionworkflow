# Providers, models and prices

All model knowledge lives in [`motionworkflow/models.json`](../motionworkflow/models.json). Code never hardcodes a model endpoint, so swapping in a newer or cheaper model is a data edit.

## Keys

| Provider | Env var | Get it | Unlocks |
|---|---|---|---|
| fal.ai | `FAL_KEY` | https://fal.ai/dashboard/keys | Most image, video, voice and swap models. Pay per output; failed generations aren't billed. |
| Replicate | `REPLICATE_API_TOKEN` | https://replicate.com/account/api-tokens | FLUX schnell, Nano Banana, Seedance Lite. Billed by compute time. |
| Enhancor | `ENHANCOR_API_KEY` | https://app.enhancor.ai/api-dashboard | Seedance 2.5 Edit / Omni character swap (the Genjutsu engine). Needs a webhook (cloudflared or `ENHANCOR_WEBHOOK_URL`). |
| Anthropic | `ANTHROPIC_API_KEY` | https://platform.claude.com/settings/keys | Claude writes Short Maker scripts as structured JSON. Budget/free tiers use `MW_PLANNER_MODEL_BUDGET` (Claude Haiku 5.5), others `MW_PLANNER_MODEL` (Claude Opus 5.5). |
| Pollinations | none | — | Free FLUX images (rate-limited, best effort). |
| Mock | none | — | Offline placeholder media so every workflow and test runs without keys. Disable with `MW_ALLOW_MOCK=0`. |

A configured key doesn't prove the account has credit. `mw doctor` only checks presence; nothing in setup makes a billed call.

## Prices are estimates

The `price` on each model is what the budget guard uses. Values were set in October 2026 from provider pages and public price lists and **will drift**. Before relying on a number, open the model's page on the provider and update it. Units:

- `image` per image · `megapixel` per output megapixel (fal rounds up) · `second` per output second · `video` per clip · `1k_chars` per 1,000 characters of text
- `by_resolution` overrides the rate per resolution (e.g. Wan 2.5: 480p / 720p / 1080p)

The Enhancor Seedance price is a placeholder ($0.10/s); set it to your actual rate.

## Override without editing the shipped file

Create `models.local.json` next to `.env` (git-ignored):

```json
{
  "models": [
    {"id": "enhancor:seedance-edit", "price": {"unit": "second", "usd": 0.06}},
    {"id": "fal:my-new-video", "name": "Some New Video Model", "provider": "fal",
     "endpoint": "fal-ai/some-new-model/image-to-video", "kind": "image_to_video", "tier": "budget",
     "price": {"unit": "second", "usd": 0.03},
     "inputs": {"prompt": "prompt", "image": "image_url", "duration": {"field": "duration", "type": "str"}},
     "durations": [5, 10]}
  ],
  "defaults": {"image_to_video": {"budget": ["fal:my-new-video", "fal:ltx-video-i2v"]}}
}
```

Entries with an existing `id` are merged field by field; new ids are added. `defaults` lists, per kind and tier, the models to try in order (the first one whose provider has a key wins).

## Mapping inputs

`inputs` maps MotionWorkflow's generic parameters to the provider's request fields:

| Generic | Meaning |
|---|---|
| `prompt`, `negative_prompt`, `seed` | text and seed |
| `image` / `images` | one / several input images (local files are uploaded or sent as data URIs automatically) |
| `video` | input video (swap) |
| `aspect_ratio` | `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `duration` | seconds, snapped to the model's `durations` (or `duration_range`) |
| `resolution` | one of the model's `resolutions` |
| `num_images`, `audio`, `text`, `voice` | batch size, generate sound, TTS text and voice |

A mapping can be a field name (`"image": "image_url"`) or an object: `{"field": "image_size", "map": {"16:9": "landscape_16_9"}}`, `{"field": "duration", "type": "str", "suffix": "s"}`. `fixed` adds constant fields to every request. If a provider answers 422, its field names changed: check the model's API page and fix `inputs`.

## Adding a provider

Subclass `providers.base.Provider` (`submit` returns a JSON-serialisable handle with `request_id`; `wait` polls; `collect` downloads), register it in `providers/__init__.py`, add its key to `config.KEYS`, and add models with `"provider": "<name>"`. `submit` must raise `RejectedError` when the provider refused (nothing billed) and `AmbiguousError` when it can't tell (timeout after sending).
