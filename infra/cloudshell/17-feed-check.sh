#!/usr/bin/env bash
# Cloud Shell: show why new workouts may not be reaching the feed. Read-only: prints the last day
# of rabbt's sync and sharing log lines (Garmin checks, new workouts found, auto-share decisions,
# errors). Nothing on the server is changed. Paste the output back to Claude.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -c '
  echo \"== rabbt status\"; systemctl is-active rabbit
  echo \"== sync and sharing, last 24h (newest last)\"
  journalctl -u rabbit --since \"24 hours ago\" --no-pager -o cat \
    | grep -E \"\\\"(poll|sync_new|sync_failed|poll_unexpected_error|reauth_nudge|connection_sync_failed|share_consent_skipped|share_check_failed|share_scan_failed|after_workouts_failed|sync_moments_failed|ext_workouts_import)\\\"\" \
    | tail -n 80
  echo \"== errors, last 24h\"
  journalctl -u rabbit --since \"24 hours ago\" --no-pager -p warning -o cat | tail -n 30
'"
