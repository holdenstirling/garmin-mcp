#!/usr/bin/env bash
# Cloud Shell step 4: SSH to the VM and run the one-time Garmin and TrainingPeaks logins.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo garmin-mcp-login --user holden && sudo garmin-mcp-trainingpeaks-login --user holden" \
  -- -t
