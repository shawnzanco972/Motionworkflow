#!/usr/bin/env bash
# Fetch the two upstream skills this project builds on, at pinned commits.
#
#   Take One  -> .claude/skills/take-one        (Claude Code skill: studio-style short films rendered from code)
#   Genjutsu  -> vendor/genjutsu                (depth + SAM 3 / face-mesh prep for Seedance character swap)
#                .claude/skills/tein-video-workflow -> its skill
#
# They are fetched rather than copied into this repo because their names, logos,
# artwork and example media are not covered by their MIT licences.
# Re-run any time; set TAKE_ONE_REF / GENJUTSU_REF to move to another commit.
# Add --with-genjutsu-env to also build Genjutsu's own Python environment.
set -euo pipefail
cd "$(dirname "$0")/.."

TAKE_ONE_URL="https://github.com/talsiach/take-one.git"
TAKE_ONE_REF="${TAKE_ONE_REF:-865556d72e7548e844e99c1ab8b1b0f8379f8369}"
GENJUTSU_URL="https://github.com/sirioberati/Genjustsu-Open-Source-Workflow.git"
GENJUTSU_REF="${GENJUTSU_REF:-40fd6615c2b7d940d4d7060e82de522292eefe99}"

fetch() { # url ref dir
  local url="$1" ref="$2" dir="$3"
  if [ ! -d "$dir/.git" ]; then
    mkdir -p "$(dirname "$dir")"
    git clone --quiet --filter=blob:none "$url" "$dir"
  fi
  git -C "$dir" fetch --quiet origin "$ref" 2>/dev/null || git -C "$dir" fetch --quiet origin
  git -C "$dir" -c advice.detachedHead=false checkout --quiet "$ref"
  echo "  $dir @ $(git -C "$dir" rev-parse --short HEAD)"
}

echo "Fetching skills:"
fetch "$TAKE_ONE_URL" "$TAKE_ONE_REF" .claude/skills/take-one
fetch "$GENJUTSU_URL" "$GENJUTSU_REF" vendor/genjutsu
ln -sfn ../../vendor/genjutsu/.agents/skills/tein-video-workflow .claude/skills/tein-video-workflow

if [ -f .claude/skills/take-one/package.json ] && command -v npm >/dev/null 2>&1; then
  (cd .claude/skills/take-one && npm install --silent --no-audit --no-fund >/dev/null 2>&1) \
    && echo "  take-one: node dependencies installed" \
    || echo "  take-one: npm install failed; run it inside .claude/skills/take-one"
fi

if [ "${1:-}" = "--with-genjutsu-env" ]; then
  echo "Building Genjutsu's environment (needs Python 3.12+ and rubberband):"
  (cd vendor/genjutsu && bash setup.sh) || echo "  Genjutsu setup did not finish; see vendor/genjutsu/docs/SETUP-AGENT.md"
fi

cat <<'EOF'

Done. In Claude Code (new session): /take-one ... for studio films, or ask for a Genjutsu swap.
Take One checks: bash .claude/skills/take-one/scripts/doctor.sh
Genjutsu prep in Character Swap needs: bash scripts/install-skills.sh --with-genjutsu-env
EOF
