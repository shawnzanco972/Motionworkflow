# Changelog

## 0.3.0 — pricing you can see, project controls, hardening

**Pricing**
- Every project has a **cost card**: spent vs estimate, per step (numbered steps grouped), what the next approval costs, and every charge and refund. A cost pill sits in the project header; project cards show spend (and the estimate while unfinished).
- New **Spending** page: today / 7 / 30 days / all time, spend per day (bar chart with hover detail, or a table), by service, by model, and recent charges linked to their projects.
- **Price guide**: typical projects × quality tiers, priced from the catalog with real models even before you add keys, flagging anything over your per-project limit. Also `mw prices`.
- Home service cards show live "from" prices; the Presenter form suggests a video avatar when it would cost about a quarter as much as a photo.
- `mw spend` now prints today / 7 / 30 days / all time and the top models.
- The sidebar budget meter turns amber past 80% of today's budget and red when it's used up.

**Project controls**
- **Stop** a running project: nothing new is sent after Stop; requests already sent keep their saved handle and **Resume** collects them without paying twice. Works from the app or `mw stop` in another terminal.
- **Run again** (same inputs and settings, re-estimated and confirmed), **Edit as new** (the form prefilled with script, avatar, voice and tier) and **Download everything** (one zip).
- Projects: search, a Stopped filter, and the spend of the current view.
- Alerts when a project needs approval, finishes or fails (toast with a link, count in the tab title).
- A failure now offers the fix: add the missing key, open budget limits, or, when we can't tell whether the provider accepted a request, send it again with a clear warning.

**Hardening**
- Settings refuse values that can't work (text or NaN in a budget, negative amounts, an unknown tier, parallel outside 1-8) with a reason; a broken value in `.env` falls back to the safe default instead of disabling a limit.
- Fixed a project page that could stay on "Working" when a job finished within the same second as its last update.
- The package now ships `static/js` (a non-editable install had no app scripts).
- `/api/jobs` reads the spend ledger once for the whole list.
- 36 new tests (93 in total): bad numbers, text and files, odd caption text (braces, emoji, Hebrew), settings validation, bad ids and paths, double approve, edits and delete while running, the daily budget hit mid-run, one failed shot among several, restart resume, no mock and no keys, Stop at every point, duplicate and zip, the price guide. Plus a browser test (Playwright) with an optional axe accessibility audit.

**Changed defaults**
- "Free" tier is labelled **Cheapest**: it uses free models where they exist, but voices and avatars always cost a little.
- `MW_MAX_COST_PER_JOB` defaults to **$5** (was $3) so a 60 s Presenter video with a photo avatar (~$3.44) isn't refused out of the box. The daily budget stays $10 and anything over $0.50 still asks first. If you set your own value in `.env`, nothing changes for you.

## 0.2.0 — your face and voice, a multi-page studio

- **Presenter**: you talking about any topic, in your cloned voice, with your photo animated or your own short video lip-synced; script and voice are approved (and single lines re-voiced) before the expensive part.
- **Avatars & voices** library with consent, browser recording and clean reference clips.
- The app became a multi-page studio: Home, one page per service, Projects, project pages, Settings; light and dark themes; phone layout; zero axe violations.
- Every request is validated before a project exists (numbers, text limits, unreadable or empty files).

## 0.1.0 — first release

- Image, Video, Short Maker, Voiceover and Character Swap on cheap fal / Replicate / Enhancor models, with Free/Budget/Standard/Premium tiers and offline mock models.
- Money safety: estimates first, per-project and daily caps, approval gates, a spend ledger, and request handles saved so nothing is paid for twice.
- Genjutsu prep with its mask review gate; Take One's craft in Short Maker and its fresh-eyes reviewer.
