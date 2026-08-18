#!/usr/bin/env bash
# Start the portal against .env.local. The production .env is never read here.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env.local ]]; then
  echo ".env.local is missing. Copy .env.example and set APP_ENV=development." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env.local
set +a

if [[ -x .venv/bin/python ]]; then
  python_cmd=(.venv/bin/python -m uvicorn)
elif command -v uv >/dev/null 2>&1; then
  python_cmd=(uv run uvicorn)
else
  echo "No .venv and no uv found. Run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

exec "${python_cmd[@]}" app.main:app \
  --host "${APP_HOST:-127.0.0.1}" \
  --port "${APP_PORT:-8000}" \
  "$@"
