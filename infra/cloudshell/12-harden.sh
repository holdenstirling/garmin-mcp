#!/usr/bin/env bash
# Cloud Shell: fix what 9-audit.sh flags. Idempotent; each step is skipped when already done.
#   bash infra/cloudshell/12-harden.sh
#   BUDGET_USD=40 bash infra/cloudshell/12-harden.sh     (monthly budget, default 5)
#   ALERT_EMAIL=you@example.com ...                       (default: your gcloud account)
# 1. delete the GCP default firewall rule that opens RDP (3389) to the internet
# 2. turn on VM deletion protection
# 3. on the VM: cap the journal at 300 MB, turn off LLMNR/mDNS (the stray :5355 listener)
# 4. uptime checks (MCP /healthz, Rabbit /app/privacy) + one email alert when either is down
# 5. a monthly GCP budget with email alerts at 50 / 90 / 100 %
# Run 11-domain.sh first so the Rabbit uptime check targets the new address.
set -uo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "infra/config.env missing: run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
APP_HOST=${APP_DOMAIN:-$DOMAIN}
BUDGET_USD=${BUDGET_USD:-5}
ALERT_EMAIL=${ALERT_EMAIL:-$(gcloud config get-value account 2>/dev/null)}
g() { gcloud --project "$PROJECT" --quiet "$@"; }
ok() { echo "   ok: $*"; }
skip() { echo "   skip: $*"; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "==> 1. Firewall"
if g compute firewall-rules describe default-allow-rdp >/dev/null 2>&1; then
  g compute firewall-rules delete default-allow-rdp && ok "deleted default-allow-rdp (3389 open to 0.0.0.0/0)"
else skip "default-allow-rdp already gone"; fi

echo "==> 2. Deletion protection"
if [[ $(g compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(deletionProtection)') == True ]]; then
  skip "already on"
else
  g compute instances update "$VM_NAME" --zone "$ZONE" --deletion-protection && ok "on"
fi

echo "==> 3. VM: journal cap + no LLMNR"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
mkdir -p /etc/systemd/journald.conf.d /etc/systemd/resolved.conf.d
printf \"[Journal]\nSystemMaxUse=300M\n\" > /etc/systemd/journald.conf.d/rabbit-size.conf
printf \"[Resolve]\nLLMNR=no\nMulticastDNS=no\n\" > /etc/systemd/resolved.conf.d/rabbit-no-llmnr.conf
systemctl restart systemd-journald
systemctl is-active --quiet systemd-resolved && systemctl restart systemd-resolved || true
journalctl --vacuum-size=300M >/dev/null 2>&1 || true
echo \"   ok: journal \$(journalctl --disk-usage | grep -o \"[0-9.]*[KMG]\" | head -1), :5355 listeners: \$(ss -lntu | grep -c :5355 || true)\"
'" || echo "   WARN: VM step failed (IAP SSH); re-run later"

echo "==> 4. Uptime checks + alert (to $ALERT_EMAIL)"
g services enable monitoring.googleapis.com >/dev/null 2>&1 || true
add_uptime() {  # name host path
  if g monitoring uptime list-configs --format='value(displayName)' 2>/dev/null | grep -qxF "$1"; then
    skip "uptime check $1 exists"
  else
    g monitoring uptime create "$1" --resource-type=uptime-url \
      --resource-labels="host=$2,project_id=$PROJECT" --protocol=https --path="$3" \
      --period=5 --timeout=10 >/dev/null && ok "uptime check $1 -> https://$2$3"
  fi
}
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$APP_HOST/app/privacy" || true)
add_uptime "MCP server" "$DOMAIN" /healthz
if [[ "$code" == 200 ]]; then add_uptime "Rabbit app" "$APP_HOST" /app/privacy
else skip "Rabbit check: https://$APP_HOST/app/privacy -> $code (run 11-domain.sh, then re-run this)"; fi

CH=$(g beta monitoring channels list --format='value(name,labels.email_address)' 2>/dev/null | awk -v e="$ALERT_EMAIL" '$2==e{print $1; exit}')
if [[ -z "$CH" && -n "$ALERT_EMAIL" ]]; then
  CH=$(g beta monitoring channels create --display-name="Rabbit alerts" --type=email \
        --channel-labels="email_address=$ALERT_EMAIL" --format='value(name)' 2>/dev/null) && ok "email channel $ALERT_EMAIL"
fi
if g alpha monitoring policies list --filter='displayName="Rabbit or MCP down"' --format='value(name)' 2>/dev/null | grep -q .; then
  skip "alert policy exists"
elif [[ -n "$CH" ]]; then
  cat > "$TMP/policy.json" <<JSON
{"displayName": "Rabbit or MCP down", "combiner": "OR", "notificationChannels": ["$CH"],
 "documentation": {"mimeType": "text/markdown", "content": "Uptime check failing from 2+ regions for 10 min. Check: bash infra/cloudshell/9-audit.sh"},
 "conditions": [{"displayName": "uptime check failing",
   "conditionThreshold": {
     "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\"",
     "aggregations": [{"alignmentPeriod": "1200s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                       "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.host"]}],
     "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "600s",
     "trigger": {"count": 1}}}]}
JSON
  g alpha monitoring policies create --policy-from-file="$TMP/policy.json" >/dev/null && ok "alert policy: email when an uptime check fails 10 min"
else echo "   WARN: no email channel; alert policy not created"; fi

echo "==> 5. Budget (\$$BUDGET_USD / month)"
BA=$(g billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')
if [[ -z "$BA" ]]; then echo "   WARN: can't read the billing account; set a budget in the console (Billing > Budgets)"
else
  g services enable billingbudgets.googleapis.com >/dev/null 2>&1 || true
  if g billing budgets list --billing-account="$BA" --format='value(displayName)' 2>/dev/null | grep -qx "Rabbit monthly"; then
    skip "budget 'Rabbit monthly' exists"
  else
    g billing budgets create --billing-account="$BA" --display-name="Rabbit monthly" \
      --budget-amount="${BUDGET_USD}USD" --filter-projects="projects/$PROJECT" \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 >/dev/null \
      && ok "budget \$$BUDGET_USD/month, emails billing admins at 50/90/100%" \
      || echo "   WARN: budget create failed (needs Billing Account Administrator); set it in the console"
  fi
fi

echo
echo "Still manual (can't be scripted from here):"
echo " - Anthropic console > Limits: monthly spend limit + usage alert for the Rabbit key"
echo " - Google Auth Platform > Audience: Testing = 100 test users and Calendar re-connect every 7 days"
echo "Re-run: bash infra/cloudshell/9-audit.sh"
