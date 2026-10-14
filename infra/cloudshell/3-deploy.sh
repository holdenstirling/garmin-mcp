#!/usr/bin/env bash
# Cloud Shell step 3: first deploy (installs Caddy, uv, Python, systemd unit) and a health check.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
[[ "$GITHUB_CLIENT_ID" != Ov23li... && -n "$GITHUB_CLIENT_ID" ]] || { echo "Run step 2 first."; exit 1; }
[[ "$DOMAIN" != garmin.example.com ]] || { echo "Run step 1 first."; exit 1; }

./deploy.sh --bootstrap

echo "==> Waiting for HTTPS on $DOMAIN (Caddy fetches a Let's Encrypt certificate)"
for i in $(seq 1 30); do
  if curl -fsS "https://$DOMAIN/healthz" >/dev/null 2>&1; then
    echo
    echo "=================================================================="
    echo " Live:  https://$DOMAIN/healthz"
    echo " claude.ai connector URL:  https://$DOMAIN/mcp"
    echo "=================================================================="
    exit 0
  fi
  sleep 5
done
echo "!! HTTPS not answering yet; Caddy may still be getting its certificate. Try again in a minute:"
echo "   curl https://$DOMAIN/healthz"
