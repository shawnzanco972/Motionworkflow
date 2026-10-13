# Roadmap and known limits

## Known limits (read before spending real money)

- **No real provider has been called from this code yet.** It was built in a sandbox without network access to fal, Replicate, Enhancor or Anthropic. Request and response handling follows each provider's documentation and is covered by offline tests with fake transports, but the first real run of each model is the real test. Start with one cheap job per model (an image, a 5 s clip, one voice line) and watch the provider dashboard.
- **Prices are estimates** taken from provider pages in October 2026 and stored in `motionworkflow/models.json`. Providers change prices often; fix any you find with a `models.local.json` override (see docs/PROVIDERS.md). The ledger logs the estimate at request time, not the bill.
- **Unverified model IDs.** `fal:omnihuman-15` (`fal-ai/bytedance/omnihuman/v1.5`) could not be confirmed; if fal rejects it, the request is refunded in the ledger and the step fails with the provider's message. Check `mw doctor` and the fal model page.
- **Voice cloning is strongest in English.** Chatterbox and F5-TTS clone other languages less faithfully; the script writer and captions handle other languages (including right-to-left) fine.
- **Long photo-avatar videos are the expensive path.** A 60 s Presenter with a photo is ~$3.44 on Budget, ~$4.89 on Standard. A 10-20 s video of you, lip-synced, does the same minute for ~$0.77.
- **Stop is a checkpoint, not a cancel at the provider.** Requests already sent finish (and are billed) at the provider; Resume collects them.
- **One computer, one person.** The app only listens on 127.0.0.1 and has no login. Don't expose it to a network.
- **Large uploads to Enhancor** go through a public temporary host (tmpfiles / catbox): anyone with the link can download that file until it expires.

## Next (most useful first)

1. **First real runs**: one cheap job per provider, then correct any response-shape or price differences in `models.json`.
2. **Real spend reconciliation**: read actual charges where providers expose them (fal and Replicate both report per-request cost or time) and show estimate vs actual per project.
3. **Templates**: save a project's settings as a reusable recipe ("my weekly finance tip": avatar, voice, tone, length, music) and start from it in one click.
4. **Batch**: a list of topics becomes a queue of Presenter or Short projects, each stopping at its approval gate, under one combined estimate.
5. **Publishing helpers**: export presets per platform (TikTok, Reels, Shorts, LinkedIn) with safe-zone checks and the matching `POSTS.md` text.
6. **More voices and languages**: per-language voice models in the catalog and a language picker that chooses them.
7. **Thumbnails**: generate and A/B a few cover frames from the finished video.
8. **Notifications outside the browser**: optional desktop notification or email when an approval is waiting.
