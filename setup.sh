#!/usr/bin/env bash
# One-time setup: virtualenv, dependencies, .env. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
[ -n "$PY" ] || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10+ is required (found $("$PY" --version))."; exit 1; }

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env - add your API keys there (or in the app's Settings tab)."
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo
  echo "ffmpeg is missing. Install it:  macOS: brew install ffmpeg   Ubuntu/WSL: sudo apt install ffmpeg"
  echo "(or: .venv/bin/pip install imageio-ffmpeg)"
fi
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Optional: install cloudflared for Enhancor character swap (brew install cloudflared)."
fi

echo
.venv/bin/mw doctor || true
echo
echo "Setup done. Start the app with:  ./start.sh"
