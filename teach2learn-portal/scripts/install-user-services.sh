#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly service_dir="${project_dir}/deploy/user"

if [[ "$(loginctl show-user "${USER}" -p Linger --value)" != "yes" ]]; then
  echo "User lingering is disabled. Run: loginctl enable-linger ${USER}" >&2
  exit 3
fi

mkdir -p "${HOME}/.config/systemd/user"
install -m 0644 "${service_dir}/teach2learn-vllm.service" "${HOME}/.config/systemd/user/teach2learn-vllm.service"
install -m 0644 "${service_dir}/teach2learn-portal.service" "${HOME}/.config/systemd/user/teach2learn-portal.service"
systemctl --user daemon-reload
systemctl --user enable teach2learn-vllm.service teach2learn-portal.service

echo "Installed and enabled EquitableT2L user services."
echo "Start them with: systemctl --user start teach2learn-vllm.service teach2learn-portal.service"
