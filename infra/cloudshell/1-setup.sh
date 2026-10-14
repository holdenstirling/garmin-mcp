#!/usr/bin/env bash
# Cloud Shell step 1: write infra/config.env, create the GCP resources, pick an sslip.io hostname.
set -euo pipefail
cd "$(dirname "$0")/../.."

if ! command -v uv >/dev/null; then
  echo "==> Installing uv (needed by setup.sh to generate the Web Push key)"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
fi
export PATH="$HOME/.local/bin:$PATH"

PROJECT=$(gcloud config get-value project 2>/dev/null)
[[ -n "$PROJECT" ]] || { echo "No project selected: gcloud config set project <id>"; exit 1; }
GH_LOGIN=${GH_LOGIN:-holdenstirling}
GHID=$(curl -fsS "https://api.github.com/users/$GH_LOGIN" |
  python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')

if [[ ! -f infra/config.env ]]; then
  sed -e "s/^PROJECT=.*/PROJECT=$PROJECT/" \
      -e "s/^BEHIND_CLOUDFLARE=.*/BEHIND_CLOUDFLARE=false/" \
      -e "s/^ALLOWED_GITHUB_USERS=.*/ALLOWED_GITHUB_USERS=$GHID:holden/" \
      -e "s/^TRAININGPEAKS_ENABLED=.*/TRAININGPEAKS_ENABLED=true/" \
      -e "s/^TRAININGPEAKS_ALLOW_WRITES=.*/TRAININGPEAKS_ALLOW_WRITES=true/" \
      infra/config.env.example > infra/config.env
fi
# shellcheck disable=SC1091
source infra/config.env

DELETE_DEFAULT_SSH=y ./infra/setup.sh

IP=$(gcloud compute addresses describe garmin-mcp-ip --project "$PROJECT" --region "$REGION" \
  --format='value(address)')
DOMAIN="${IP//./-}.sslip.io"
sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" infra/config.env

cat <<MSG

==================================================================
 Server address:  https://$DOMAIN
 GitHub OAuth App settings (next step):
   Homepage URL:               https://$DOMAIN
   Authorization callback URL: https://$DOMAIN/github/callback
==================================================================
MSG
