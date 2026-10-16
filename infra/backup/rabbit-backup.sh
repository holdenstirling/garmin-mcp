#!/usr/bin/env bash
# Nightly off-server backup of the app data (runs ON the VM as root from rabbit-backup.service).
# Installed to /usr/local/sbin/rabbit-backup by infra/backup/install.sh.
#
# What: one tar.gz of /var/lib/rabbit and /var/lib/garmin-mcp. Every document in them is
#   already Fernet-encrypted at rest; the Fernet keys are NOT on this disk (they live only in
#   Secret Manager) and are never added to the archive. Temp files and health probes are skipped.
# Where: gs://$BACKUP_BUCKET/daily/<UTC timestamp>.tgz, plus monthly/<YYYY-MM>-<timestamp>.tgz
#   on the 1st (bucket lifecycle keeps 30 days of dailies and 12 months of monthlies; see
#   infra/cloudshell/14-offsite-backups.sh).
# How: the VM's service account token from the metadata server + curl to the GCS XML API
#   (no gcloud/gsutil needed). The service account only has roles/storage.objectCreator on
#   the bucket: it can add objects, never read, overwrite or delete them. Uploads use
#   x-goog-if-generation-match: 0 (create only) and Content-MD5 (GCS rejects a corrupt upload).
# Result: /var/lib/rabbit-backup/last-success (UTC epoch, object, bytes) for 9-audit.sh.
# Restore: infra/restore-backup.md.
set -euo pipefail
umask 077

CONF=/etc/rabbit-backup.env
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"
BUCKET="${BACKUP_BUCKET:?set BACKUP_BUCKET in $CONF}"
SOURCES=(/var/lib/rabbit /var/lib/garmin-mcp)
# Testing: BACKUP_SOURCES="/tmp/a /tmp/b" DRY_RUN=1 lists what would be uploaded, uploads nothing.
[[ -n "${BACKUP_SOURCES:-}" ]] && read -r -a SOURCES <<<"$BACKUP_SOURCES"
STATE_DIR=/var/lib/rabbit-backup
MD=http://metadata.google.internal/computeMetadata/v1

log() { echo "rabbit-backup: $*"; }

[[ "$BUCKET" =~ ^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$ ]] || { log "bad bucket name '$BUCKET'"; exit 2; }

present=()
for d in "${SOURCES[@]}"; do [[ -d "$d" ]] && present+=("${d#/}"); done
(( ${#present[@]} )) || { log "no data directories found"; exit 1; }

WORK=$(mktemp -d /var/tmp/rabbit-backup.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
ARCHIVE="$WORK/backup.tgz"

# Room for the archive (compressed size <= data size) plus margin.
need_kb=$(du -sk "${present[@]/#//}" | awk '{s+=$1} END {print s+10240}')
free_kb=$(df -Pk /var/tmp | awk 'NR==2{print $4}')
(( free_kb > need_kb )) || { log "not enough space in /var/tmp (${free_kb} KB free, need ${need_kb} KB)"; exit 1; }

# Files are written atomically (temp + rename), so each one is old or new, never partial.
# Exit 1 from tar = "file changed while reading" (a doc saved mid-backup): still a good archive.
rc=0
tar --create --gzip --file "$ARCHIVE" --directory / \
  --exclude='*.tmp' --exclude='.healthz-*' --exclude='*fernet*key*' --exclude='*.key' \
  --exclude='*.pem' --exclude='env' --exclude='*.env' \
  --warning=no-file-changed --warning=no-file-removed \
  "${present[@]}" || rc=$?
(( rc == 0 || rc == 1 )) || { log "tar failed ($rc)"; exit 1; }
gzip -t "$ARCHIVE"
size=$(stat -c %s "$ARCHIVE")
md5=$(openssl dgst -md5 -binary "$ARCHIVE" | base64)
if [[ "${DRY_RUN:-0}" == 1 ]]; then
  tar -tzf "$ARCHIVE"; log "dry run: $size bytes, nothing uploaded"; exit 0
fi

token=$(curl -fsS -H 'Metadata-Flavor: Google' "$MD/instance/service-accounts/default/token" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

host=$(curl -fsS -H 'Metadata-Flavor: Google' "$MD/instance/name" 2>/dev/null || hostname -s)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
objects=("daily/$host/$stamp.tgz")
[[ "$(date -u +%d)" == 01 ]] && objects+=("monthly/$host/$(date -u +%Y-%m)-$stamp.tgz")

for obj in "${objects[@]}"; do
  for attempt in 1 2 3 4 5; do
    code=$(curl -sS -o "$WORK/resp" -w '%{http_code}' -X PUT --data-binary "@$ARCHIVE" \
      -H "Authorization: Bearer $token" -H 'Content-Type: application/gzip' \
      -H "Content-MD5: $md5" -H 'x-goog-if-generation-match: 0' \
      "https://storage.googleapis.com/$BUCKET/$obj" || echo 000)
    [[ "$code" == 200 ]] && break
    log "upload $obj attempt $attempt -> HTTP $code: $(head -c 300 "$WORK/resp" 2>/dev/null)"
    [[ "$code" == 4* && "$code" != 408 && "$code" != 429 ]] && exit 1
    sleep $(( attempt * 20 ))
  done
  [[ "$code" == 200 ]] || { log "upload $obj failed"; exit 1; }
  log "uploaded gs://$BUCKET/$obj ($size bytes)"
done

install -d -m 0700 "$STATE_DIR"
printf '%s %s %s\n' "$(date -u +%s)" "gs://$BUCKET/${objects[0]}" "$size" > "$STATE_DIR/last-success.tmp"
mv -f "$STATE_DIR/last-success.tmp" "$STATE_DIR/last-success"
