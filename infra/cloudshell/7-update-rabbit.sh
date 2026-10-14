#!/usr/bin/env bash
# Cloud Shell: redeploy Rabbit (the phone app) with the latest code. Safe to re-run.
# Works in a fresh (ephemeral) Cloud Shell: recreates infra/config.env from the known
# values if it's missing, installs bun, builds the web app and deploys it. No secrets asked.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"

git pull --ff-only -q || true

if [[ ! -f infra/config.env ]]; then
  echo "==> Writing infra/config.env"
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
GITHUB_CLIENT_ID=Ov23liWUsK5Ksw2XDvKj
ALLOWED_GITHUB_USERS=unused-for-rabbit-deploys
TRAININGPEAKS_ENABLED=true
TRAININGPEAKS_ALLOW_WRITES=true
ENV
fi
gcloud config set project training-project-511604 >/dev/null 2>&1 || true
# APIs Rabbit calls for the athlete (idempotent; quiet when already on).
gcloud services enable calendar-json.googleapis.com --project training-project-511604 --quiet >/dev/null 2>&1 \
  || echo "(couldn't enable the Google Calendar API here; enable it in the Cloud console)"

if ! command -v bun >/dev/null; then
  echo "==> Installing bun"
  curl -fsSL https://bun.sh/install | bash >/dev/null 2>&1
fi

echo "==> Type-checking and building the web app"
LOG=$(mktemp)
if ! (cd web && bun install --frozen-lockfile && bun run build) >"$LOG" 2>&1; then
  tail -40 "$LOG"; echo "!! web build failed (see above). Nothing deployed."; exit 1
fi
echo "    ok"

if command -v uv >/dev/null; then
  echo "==> Running the full test suite (nothing deploys if a test fails)"
  if ! uv run -q pytest -q -x 2>&1 | tail -25; then
    [[ "${SKIP_TESTS:-}" == 1 ]] || { echo "!! tests failed. Nothing deployed."; exit 1; }
  fi
fi

./deploy.sh --rabbit
echo
echo "==> Done. Open https://34-45-18-209.sslip.io/app/"
