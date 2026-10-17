#!/usr/bin/env bash
# Cloud Shell: nightly OFF-SERVER backups of the app data to Cloud Storage (run once; idempotent).
#   bash infra/cloudshell/14-offsite-backups.sh
#   BACKUP_BUCKET=my-bucket RUN_NOW=0 bash infra/cloudshell/14-offsite-backups.sh
# In addition to the daily boot-disk snapshots (10-backups.sh), this survives losing the VM,
# its disk and its snapshots:
#   1. bucket gs://$PROJECT-rabbit-backups in $REGION: uniform bucket-level access, public access
#      prevention enforced, object versioning, lifecycle = daily/ kept 30 days, monthly/ kept
#      12 months, replaced (noncurrent) versions dropped after 7 days;
#   2. the VM's service account gets ONLY roles/storage.objectCreator on that bucket (add
#      objects; no read, list, overwrite or delete), and any other role it has there is removed;
#   3. over IAP SSH: installs infra/backup (rabbit-backup script + systemd timer, 08:20 UTC daily)
#      and, unless RUN_NOW=0, takes the first backup right away and shows it in the bucket.
# The archives hold the Fernet-encrypted data only. The Fernet keys stay in Secret Manager and
# are never uploaded: keep them (and an offline copy) or the backups can't be read.
# Restore: infra/restore-backup.md.
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ -f infra/config.env ]] || infra/write-config.sh  # a fresh clone: write the known settings
# shellcheck disable=SC1091
source infra/config.env

BUCKET=${BACKUP_BUCKET:-$PROJECT-rabbit-backups}
LOCATION=${BACKUP_LOCATION:-$REGION}
RUN_NOW=${RUN_NOW:-1}
g() { gcloud --project "$PROJECT" --quiet "$@"; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "==> Cloud Storage API"
g services enable storage.googleapis.com >/dev/null

VM_SA=$(g compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(serviceAccounts[0].email)')
[[ -n "$VM_SA" ]] || { echo "VM $VM_NAME has no service account"; exit 1; }
echo "==> VM service account: $VM_SA"

echo "==> Bucket gs://$BUCKET ($LOCATION)"
if g storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "   exists"
else
  g storage buckets create "gs://$BUCKET" --location="$LOCATION" --default-storage-class=STANDARD \
    --uniform-bucket-level-access --public-access-prevention
fi

cat >"$TMP/lifecycle.json" <<'JSON'
{
  "lifecycle": {
    "rule": [
      {"action": {"type": "Delete"}, "condition": {"age": 31, "matchesPrefix": ["daily/"]}},
      {"action": {"type": "Delete"}, "condition": {"age": 366, "matchesPrefix": ["monthly/"]}},
      {"action": {"type": "Delete"}, "condition": {"isLive": false, "daysSinceNoncurrentTime": 7}}
    ]
  }
}
JSON
# Re-applied every run so the settings can't drift.
g storage buckets update "gs://$BUCKET" --uniform-bucket-level-access --public-access-prevention \
  --versioning --lifecycle-file="$TMP/lifecycle.json" >/dev/null
g storage buckets describe "gs://$BUCKET" --format=json >"$TMP/bucket.json"
python3 - "$TMP/bucket.json" <<'PY'
import json, sys
b = json.load(open(sys.argv[1]))
ubla = (b.get("uniform_bucket_level_access") or b.get("iamConfiguration", {}).get("uniformBucketLevelAccess", {}).get("enabled"))
pap = b.get("public_access_prevention") or b.get("iamConfiguration", {}).get("publicAccessPrevention")
ver = b.get("versioning_enabled", (b.get("versioning") or {}).get("enabled"))
rules = b.get("lifecycle_config", b.get("lifecycle", {})).get("rule", [])
print(f"   uniform access: {ubla}, public access prevention: {pap}, versioning: {ver}, lifecycle rules: {len(rules)}")
PY

echo "==> IAM: $VM_SA may only create objects in gs://$BUCKET"
g storage buckets get-iam-policy "gs://$BUCKET" --format=json >"$TMP/policy.json"
python3 - "$TMP/policy.json" "serviceAccount:$VM_SA" >"$TMP/extra-roles" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
for b in p.get("bindings", []):
    if sys.argv[2] in b.get("members", []) and b["role"] != "roles/storage.objectCreator":
        print(b["role"])
PY
while read -r role; do
  [[ -n "$role" ]] || continue
  echo "   removing $role from $VM_SA"
  g storage buckets remove-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$VM_SA" --role="$role" >/dev/null
done <"$TMP/extra-roles"
g storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$VM_SA" \
  --role=roles/storage.objectCreator >/dev/null
echo "   ok: roles/storage.objectCreator"
proj_roles=$(g projects get-iam-policy "$PROJECT" --flatten='bindings[].members' \
  --filter="bindings.members:serviceAccount:$VM_SA" --format='value(bindings.role)' 2>/dev/null |
  grep -E 'roles/(owner|editor|storage\.)' || true)
[[ -z "$proj_roles" ]] || echo "   WARN: project-level roles also reach the bucket: $proj_roles"

echo "==> Installing the nightly backup on $VM_NAME (IAP SSH)"
tar -czf "$TMP/backup-kit.tgz" -C infra backup
gcloud compute scp "$TMP/backup-kit.tgz" "$VM_NAME:/tmp/rabbit-backup-kit.tgz" \
  --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --quiet
# shellcheck disable=SC2016  # expanded on the VM
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --quiet \
  --command "sudo env BACKUP_BUCKET='$BUCKET' RUN_NOW='$RUN_NOW' bash -euo pipefail -c '
    D=\$(mktemp -d); tar -xzf /tmp/rabbit-backup-kit.tgz -C \"\$D\"; rm -f /tmp/rabbit-backup-kit.tgz
    bash \"\$D/backup/install.sh\"; rm -rf \"\$D\"
    if [[ \"\$RUN_NOW\" == 1 ]]; then
      echo \"==> First backup now (a minute or two)\"
      systemctl start rabbit-backup.service || true
      journalctl -u rabbit-backup.service -n 8 --no-pager -o cat
      cat /var/lib/rabbit-backup/last-success 2>/dev/null || echo \"!! no successful backup yet\"
    fi'"

echo
echo "==> Newest backups in gs://$BUCKET"
g storage ls -l "gs://$BUCKET/daily/**" 2>/dev/null | sort -k2 | tail -5 || echo "   (none yet)"
echo "Nightly at ~08:20 UTC. Check with: bash infra/cloudshell/9-audit.sh   Restore: infra/restore-backup.md"
