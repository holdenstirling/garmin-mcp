#!/usr/bin/env bash
# Cloud Shell: connect an Oura developer app to Rabbit (optional).
# Before running: create an app at https://developer.ouraring.com (since Oct 2025 new apps can't be
# created on the old cloud.ouraring.com/oauth/applications page; it only edits existing ones)
# with redirect URI  https://rabbit.holdenottolini.com/app/auth/oura/callback
# Asks for the client ID and the client secret (hidden). The secret goes to Secret Manager.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
read -r -p "Oura client ID: " CID
CID=$(printf '%s' "$CID" | tr -cd 'A-Za-z0-9_-')
[[ -n "$CID" ]] || { echo "No client ID. Nothing changed."; exit 1; }
read -r -s -p "Oura client secret (hidden): " SEC; echo
SEC=$(printf '%s' "$SEC" | tr -d '[:space:]')
[[ ${#SEC} -ge 16 ]] || { echo "That secret looks too short. Nothing changed."; exit 1; }
gcloud secrets describe garmin-mcp-oura-client-secret --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud secrets create garmin-mcp-oura-client-secret --project "$PROJECT" --replication-policy=automatic >/dev/null
printf '%s' "$SEC" | gcloud secrets versions add garmin-mcp-oura-client-secret --project "$PROJECT" --data-file=- >/dev/null
unset SEC
SA=$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT" --format='value(serviceAccounts[0].email)')
gcloud secrets add-iam-policy-binding garmin-mcp-oura-client-secret --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --condition=None >/dev/null
echo "==> Secret saved. Setting OURA_CLIENT_ID on the server and restarting Rabbit"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
  f=/etc/rabbit/env
  grep -q ^OURA_CLIENT_ID= \$f && sed -i \"s|^OURA_CLIENT_ID=.*|OURA_CLIENT_ID=$CID|\" \$f || echo OURA_CLIENT_ID=$CID >> \$f
  systemctl restart rabbit
  for i in \$(seq 1 60); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && { echo rabbit healthy; exit 0; }; sleep 1; done
  journalctl -u rabbit -n 30 --no-pager; exit 1'"
echo "==> Done. In Rabbit: Settings > Oura > Connect."
