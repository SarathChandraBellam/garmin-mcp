#!/usr/bin/env bash
# Install dependencies at the start of Claude Code on the web sessions so that
# black, ruff, mypy and pytest are ready to run. Local sessions are left alone.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
uv sync --locked --quiet
