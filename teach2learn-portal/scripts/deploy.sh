#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
remote_host="${REMOTE_HOST:-}"
remote_dir="${REMOTE_DIR:-/data/scratch/sanyam_jain_2022/teach2learn-portal}"

if [[ -z "$remote_host" ]]; then
  echo "Set REMOTE_HOST, for example: REMOTE_HOST=user@server ./scripts/deploy.sh" >&2
  exit 2
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required on both machines." >&2
  exit 1
fi

echo "Additively syncing to ${remote_host}:${remote_dir}/"
rsync -azv --itemize-changes \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'deploy/oauth.env' \
  --exclude 'secrets/' \
  --exclude 'data/' \
  --exclude 'logs/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.DS_Store' \
  "$project_dir/" "${remote_host}:${remote_dir}/"

echo "Sync complete. No remote files were deleted and no service was restarted."
