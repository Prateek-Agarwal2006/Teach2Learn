#!/usr/bin/env bash
set -u
umask 077

readonly project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${project_dir}/logs"

run_loop() {
  local profile="$1"
  while true; do
    "${project_dir}/scripts/run-vllm-engine.sh" "$profile" >> "${project_dir}/logs/vllm-${profile}.log" 2>&1
    sleep 5
  done
}

wait_for_engine() {
  local port="$1"
  local attempt
  for attempt in {1..240}; do
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
      exec 3>&-
      exec 3<&-
      return 0
    fi
    sleep 1
  done
  return 1
}

# CUDA graph capture is intentionally staggered. Starting five captures at
# once creates avoidable CPU, disk, and shared-GPU contention after a reboot.
for entry in "gemma2:18102" "mistral:18103" "granite:18104" "qwen3:18101" "qwen2.5:18105"; do
  profile="${entry%%:*}"
  port="${entry##*:}"
  run_loop "$profile" &
  wait_for_engine "$port" || true
done
wait
