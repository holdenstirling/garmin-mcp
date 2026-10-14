#!/usr/bin/env bash
# Show the MCP server's recent logs (default last 80 lines): bash infra/cloudshell/logs.sh [N]
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
N="${1:-80}"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo journalctl -u garmin-mcp -n $N --no-pager -o cat; echo ---; sudo grep -E '^(PUBLIC_BASE_URL|ALLOWED_GITHUB_USERS|GITHUB_CLIENT_ID|OAUTH_)' /etc/garmin-mcp/env"
