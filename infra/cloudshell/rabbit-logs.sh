#!/usr/bin/env bash
# Show Rabbit's recent logs (default last 60 lines): bash infra/cloudshell/rabbit-logs.sh [N]
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first (it writes infra/config.env)."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
N="${1:-60}"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo journalctl -u rabbit -n $N --no-pager -o cat"
