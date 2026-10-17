#!/usr/bin/env bash
# Cloud Shell: daily snapshots of the VM's boot disk (all app data lives on it).
#   bash infra/cloudshell/10-backups.sh            create + attach the schedule (idempotent)
#   SNAPSHOT_NOW=1 bash infra/cloudshell/10-backups.sh   also take one snapshot right away
# Creates resource policy "garmin-mcp-daily" (daily 09:00 UTC, 14-day retention, snapshots kept
# if the disk is deleted) in $REGION and attaches it to the boot disk. No-op when already attached.
# Restore: create a disk from a snapshot, then a VM from that disk (docs/SETUP_AUDIT.md).
# Snapshots hold the Fernet-encrypted data only; the keys live in Secret Manager, so never
# destroy the garmin-mcp-fernet-key / garmin-mcp-rabbit-fernet-key secret versions.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || infra/write-config.sh  # a fresh clone: write the known settings
# shellcheck disable=SC1091
source infra/config.env

POLICY=garmin-mcp-daily
RETENTION_DAYS=14
START_UTC=09:00
g() { gcloud --project "$PROJECT" --quiet "$@"; }

DISK=$(g compute instances describe "$VM_NAME" --zone "$ZONE" --format=json |
  python3 -c 'import json,sys
d=json.load(sys.stdin)
print(next(x["source"].rsplit("/",1)[-1] for x in d["disks"] if x.get("boot")))')
echo "==> Boot disk: $DISK ($ZONE)"

if g compute resource-policies describe "$POLICY" --region "$REGION" >/dev/null 2>&1; then
  read -r days start < <(g compute resource-policies describe "$POLICY" --region "$REGION" \
    --format='value(snapshotSchedulePolicy.retentionPolicy.maxRetentionDays,snapshotSchedulePolicy.schedule.dailySchedule.startTime)')
  echo "==> Policy $POLICY exists (retention ${days:-?}d, daily ${start:-?} UTC)"
  if [[ "${days:-}" != "$RETENTION_DAYS" || "${start:-}" != "$START_UTC" ]]; then
    echo "   note: differs from ${RETENTION_DAYS}d / $START_UTC; left unchanged (a policy in use can't be edited;"
    echo "   detach it, delete it, and re-run this script to recreate)."
  fi
else
  echo "==> Creating snapshot schedule $POLICY in $REGION (daily $START_UTC UTC, ${RETENTION_DAYS}-day retention)"
  g compute resource-policies create snapshot-schedule "$POLICY" \
    --region "$REGION" \
    --description "Daily boot-disk snapshots for $VM_NAME" \
    --daily-schedule --start-time "$START_UTC" \
    --max-retention-days "$RETENTION_DAYS" \
    --on-source-disk-delete keep-auto-snapshots
fi

ATTACHED=$(g compute disks describe "$DISK" --zone "$ZONE" --format='value(resourcePolicies)' |
  tr ';,' '\n\n' | sed 's|.*/||' | grep -v '^$' || true)
if grep -qx "$POLICY" <<<"$ATTACHED"; then
  echo "==> Already attached to $DISK: nothing to do"
else
  if [[ -n "$ATTACHED" ]]; then
    echo "==> Other policies on $DISK: $(tr '\n' ' ' <<<"$ATTACHED")"
    echo "   (a disk can have only one snapshot schedule; if attaching fails, detach the other one:"
    echo "    gcloud compute disks remove-resource-policies $DISK --zone $ZONE --resource-policies <name>)"
  fi
  echo "==> Attaching $POLICY to $DISK"
  g compute disks add-resource-policies "$DISK" --zone "$ZONE" --resource-policies "$POLICY"
fi

if [[ "${SNAPSHOT_NOW:-}" == 1 ]]; then
  NAME="$DISK-manual-$(date -u +%Y%m%d-%H%M%S)"
  echo "==> Taking snapshot $NAME now (manual snapshots are not auto-deleted)"
  g compute disks snapshot "$DISK" --zone "$ZONE" --snapshot-names "$NAME"
fi

echo
echo "==> Snapshots of $DISK:"
g compute snapshots list --filter="sourceDisk~/disks/$DISK\$" --sort-by=~creationTimestamp \
  --format='table(name,creationTimestamp,diskSizeGb,storageBytes.size(units_out=M):label=STORED_MB,status)' || true
echo "First scheduled snapshot runs at the next $START_UTC UTC window."
