#!/usr/bin/env bash
# Cloud Shell, run ONCE: let GitHub Actions deploy Rabbit on every push to main, with no
# stored keys. GitHub proves "this is holdenstirling/garmin-mcp on main" with a short-lived
# OIDC token; Google trades it for a short-lived token of a deploy-only service account.
# Idempotent: safe to re-run.
#
# The deploy account can only: see the VM, SSH to it through IAP (OS Login, sudo), and act as
# the VM's own service account (required for OS Login on a VM that runs as one). It can't read
# secrets, change IAM, create VMs or touch anything else.
set -euo pipefail
cd "$(dirname "$0")/../.."
infra/write-config.sh
# shellcheck disable=SC1091
source infra/config.env
g() { gcloud --project "$PROJECT" --quiet "$@"; }
# New service accounts take a little while to be visible to IAM: retry bindings.
retry() { local n; for n in 1 2 3 4 5 6 7 8; do "$@" && return 0; echo "   (waiting for IAM to catch up, try $n)"; sleep 10; done; return 1; }

REPO=holdenstirling/garmin-mcp
SA_NAME=rabbit-deployer
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
POOL=github
PROVIDER=github-oidc
PNUM=$(g projects describe "$PROJECT" --format='value(projectNumber)')
VM_SA=$(g compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(serviceAccounts[0].email)')

echo "==> APIs"
g services enable iamcredentials.googleapis.com sts.googleapis.com iap.googleapis.com >/dev/null

echo "==> Deploy service account ($SA)"
g iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  g iam service-accounts create "$SA_NAME" --display-name "Rabbit deploys from GitHub Actions" >/dev/null
for role in roles/compute.viewer roles/compute.osAdminLogin roles/iap.tunnelResourceAccessor; do
  retry g projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" \
    --condition=None >/dev/null
done
retry g iam service-accounts add-iam-policy-binding "$VM_SA" --member "serviceAccount:$SA" \
  --role roles/iam.serviceAccountUser >/dev/null

echo "==> Workload identity pool + GitHub provider (only $REPO, only main)"
g iam workload-identity-pools describe "$POOL" --location global >/dev/null 2>&1 || \
  g iam workload-identity-pools create "$POOL" --location global --display-name "GitHub Actions" >/dev/null
if ! g iam workload-identity-pools providers describe "$PROVIDER" --location global \
     --workload-identity-pool "$POOL" >/dev/null 2>&1; then
  g iam workload-identity-pools providers create-oidc "$PROVIDER" --location global \
    --workload-identity-pool "$POOL" --display-name "GitHub OIDC" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository == '$REPO' && assertion.ref == 'refs/heads/main'" >/dev/null
fi
retry g iam service-accounts add-iam-policy-binding "$SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PNUM/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO" >/dev/null

echo
echo "==> Done. GitHub Actions now deploys Rabbit on every push to main."
echo "    provider: projects/$PNUM/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
echo "    account:  $SA"
echo "    Watch runs: https://github.com/$REPO/actions"
