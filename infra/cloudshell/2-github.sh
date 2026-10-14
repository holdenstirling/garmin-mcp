#!/usr/bin/env bash
# Cloud Shell step 2: record the GitHub OAuth App's client ID, store its secret in Secret Manager.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env

read -r -p "GitHub OAuth App client ID: " CID
CID=$(printf '%s' "$CID" | tr -d '[:space:]')
[[ -n "$CID" ]] || { echo "client ID is required"; exit 1; }
sed -i "s/^GITHUB_CLIENT_ID=.*/GITHUB_CLIENT_ID=$CID/" infra/config.env

read -r -s -p "GitHub OAuth App client secret (hidden): " S; echo
[[ -n "$S" ]] || { echo "client secret is required"; exit 1; }
printf '%s' "$S" | gcloud secrets versions add garmin-mcp-github-client-secret \
  --project "$PROJECT" --data-file=- >/dev/null
unset S
echo "==> Saved client ID to infra/config.env and the secret to Secret Manager."
