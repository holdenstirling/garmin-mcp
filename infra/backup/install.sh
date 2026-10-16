#!/usr/bin/env bash
# Install / refresh the nightly off-server backup on the VM. Run ON the VM as root:
#   sudo BACKUP_BUCKET=<bucket> bash infra/backup/install.sh
# (infra/cloudshell/14-offsite-backups.sh does this over IAP; bootstrap-rabbit.sh re-runs it
# when /etc/rabbit-backup.env exists.) Idempotent. Only installs files under /usr/local/sbin,
# /etc/systemd/system and /etc/rabbit-backup.env; never touches the data directories.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
CONF=/etc/rabbit-backup.env
if [[ -n "${BACKUP_BUCKET:-}" ]]; then
  printf 'BACKUP_BUCKET=%s\n' "$BACKUP_BUCKET" > "$CONF.tmp"
  install -m 0644 -o root -g root "$CONF.tmp" "$CONF" && rm -f "$CONF.tmp"
fi
[[ -f "$CONF" ]] || { echo "set BACKUP_BUCKET (no $CONF yet)"; exit 2; }
for bin in curl openssl tar gzip python3; do
  command -v "$bin" >/dev/null || { echo "missing $bin"; exit 1; }
done
install -m 0755 -o root -g root "$SRC/rabbit-backup.sh" /usr/local/sbin/rabbit-backup
install -m 0644 "$SRC/rabbit-backup.service" /etc/systemd/system/rabbit-backup.service
install -m 0644 "$SRC/rabbit-backup.timer" /etc/systemd/system/rabbit-backup.timer
install -d -m 0700 -o root -g root /var/lib/rabbit-backup
systemctl daemon-reload
systemctl enable --now rabbit-backup.timer
echo "==> rabbit-backup.timer: $(systemctl show -p NextElapseUSecRealtime --value rabbit-backup.timer 2>/dev/null || echo scheduled)"
