#!/usr/bin/env bash
# Render infra/Caddyfile for $DOMAIN, validate, and reload Caddy (graceful: open
# connections to the MCP server are kept). Run ON the VM as root.
#   sudo DOMAIN=garmin.example.com bash infra/render-caddy.sh
#   sudo DOMAIN=garmin.example.com APP_DOMAIN=rabbit.example.com bash infra/render-caddy.sh
# With APP_DOMAIN, Rabbit (/app) is served on its own hostname and /app on $DOMAIN
# redirects there; the MCP server stays on $DOMAIN. APP_DOMAIN is remembered in
# /etc/caddy/app_domain so later renders keep it.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${DOMAIN:?DOMAIN is required}"
APP_DOMAIN="${APP_DOMAIN:-$(cat /etc/caddy/app_domain 2>/dev/null || true)}"
[[ "$APP_DOMAIN" =~ ^[a-z0-9.-]*$ ]] || { echo "bad APP_DOMAIN"; exit 1; }
TLS_LINE=""
if [[ -f /etc/caddy/certs/origin.pem && -f /etc/caddy/certs/origin.key ]]; then
  TLS_LINE="tls /etc/caddy/certs/origin.pem /etc/caddy/certs/origin.key"
fi
TMP=$(mktemp)
sed -e "s|__DOMAIN__|${DOMAIN}|g" -e "s|__TLS__|${TLS_LINE}|" "$SRC/infra/Caddyfile" > "$TMP"
if [[ -n "$APP_DOMAIN" && "$APP_DOMAIN" != "$DOMAIN" ]]; then
  # /app on the old host -> the app's own host (308 keeps POST bodies).
  python3 - "$TMP" "$APP_DOMAIN" <<'PY'
import sys, re
path, app = sys.argv[1], sys.argv[2]
s = open(path).read()
old = re.search(r"\thandle @rabbit \{.*?\n\t\}\n", s, re.S).group(0)
s = s.replace(old, "\thandle @rabbit {\n\t\tredir https://%s{uri} 308\n\t}\n" % app, 1)
s += """
%s {
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy no-referrer
		X-Frame-Options DENY
		-Server
	}
	@rabbit path /app /app/*
	handle @rabbit {
		reverse_proxy 127.0.0.1:8001 {
			flush_interval -1
			stream_close_delay 5m
		}
	}
	handle {
		redir /app/ 302
	}
}
""" % app
open(path, "w").write(s)
PY
  echo "$APP_DOMAIN" > /etc/caddy/app_domain
fi
caddy validate --config "$TMP" --adapter caddyfile
install -m 0644 "$TMP" /etc/caddy/Caddyfile
rm -f "$TMP"
systemctl reload-or-restart caddy
echo "==> Caddy config applied for $DOMAIN${APP_DOMAIN:+ (Rabbit on $APP_DOMAIN)}"
