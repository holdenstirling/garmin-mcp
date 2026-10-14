#!/usr/bin/env bash
# Re-run only the TrainingPeaks cookie login on the VM (e.g. when the cookie expires).
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo garmin-mcp-trainingpeaks-login --user holden" -- -t
