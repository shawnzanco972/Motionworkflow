#!/usr/bin/env bash
# Start the app in the background inside a Codespace and print its address.
# --show only prints the address (and starts the app if it isn't running).
cd "$(dirname "$0")/.."
LOG=/tmp/motionworkflow.log
if ! curl -fs -o /dev/null http://127.0.0.1:8770/api/status 2>/dev/null; then
  setsid nohup bash start.sh > "$LOG" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    curl -fs -o /dev/null http://127.0.0.1:8770/api/status 2>/dev/null && break
    sleep 1
  done
fi
if [ -n "${CODESPACE_NAME:-}" ]; then
  URL="https://${CODESPACE_NAME}-8770.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}/"
else
  URL="http://127.0.0.1:8770/"
fi
echo
echo "  MotionWorkflow is running:  $URL"
echo "  (Log: $LOG)"
echo
