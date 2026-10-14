#!/usr/bin/env bash
# Cloud Shell step 6 (optional): deploy Rabbit, the phone coach app, at https://<host>/app/
# Asks for: the Claude API key (hidden), the Google OAuth client ID, and its secret (hidden).
# Secrets go straight to Secret Manager and are never printed.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
ALLOWED="${RABBIT_ALLOWED:-holdenstirling@gmail.com:holden}"

pick() {  # pick <regex>: print the single token in stdin matching <regex>, else nothing
  python3 -c 'import re,sys
m=set(re.findall(sys.argv[1], sys.stdin.read()))
print(m.pop() if len(m)==1 else "", end="")' "$1"
}

save_secret() {  # save_secret <name> <value>
  printf '%s' "$2" | gcloud secrets versions add "$1" --project "$PROJECT" --data-file=- >/dev/null
}

if [[ "${SKIP_SECRETS:-}" != 1 ]]; then
  read -r -s -p "Claude API key (sk-ant-..., hidden): " RAW; echo
  KEY=$(printf '%s' "$RAW" | pick 'sk-ant-[A-Za-z0-9_-]{20,}'); unset RAW
  [[ -n "$KEY" ]] || { echo "No sk-ant-... key found in that paste. Nothing saved."; exit 1; }
  save_secret garmin-mcp-anthropic-api-key "$KEY"; unset KEY
  echo "==> Claude API key saved."

  read -r -p "Google OAuth client ID (...apps.googleusercontent.com): " RAW
  GCID=$(printf '%s' "$RAW" | pick '[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com'); unset RAW
  [[ -n "$GCID" ]] || { echo "That doesn't look like a Google OAuth client ID."; exit 1; }
  printf '%s' "$GCID" > infra/.rabbit-google-client-id

  read -r -s -p "Google OAuth client secret (GOCSPX-..., hidden): " RAW; echo
  GSEC=$(printf '%s' "$RAW" | pick 'GOCSPX-[A-Za-z0-9_-]{20,}'); unset RAW
  [[ -n "$GSEC" ]] || { echo "No GOCSPX-... secret found in that paste. Nothing saved."; exit 1; }
  save_secret garmin-mcp-google-client-secret "$GSEC"; unset GSEC
  echo "==> Google client secret saved."
fi
GCID=$(cat infra/.rabbit-google-client-id)

if ! command -v bun >/dev/null; then
  echo "==> Installing bun (builds the web app)"
  curl -fsSL https://bun.sh/install | bash >/dev/null 2>&1
  export PATH="$HOME/.bun/bin:$PATH"
fi

echo "==> Deploying Rabbit (first start is expected to fail until its config is filled in)"
./deploy.sh --rabbit --bootstrap || true

echo "==> Filling in Rabbit's config and starting it"
bash scripts/rabbit-prod-env.sh "$GCID" "$ALLOWED" "mailto:${ALLOWED%%:*}"

cat <<MSG

==================================================================
 Rabbit:  https://$DOMAIN/app/
 Open it on your phone, sign in with Google (${ALLOWED%%:*}),
 connect Garmin, then Share -> Add to Home Screen.
==================================================================
MSG
