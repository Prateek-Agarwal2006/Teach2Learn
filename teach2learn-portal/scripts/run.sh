#!/usr/bin/env bash
set -euo pipefail
umask 077

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

set -a
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi
if [[ -f deploy/oauth.env ]]; then
  # Deployment-specific OAuth locations contain no client secret; the secret
  # stays in the mode-600 JSON file referenced below.
  # shellcheck disable=SC1091
  source deploy/oauth.env
fi
set +a

# Adapter responses contain a private assessment and one public question.
# The streaming backend stops at that question; this cap prevents a malformed
# response from consuming an unnecessarily long decode slot.
export INFERENCE_MAX_NEW_TOKENS="${INFERENCE_MAX_NEW_TOKENS:-192}"

if [[ -n "${APP_PYTHON:-}" ]]; then
  python_cmd=("$APP_PYTHON" -m uvicorn)
else
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required when APP_PYTHON is not configured." >&2
    exit 1
  fi
  python_cmd=(uv run uvicorn)
fi

exec "${python_cmd[@]}" "${APP_MODULE:-app.main:app}" \
  --host "${APP_HOST:-127.0.0.1}" \
  --port "${APP_PORT:-8000}" \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --no-access-log \
  "$@"
