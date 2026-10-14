#!/usr/bin/env bash
# Sanity-check the GitHub OAuth settings without revealing the secret.
set -uo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
echo "config.env client ID: [$GITHUB_CLIENT_ID]"
for v in $(gcloud secrets versions list garmin-mcp-github-client-secret --project "$PROJECT" \
            --format='value(name)' --filter='state=ENABLED'); do
  gcloud secrets versions access "$v" --secret garmin-mcp-github-client-secret --project "$PROJECT" |
    python3 infra/cloudshell/_secret_shape.py "secret version $v"
done
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo grep -E '^(GITHUB_CLIENT_ID|PUBLIC_BASE_URL)=' /etc/garmin-mcp/env" 2>/dev/null |
  sed 's/^/VM env: [/; s/$/]/'
