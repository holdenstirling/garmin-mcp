#!/usr/bin/env bash
# Cloud Shell: get rabbt ready for more people (about 50 to 100).
#   bash infra/cloudshell/18-more-users.sh            # e2-small (2 GB), about $13 a month
#   bash infra/cloudshell/18-more-users.sh e2-medium  # 4 GB, about $25 a month
# 1. Moves the server to a bigger machine (stop, resize, start: about 2 minutes offline).
# 2. Sets the AI caps in /etc/rabbit/env: 400k tokens per person per day and 20M for everyone
#    together per day (past that, coach chat pauses until tomorrow; plans keep working).
# Safe to run again. Nothing is deleted; the disk and its data stay as they are.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || infra/write-config.sh
# shellcheck disable=SC1091
source infra/config.env
TYPE=$(printf '%s' "${1:-e2-small}" | tr -cd 'a-z0-9-')
g() { gcloud --project "$PROJECT" --quiet "$@"; }

CUR=$(g compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(machineType.basename())')
if [[ "$CUR" == "$TYPE" ]]; then
  echo "==> Already on $TYPE"
else
  echo "==> Moving $VM_NAME from $CUR to $TYPE (rabbt is offline for about 2 minutes)"
  g compute instances stop "$VM_NAME" --zone "$ZONE"
  g compute instances set-machine-type "$VM_NAME" --zone "$ZONE" --machine-type "$TYPE"
  g compute instances start "$VM_NAME" --zone "$ZONE"
  echo "==> Waiting for the server to boot"
  for i in $(seq 1 30); do
    g compute ssh "$VM_NAME" --zone "$ZONE" --tunnel-through-iap --command true >/dev/null 2>&1 && break
    sleep 10
  done
fi

echo "==> Setting AI caps and checking rabbt is healthy"
g compute ssh "$VM_NAME" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
  f=/etc/rabbit/env
  set_kv() { grep -q ^\$1= \$f && sed -i \"s|^\$1=.*|\$1=\$2|\" \$f || echo \$1=\$2 >> \$f; }
  set_kv AGENT_DAILY_TOKEN_BUDGET 400000
  set_kv AGENT_GLOBAL_DAILY_TOKEN_BUDGET 20000000
  grep -E \"^AGENT_(DAILY_TOKEN_BUDGET|GLOBAL_DAILY_TOKEN_BUDGET)=\" \$f
  systemctl restart rabbit
  for i in \$(seq 1 90); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && { echo rabbit healthy; free -m | sed -n 1,2p; exit 0; }; sleep 1; done
  journalctl -u rabbit -n 30 --no-pager; exit 1'"

# Keep the saved config in step so later scripts and audits expect the new size.
sed -i "s/^MACHINE_TYPE=.*/MACHINE_TYPE=$TYPE/" infra/config.env
echo "==> Done. rabbt runs on $TYPE with AI caps set."
echo "    Next: in the Anthropic console, set a monthly spend limit (for example \$50) on rabbt's key."
echo "    Then in rabbt: Me > Invites and members > new invite link, 75 people, 30 days. Put that link in your story."
