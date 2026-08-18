#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

set -a
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi
if [[ -f deploy/oauth.env ]]; then
  # shellcheck disable=SC1091
  source deploy/oauth.env
fi
set +a

exec python3 scripts/backup_to_relay.py
