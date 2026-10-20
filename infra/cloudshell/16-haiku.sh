#!/usr/bin/env bash
# Cloud Shell: run every rabbt AI call on Claude Haiku (the lean setup, about 7x cheaper than Opus
# for daily notes and workout feedback). Sets AGENT_MODEL and AGENT_PROACTIVE_MODEL in
# /etc/rabbit/env on the server and restarts rabbt. Run again with a model name to change it, e.g.
#   bash infra/cloudshell/16-haiku.sh claude-sonnet-5-5
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || { echo "Run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
MODEL=$(printf '%s' "${1:-claude-haiku-5-5}" | tr -cd 'a-z0-9.-')
echo "==> Setting rabbt's AI model to $MODEL and restarting"
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "sudo bash -euo pipefail -c '
  f=/etc/rabbit/env
  for k in AGENT_MODEL AGENT_PROACTIVE_MODEL; do
    grep -q ^\$k= \$f && sed -i \"s|^\$k=.*|\$k=$MODEL|\" \$f || echo \$k=$MODEL >> \$f
  done
  grep -E \"^AGENT_(PROACTIVE_)?MODEL=\" \$f
  systemctl restart rabbit
  for i in \$(seq 1 60); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && { echo rabbit healthy; exit 0; }; sleep 1; done
  journalctl -u rabbit -n 30 --no-pager; exit 1'"
echo "==> Done. rabbt now uses $MODEL for chat, daily notes and workout feedback."
