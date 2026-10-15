# Run MotionWorkflow from your phone

The app runs in a **GitHub Codespace**: a small computer in the cloud that GitHub starts for you. You use it from your phone's browser. Free GitHub accounts include enough Codespace hours each month for this (it stops by itself after 30 minutes of inactivity, so it doesn't use them up).

## Start it (first time ~3-5 minutes)

1. In your phone's browser (Safari or Chrome, signed in to github.com), open:
   **https://codespaces.new/shawnzanco972/Motionworkflow**
   Pick the branch with the app if asked, then tap **Create codespace**.
2. Wait while it installs (Python, ffmpeg, the app). An editor opens; ignore it.
3. When it's ready, the app opens in a new tab. If your browser blocked that, open the **Ports** tab in the editor's bottom panel (or the ☰ menu → Terminal → Ports) and tap the 🌐 globe next to **MotionWorkflow (8770)**. The terminal also prints the address, like `https://<name>-8770.app.github.dev/`.
4. Add it to your home screen (Share → Add to Home Screen) for one-tap access next time.

The address is private: only you, signed in to GitHub, can open it.

## Next time

Open https://github.com/codespaces, tap your MotionWorkflow codespace to wake it, and the app starts by itself. Your projects, avatars and voices are kept in the codespace until you delete it.

## Add your keys

In the app: **Settings → API keys**, paste your fal.ai key (and Claude key). Or, so they survive deleting the codespace, add them once as **Codespaces secrets** at https://github.com/settings/codespaces (names `FAL_KEY`, `ANTHROPIC_API_KEY`), allowed for this repository.

## Tips on a phone

- **Avatar**: on Avatars & voices, tap Add avatar and choose *Take Photo / Video* to use your camera. A 10-20 s video of you looking at the camera gives the best (and cheapest) Presenter videos.
- **Voice**: Add voice → Record. Allow the microphone, read the text shown for ~20 seconds in a quiet room.
- **Downloads**: on a finished project tap Download, then Share → Save Video.
- If the page says the server can't be reached, the codespace went to sleep: open https://github.com/codespaces and tap it.
