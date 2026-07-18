#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ] || [ "$#" -ne 3 ]; then
  echo "usage: sudo install.sh SOURCE_ROOT GROK_LINUX_BINARY GIT_REPO_SSH_URL" >&2
  exit 2
fi

source_root="$1"
grok_binary="$2"
repo_url="$3"

test -f "$source_root/x_grok_reader/worker.py"
test -f "$source_root/config/queries.toml"
test -f "$grok_binary"
for command in findmnt git ssh ssh-keygen sudo python3 visudo systemctl; do
  command -v "$command" >/dev/null || {
    echo "required command is missing: $command" >&2
    exit 1
  }
done
case "$repo_url" in
  git@github.com:*/*.git) ;;
  *) echo "repository URL must be git@github.com:OWNER/REPO.git" >&2; exit 2 ;;
esac
if [ "$(findmnt -n -o FSTYPE /run)" != "tmpfs" ]; then
  echo "/run must be tmpfs; refusing to persist runtime content" >&2
  exit 1
fi

PYTHONPATH="$source_root" python3 - "$source_root/config/queries.toml" <<'PY'
import pathlib
import sys

from x_grok_reader.config import load_queries

if not load_queries(pathlib.Path(sys.argv[1])):
    raise SystemExit("enable at least one query before installing")
PY

grok_help="$("$grok_binary" --help)"
for flag in --always-approve --sandbox --json-schema --no-memory --no-subagents; do
  printf '%s\n' "$grok_help" | grep -F -- "$flag" >/dev/null || {
    echo "installed Grok Build does not support required flag: $flag" >&2
    exit 1
  }
done

getent group xreader >/dev/null || groupadd --system xreader
for user in xreader-worker xreader-grok xreader-submit; do
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "/var/lib/$user" \
      --shell /usr/sbin/nologin --gid xreader "$user"
  fi
done

install -d -o xreader-worker -g xreader -m 0770 /run/x-grok-reader
install -d -o root -g root -m 0755 /usr/local/lib/x-grok-reader
install -d -o root -g root -m 0755 /usr/local/lib/x-grok-reader/x_grok_reader
cp -R "$source_root/x_grok_reader/." /usr/local/lib/x-grok-reader/x_grok_reader/

install -d -o root -g root -m 0755 /usr/local/lib/x-grok-reader/grok-home
printf '%s\n' '[cli]' 'auto_update = false' \
  > /usr/local/lib/x-grok-reader/grok-home/config.toml
printf '%s\n' '[grok_com_config]' 'disable_api_key_auth = true' \
  > /usr/local/lib/x-grok-reader/grok-home/requirements.toml
chown -R root:root /usr/local/lib/x-grok-reader
find /usr/local/lib/x-grok-reader -type d -exec chmod 0755 {} +
find /usr/local/lib/x-grok-reader -type f -exec chmod 0644 {} +

install -o root -g root -m 0755 "$grok_binary" /usr/local/bin/grok
install -d -o root -g root -m 0755 /usr/local/libexec
for helper in \
  xreader-grok-login xreader-grok-search xreader-grok-search-as-user \
  xreader-ingest xreader-submit xreader-submit-as-user; do
  install -o root -g root -m 0755 \
    "$source_root/scripts/libexec/$helper" "/usr/local/libexec/$helper"
done

install -d -o root -g xreader -m 0750 /etc/x-grok-reader
install -o root -g xreader -m 0640 \
  "$source_root/config/queries.toml" /etc/x-grok-reader/queries.toml
printf '%s\n' "$repo_url" > /etc/x-grok-reader/repo-url
chown root:xreader /etc/x-grok-reader/repo-url
chmod 0640 /etc/x-grok-reader/repo-url

install -d -o xreader-grok -g xreader -m 0700 /var/lib/xreader-grok
install -d -o xreader-submit -g xreader -m 0700 /var/lib/xreader-submit/.ssh
if [ ! -f /var/lib/xreader-submit/.ssh/id_ed25519 ]; then
  sudo -u xreader-submit ssh-keygen -q -t ed25519 -N '' \
    -C xreader-hetzner-ingest \
    -f /var/lib/xreader-submit/.ssh/id_ed25519
fi

known_hosts_tmp="$(mktemp)"
python3 - "$known_hosts_tmp" <<'PY'
import json
import pathlib
import sys
import urllib.request

request = urllib.request.Request(
    "https://api.github.com/meta",
    headers={"Accept": "application/vnd.github+json", "User-Agent": "x-grok-reader"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)
keys = payload.get("ssh_keys")
if not isinstance(keys, list) or not keys:
    raise SystemExit("GitHub metadata returned no SSH host keys")
pathlib.Path(sys.argv[1]).write_text(
    "".join(f"github.com {key}\n" for key in keys),
    encoding="utf-8",
)
PY
install -o xreader-submit -g xreader -m 0600 \
  "$known_hosts_tmp" /var/lib/xreader-submit/.ssh/known_hosts
rm -f -- "$known_hosts_tmp"

install -o root -g root -m 0440 \
  "$source_root/scripts/xreader-sudoers" /etc/sudoers.d/xreader
visudo -cf /etc/sudoers.d/xreader

install -o root -g root -m 0644 \
  "$source_root/systemd/x-grok-reader.service" \
  /etc/systemd/system/x-grok-reader.service
install -o root -g root -m 0644 \
  "$source_root/systemd/x-grok-reader.timer" \
  /etc/systemd/system/x-grok-reader.timer
install -o root -g root -m 0644 \
  "$source_root/systemd/x-grok-reader.tmpfiles" \
  /etc/tmpfiles.d/x-grok-reader.conf
systemd-tmpfiles --create /etc/tmpfiles.d/x-grok-reader.conf
systemctl daemon-reload

echo "Deploy key for $repo_url:"
cat /var/lib/xreader-submit/.ssh/id_ed25519.pub
echo "Add it to only that repository with write access."
echo "Then authenticate Grok with:"
echo "sudo -u xreader-grok /usr/local/libexec/xreader-grok-login"
echo "Do not enable the timer until a manual run has published and cleaned up."
