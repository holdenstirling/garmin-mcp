#!/usr/bin/env bash
# Sanity-check the GitHub OAuth settings without revealing the secret.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source infra/config.env
echo "config.env client ID: [$GITHUB_CLIENT_ID]"
for v in $(gcloud secrets versions list garmin-mcp-github-client-secret --project "$PROJECT" \
            --format='value(name)' --filter='state=ENABLED'); do
  gcloud secrets versions access "$v" --secret garmin-mcp-github-client-secret --project "$PROJECT" |
    python3 -c 'import sys,re
s=sys.stdin.buffer.read(); t=s.decode("utf-8","replace").strip()
print(f"secret version '"$v"': {len(s)} bytes, stripped {len(t)} chars, 40-hex={bool(re.fullmatch(r\"[0-9a-f]{40}\",t))}, "
      f"has-escape={chr(27) in t}, has-space={any(c.isspace() for c in t)}")'
done
gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo grep -E '^(GITHUB_CLIENT_ID|PUBLIC_BASE_URL)=' /etc/garmin-mcp/env | sed 's/^/VM env: [/; s/\$/]/'" 2>/dev/null
