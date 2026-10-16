#!/usr/bin/env bash
# Writes infra/config.env with the known (non-secret) deploy values when it's missing.
# Used by the Cloud Shell scripts and by the GitHub Actions deploy.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f infra/config.env ]] && exit 0
cat > infra/config.env <<'ENV'
PROJECT=training-project-511604
REGION=us-central1
ZONE=us-central1-a
VM_NAME=garmin-mcp
MACHINE_TYPE=e2-micro
DISK_TYPE=pd-standard
DISK_SIZE=30GB
IMAGE_FAMILY=debian-12
BEHIND_CLOUDFLARE=false
DOMAIN=34-45-18-209.sslip.io
APP_DOMAIN=rabbit.holdenottolini.com
GITHUB_CLIENT_ID=Ov23liWUsK5Ksw2XDvKj
ALLOWED_GITHUB_USERS=unused-for-rabbit-deploys
TRAININGPEAKS_ENABLED=true
TRAININGPEAKS_ALLOW_WRITES=true
ENV
echo "==> Wrote infra/config.env"
