#!/usr/bin/env bash
# Cloud Shell: connect a WHOOP developer app to Rabbit (optional).
# Before running: create an app at https://developer-dashboard.whoop.com (scopes: read:workout and offline)
# with your privacy policy URL https://rabbit.holdenottolini.com/app/privacy
# and redirect URL  https://rabbit.holdenottolini.com/app/auth/whoop/callback
# Until WHOOP approves the app, up to 10 WHOOP members can connect it.
# Asks for the client ID and the client secret (hidden). The secret goes to Secret Manager.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
read -r -p "WHOOP client ID: " CID
CID=$(printf '%s' "$CID" | tr -cd 'A-Za-z0-9_-')
[[ -n "$CID" ]] || { echo "No client ID. Nothing changed."; exit 1; }
read -r -s -p "WHOOP client secret (hidden): " SEC; echo
SEC=$(printf '%s' "$SEC" | tr -d '[:space:]')
[[ ${#SEC} -ge 16 ]] || { echo "That secret looks too short. Nothing changed."; exit 1; }
gcloud secrets describe garmin-mcp-whoop-client-secret --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud secrets create garmin-mcp-whoop-client-secret --project "$PROJECT" --replication-policy=automatic >/dev/null
printf '%s' "$SEC" | gcloud secrets versions add garmin-mcp-whoop-client-secret --project "$PROJECT" --data-file=- >/dev/null
unset SEC
SA=$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT" --format='value(serviceAccounts[0].email)')
gcloud secrets add-iam-policy-binding garmin-mcp-whoop-client-secret --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --condition=None >/dev/null
echo "==> Secret saved. Setting WHOOP_CLIENT_ID on the server and restarting Rabbit"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
  f=/etc/rabbit/env
  grep -q ^WHOOP_CLIENT_ID= \$f && sed -i \"s|^WHOOP_CLIENT_ID=.*|WHOOP_CLIENT_ID=$CID|\" \$f || echo WHOOP_CLIENT_ID=$CID >> \$f
  systemctl restart rabbit
  for i in \$(seq 1 60); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && { echo rabbit healthy; exit 0; }; sleep 1; done
  journalctl -u rabbit -n 30 --no-pager; exit 1'"
echo "==> Done. In Rabbit: Me > Connected apps > WHOOP > Connect."
