#!/usr/bin/env bash
# Cloud Shell: move Rabbit (the /app web app) to its own hostname, e.g. rabbit.holdenottolini.com.
#   bash infra/cloudshell/11-domain.sh [rabbit.holdenottolini.com]
# The MCP server (/mcp, claude.ai connector, GitHub login) stays on the old sslip.io host,
# and /app on the old host redirects to the new one. Safe to re-run.
# Before running: an A record for the new name pointing at the VM's IP, and the new
# redirect URIs added (kept alongside the old ones) at Google Cloud and Oura (printed below).
set -uo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
APP_DOMAIN="${1:-${APP_DOMAIN:-rabbit.holdenottolini.com}}"
[[ "$APP_DOMAIN" =~ ^[a-z0-9.-]+$ ]] || { echo "Bad hostname: $APP_DOMAIN"; exit 1; }
IP=$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT" \
  --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
GOT=$(getent ahostsv4 "$APP_DOMAIN" | awk 'NR==1{print $1}')
if [[ "$GOT" != "$IP" ]]; then
  echo "!! $APP_DOMAIN resolves to '${GOT:-nothing}', not the VM ($IP). Fix DNS (or wait a minute) and re-run."
  exit 1
fi
echo "==> DNS ok: $APP_DOMAIN -> $IP"
cat <<MSG

Make sure these redirect URIs are added (keep the old ones too):
  Google Cloud console > APIs & Services > Credentials > Rabbit's OAuth client > Authorized redirect URIs:
     https://$APP_DOMAIN/app/auth/google/callback
  Oura developer portal (developer.ouraring.com) > your app > Redirect URIs:
     https://$APP_DOMAIN/app/auth/oura/callback

MSG
read -r -p "Added them? Switch Rabbit to https://$APP_DOMAIN now? [y/N] " OK
[[ "$OK" == y || "$OK" == Y ]] || { echo "Nothing changed."; exit 0; }

gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
  f=/etc/rabbit/env
  sed -i \"s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$APP_DOMAIN|\" \$f
  DOMAIN=$DOMAIN APP_DOMAIN=$APP_DOMAIN bash /opt/rabbit/current/infra/render-caddy.sh
  systemctl restart rabbit
  for i in \$(seq 1 60); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && { echo rabbit healthy; exit 0; }; sleep 1; done
  journalctl -u rabbit -n 30 --no-pager; exit 1'" || exit 1

sed -i '/^APP_DOMAIN=/d' infra/config.env && echo "APP_DOMAIN=$APP_DOMAIN" >> infra/config.env
echo "==> Waiting for HTTPS on $APP_DOMAIN (Caddy gets a certificate on first request)"
for i in $(seq 1 30); do
  if curl -fsS "https://$APP_DOMAIN/app/privacy" >/dev/null 2>&1; then
    echo "==> Done. Rabbit is at https://$APP_DOMAIN/app/"
    echo "    Old links (https://$DOMAIN/app/...) redirect there. Sign in again on the new address,"
    echo "    re-add Rabbit to your Home Screen from it, and turn notifications back on."
    exit 0
  fi
  sleep 3
done
echo "!! HTTPS not answering yet on $APP_DOMAIN. Check: curl -v https://$APP_DOMAIN/app/privacy"
exit 1
