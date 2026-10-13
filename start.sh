#!/usr/bin/env bash
# Start the web app on http://127.0.0.1:8770 (PORT=8771 ./start.sh to change).
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/mw ] || bash setup.sh
exec .venv/bin/mw serve --port "${PORT:-8770}"
