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

read -r -s -p "GitHub OAuth App client secret (hidden): " RAW; echo
# A GitHub OAuth client secret is one 40-character token. Pick it out of whatever was
# pasted (extra page text, spaces, line breaks); refuse anything else. Never echo it.
S=$(printf '%s' "$RAW" | python3 -c 'import re,sys
t=sys.stdin.read()
m=re.findall(r"(?<![0-9A-Za-z])[0-9a-f]{40}(?![0-9A-Za-z])",t) or re.findall(r"(?<!\S)\S{40}(?!\S)",t)
print(m[0] if len(set(m))==1 else "",end="")')
unset RAW
if [[ ${#S} -ne 40 ]]; then
  echo "That paste didn't contain exactly one 40-character client secret. Nothing was saved."
  echo "On the GitHub app page, generate a new secret and use the copy icon next to it."
  exit 1
fi
printf '%s' "$S" | gcloud secrets versions add garmin-mcp-github-client-secret \
  --project "$PROJECT" --data-file=- >/dev/null
unset S
echo "==> Saved client ID to infra/config.env and the secret to Secret Manager."
# If the server is already deployed, restart it so it loads the new secret.
if gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
     --command "test -f /etc/systemd/system/garmin-mcp.service && sudo systemctl restart garmin-mcp && echo restarted" \
     2>/dev/null | grep -q restarted; then
  echo "==> Restarted the server so it uses the new secret."
fi
