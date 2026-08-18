#!/usr/bin/env bash
set -u
umask 077

readonly project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${project_dir}/logs"

while true; do
  "${project_dir}/scripts/run.sh" >> "${project_dir}/logs/portal.log" 2>&1
  sleep 5
done
