#!/usr/bin/env bash
# Cloud Shell: read-only live audit of the VM, network, TLS, secrets and billing guardrails.
#   bash infra/cloudshell/9-audit.sh
# Prints PASS / WARN / FAIL lines (and INFO / CHECK for context and manual follow-ups).
# Changes nothing. Never prints secret values or env-file contents (key names and perms only).
# Safe to re-run. Exit code 1 if any FAIL. See docs/SETUP_AUDIT.md for the why and the fixes.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
[[ -f infra/config.env ]] || { echo "infra/config.env missing: run 7-update-rabbit.sh once first."; exit 1; }
# shellcheck disable=SC1091
source infra/config.env
# shellcheck disable=SC1091
[[ -f infra/gcloud-python.sh ]] && source infra/gcloud-python.sh

HOSTS=("$DOMAIN" 34-45-18-209.sslip.io rabbit.holdenottolini.com)
NP=0 NW=0 NF=0
pass()  { echo "PASS   $*"; NP=$((NP + 1)); }
warn()  { echo "WARN   $*"; NW=$((NW + 1)); }
fail()  { echo "FAIL   $*"; NF=$((NF + 1)); }
info()  { echo "INFO   $*"; }
check() { echo "CHECK  $*"; }
section() { echo; echo "== $*"; }
g() { gcloud --project "$PROJECT" --quiet "$@"; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------------------
section "VM ($VM_NAME, $ZONE)"
if ! g compute instances describe "$VM_NAME" --zone "$ZONE" --format=json >"$TMP/vm.json" 2>"$TMP/err"; then
  fail "cannot describe VM: $(head -1 "$TMP/err")"
  echo "{}" >"$TMP/vm.json"
fi
# Emits shell-safe KEY=VALUE lines from the instance JSON.
python3 - "$TMP/vm.json" >"$TMP/vm.env" <<'PY'
import json, shlex, sys
d = json.load(open(sys.argv[1]))
md = {i.get("key"): i.get("value") for i in d.get("metadata", {}).get("items", [])}
boot = next((x for x in d.get("disks", []) if x.get("boot")), {})
nic = (d.get("networkInterfaces") or [{}])[0]
ac = (nic.get("accessConfigs") or [{}])[0]
sa = (d.get("serviceAccounts") or [{}])[0]
sh = d.get("shieldedInstanceConfig", {})
out = {
    "VM_STATUS": d.get("status", ""),
    "VM_TYPE": d.get("machineType", "").rsplit("/", 1)[-1],
    "VM_TAGS": ",".join(d.get("tags", {}).get("items", [])),
    "VM_BOOT_DISK": boot.get("source", "").rsplit("/", 1)[-1],
    "VM_IP": ac.get("natIP", ""),
    "VM_OSLOGIN": str(md.get("enable-oslogin", "")).upper(),
    "VM_BLOCK_KEYS": str(md.get("block-project-ssh-keys", "")).upper(),
    "VM_SSH_KEYS_MD": "yes" if md.get("ssh-keys") else "no",
    "VM_SA": sa.get("email", ""),
    "VM_SCOPES": ",".join(s.rsplit("/", 1)[-1] for s in sa.get("scopes", [])),
    "VM_DELETION_PROTECTION": str(d.get("deletionProtection", False)).lower(),
    "VM_SECURE_BOOT": str(sh.get("enableSecureBoot", False)).lower(),
}
for k, v in out.items():
    print(f"{k}={shlex.quote(v)}")
PY
# shellcheck disable=SC1091
source "$TMP/vm.env"

[[ "${VM_STATUS:-}" == RUNNING ]] && pass "VM status RUNNING" || fail "VM status '${VM_STATUS:-unknown}'"
info "machine type ${VM_TYPE:-?} (e2-micro: 2 shared vCPU, 1 GB RAM; one VM = single point of failure)"
info "external IP ${VM_IP:-none}, tags ${VM_TAGS:-none}, service account ${VM_SA:-none} (scopes: ${VM_SCOPES:-none})"
[[ "${VM_OSLOGIN:-}" == TRUE ]] && pass "OS Login enabled" || warn "OS Login not enabled on the instance"
[[ "${VM_BLOCK_KEYS:-}" == TRUE ]] && pass "project-wide SSH keys blocked" || warn "block-project-ssh-keys not set"
[[ "${VM_SSH_KEYS_MD:-no}" == no ]] && pass "no instance ssh-keys metadata" || warn "instance has ssh-keys metadata (bypasses OS Login intent)"
[[ "${VM_SECURE_BOOT:-}" == true ]] && pass "Shielded VM secure boot on" || warn "Shielded VM secure boot off"
[[ "${VM_DELETION_PROTECTION:-}" == true ]] && pass "deletion protection on" \
  || warn "deletion protection off (gcloud compute instances update $VM_NAME --zone $ZONE --deletion-protection)"

# ---------------------------------------------------------------------------
section "Boot disk + backups"
if [[ -n "${VM_BOOT_DISK:-}" ]] &&
   g compute disks describe "$VM_BOOT_DISK" --zone "$ZONE" --format=json >"$TMP/disk.json" 2>/dev/null; then
  read -r DSIZE DTYPE DPOL < <(python3 -c '
import json,sys; d=json.load(open(sys.argv[1]))
pols=",".join(p.rsplit("/",1)[-1] for p in d.get("resourcePolicies",[])) or "-"
print(d.get("sizeGb","?"), d.get("type","").rsplit("/",1)[-1], pols)' "$TMP/disk.json")
  info "boot disk $VM_BOOT_DISK: ${DSIZE}GB $DTYPE"
  if [[ "$DPOL" == "-" ]]; then
    fail "no snapshot schedule attached to $VM_BOOT_DISK (no backups). Fix: bash infra/cloudshell/10-backups.sh"
  else
    pass "resource policies on boot disk: $DPOL"
    for p in ${DPOL//,/ }; do
      g compute resource-policies describe "$p" --region "$REGION" \
        --format='value(snapshotSchedulePolicy.retentionPolicy.maxRetentionDays,snapshotSchedulePolicy.schedule.dailySchedule.startTime)' \
        2>/dev/null | while read -r days start; do info "  $p: retention ${days:-?} days, daily start ${start:-?} UTC"; done
    done
  fi
  LAST=$(g compute snapshots list --filter="sourceDisk~/disks/$VM_BOOT_DISK\$" \
    --sort-by=~creationTimestamp --limit=1 --format='value(name,creationTimestamp)' 2>/dev/null)
  NSNAP=$(g compute snapshots list --filter="sourceDisk~/disks/$VM_BOOT_DISK\$" --format='value(name)' 2>/dev/null | wc -l)
  if [[ -z "$LAST" ]]; then
    fail "no snapshots exist for $VM_BOOT_DISK"
  else
    LAST_TS=${LAST##*[[:space:]]}
    AGE_H=$(( ( $(date -u +%s) - $(date -u -d "$LAST_TS" +%s 2>/dev/null || echo 0) ) / 3600 ))
    if (( AGE_H <= 26 )); then pass "latest snapshot ${AGE_H}h old ($NSNAP total)"
    else warn "latest snapshot ${AGE_H}h old ($NSNAP total)"; fi
  fi
else
  fail "cannot describe boot disk '${VM_BOOT_DISK:-?}'"
fi

# ---------------------------------------------------------------------------
section "Firewall (rules that apply to this VM)"
if g compute firewall-rules list --format=json >"$TMP/fw.json" 2>"$TMP/err"; then
  python3 - "$TMP/fw.json" "${VM_TAGS:-}" <<'PY'
import json, sys
rules = json.load(open(sys.argv[1]))
tags = set(filter(None, sys.argv[2].split(",")))
IAP = "35.235.240.0/20"
OPEN = {"0.0.0.0/0", "::/0"}

def ports(rule):
    out = []
    for a in rule.get("allowed", []):
        proto = a.get("IPProtocol")
        for p in a.get("ports") or ["all"]:
            out.append((proto, p))
    return out

def covers(proto, p, port):
    if proto not in ("tcp", "all"):
        return False
    if p == "all":
        return True
    lo, _, hi = p.partition("-")
    return int(lo) <= port <= int(hi or lo)

ssh_open = iap_ok = False
for r in rules:
    if r.get("disabled") or r.get("direction") != "INGRESS" or not r.get("allowed"):
        continue
    targets = set(r.get("targetTags") or [])
    if targets and not (targets & tags) and not r.get("targetServiceAccounts"):
        continue  # does not apply to this VM
    src = set(r.get("sourceRanges") or [])
    ps = ports(r)
    desc = ",".join(f"{a}:{b}" for a, b in ps)
    if src & OPEN:
        rule_ssh = any(covers(a, b, 22) for a, b in ps)
        if rule_ssh:
            ssh_open = True
            print(f"FAIL   {r['name']}: SSH (22) open to the internet ({desc})")
        bad = [(a, b) for a, b in ps if not (a == "tcp" and b in ("80", "443", "22"))
               and not (a == "icmp")]  # 22 already reported above
        if bad:
            print(f"FAIL   {r['name']}: 0.0.0.0/0 allowed on {','.join(f'{a}:{b}' for a,b in bad)}")
        elif not rule_ssh:
            print(f"PASS   {r['name']}: internet-facing only on {desc}")
    elif src == {IAP} and any(covers(a, b, 22) for a, b in ps):
        iap_ok = True
        print(f"PASS   {r['name']}: SSH only from IAP range {IAP}")
    else:
        print(f"INFO   {r['name']}: {desc} from {','.join(sorted(src)) or 'tags/SA'}")
if not ssh_open:
    print("PASS   no rule exposes SSH (22) to 0.0.0.0/0")
if not iap_ok:
    print(f"WARN   no IAP-only SSH rule ({IAP}) found for this VM's tags")
PY
else
  fail "cannot list firewall rules: $(head -1 "$TMP/err")"
fi | tee "$TMP/fw.out"
NP=$((NP + $(grep -c '^PASS' "$TMP/fw.out"))); NW=$((NW + $(grep -c '^WARN' "$TMP/fw.out"))); NF=$((NF + $(grep -c '^FAIL' "$TMP/fw.out")))

# ---------------------------------------------------------------------------
section "On the VM (one IAP SSH session, read-only)"
# The remote script prints its own PASS/WARN/FAIL/INFO lines; they are counted below.
# shellcheck disable=SC2016
if gcloud compute ssh "$VM_NAME" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --quiet \
     --command "sudo bash -s" >"$TMP/remote.out" 2>"$TMP/remote.err" <<'REMOTE'
set -uo pipefail
p() { echo "PASS   $*"; }; w() { echo "WARN   $*"; }; f() { echo "FAIL   $*"; }; i() { echo "INFO   $*"; }

. /etc/os-release 2>/dev/null; i "OS ${PRETTY_NAME:-?}, kernel $(uname -r), up $(uptime -p 2>/dev/null)"
read -r _ total used _ < <(free -m | awk '/^Mem:/{print $1,$2,$3,$4}')
i "memory ${used}/${total} MB used; swap $(free -m | awk '/^Swap:/{print $3"/"$2}') MB"

pct=$(df -P / | awk 'NR==2{gsub("%","",$5); print $5}')
sz=$(df -hP / | awk 'NR==2{print $2" total, "$4" free"}')
if (( pct >= 85 )); then f "root disk ${pct}% used ($sz)"
elif (( pct >= 70 )); then w "root disk ${pct}% used ($sz)"
else p "root disk ${pct}% used ($sz)"; fi
i "data size: $(du -sh /var/lib/garmin-mcp 2>/dev/null | cut -f1) garmin-mcp, $(du -sh /var/lib/rabbit 2>/dev/null | cut -f1) rabbit"

# --- OS updates
if dpkg -s unattended-upgrades >/dev/null 2>&1; then
  en=$(apt-config dump APT::Periodic::Unattended-Upgrade 2>/dev/null | awk -F'"' '{print $2}')
  timer=$(systemctl is-active apt-daily-upgrade.timer 2>/dev/null)
  if [[ "$en" == 1 && "$timer" == active ]]; then p "unattended-upgrades enabled (timer active)"
  else f "unattended-upgrades installed but not enabled (Unattended-Upgrade='$en', timer=$timer)"; fi
  log=/var/log/unattended-upgrades/unattended-upgrades.log
  if [[ -f $log ]]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$log") ) / 86400 ))
    (( age <= 2 )) && p "unattended-upgrades ran ${age}d ago" || w "unattended-upgrades last ran ${age}d ago"
  fi
  reboot=$(apt-config dump Unattended-Upgrade::Automatic-Reboot 2>/dev/null | awk -F'"' '{print $2}')
  [[ "$reboot" == true ]] && i "automatic reboot enabled" || i "automatic reboot off: kernel/libc fixes wait for a manual reboot"
else
  f "unattended-upgrades not installed"
fi
sec=$(apt-get -s -o Debug::NoLocking=1 upgrade 2>/dev/null | grep -c '^Inst .*[Ss]ecurity')
all=$(apt-get -s -o Debug::NoLocking=1 upgrade 2>/dev/null | grep -c '^Inst ')
if (( sec > 0 )); then w "$sec pending security updates ($all total pending, per cached package lists)"
else p "no pending security updates ($all other pending)"; fi
apt-get -s -o Debug::NoLocking=1 upgrade 2>/dev/null | grep -q '^Inst caddy ' &&
  w "caddy upgrade pending (Caddy's apt repo is not in unattended-upgrades' origins)"
newest=$(find /boot -maxdepth 1 -name 'vmlinuz-*' -printf '%f\n' 2>/dev/null | sed 's/^vmlinuz-//' | sort -V | tail -1)
if [[ -n "$newest" && "$newest" != "$(uname -r)" ]]; then w "reboot needed: running $(uname -r), installed $newest"
else p "running the newest installed kernel"; fi

# --- services
for s in caddy garmin-mcp rabbit; do
  a=$(systemctl is-active "$s" 2>/dev/null); e=$(systemctl is-enabled "$s" 2>/dev/null)
  n=$(systemctl show -p NRestarts --value "$s" 2>/dev/null)
  if [[ "$a" == active && "$e" == enabled ]]; then p "$s active + enabled (restarts since start: ${n:-?})"
  else f "$s is '$a' / '$e'"; fi
done
for pp in 8000:garmin-mcp 8001:rabbit; do
  port=${pp%%:*}; name=${pp#*:}
  curl -fsS -m 5 "http://127.0.0.1:$port/healthz" >/dev/null 2>&1 && p "$name /healthz on 127.0.0.1:$port" || f "$name /healthz on 127.0.0.1:$port failed"
done
for u in garmin-mcp rabbit caddy; do
  sc=$(systemd-analyze security --no-pager "$u.service" 2>/dev/null | grep -i 'overall exposure' | sed 's/.*: //')
  [[ -n "$sc" ]] && i "systemd exposure $u: $sc"
done

# --- listeners: app ports must be loopback only
ext=$(ss -Hltn 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|::1)' | grep -vE ':(22|80|443)$' | sort -u | tr '\n' ' ')
[[ -z "$ext" ]] && p "only 22/80/443 listen on non-loopback addresses" || w "non-loopback TCP listeners: $ext"

# --- sshd
sshd_cfg=$(sshd -T 2>/dev/null)
pa=$(awk '$1=="passwordauthentication"{print $2}' <<<"$sshd_cfg")
pr=$(awk '$1=="permitrootlogin"{print $2}' <<<"$sshd_cfg")
[[ "$pa" == no ]] && p "sshd password auth off" || w "sshd passwordauthentication=$pa"
[[ "$pr" == no || "$pr" == prohibit-password || "$pr" == without-password ]] && p "sshd root login: $pr" || w "sshd permitrootlogin=$pr"

# --- journald
ju=$(journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]?B?' | head -1)
[[ -d /var/log/journal ]] && pers=persistent || pers="volatile (lost on reboot)"
cap=$(systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -E '^\s*SystemMaxUse=' | tail -1)
if [[ -n "$cap" ]]; then p "journald $pers, ${ju:-?} used, $cap"
else w "journald $pers, ${ju:-?} used, no SystemMaxUse cap (default: 10% of fs, max 4G)"; fi

# --- env files: perms + key names only (values never printed)
chk_perm() {  # path want_mode want_owner
  [[ -e "$1" ]] || { f "$1 missing"; return; }
  got=$(stat -c '%a %U:%G' "$1")
  [[ "$got" == "$2 $3" ]] && p "$1 $got" || f "$1 is $got (want $2 $3)"
}
chk_perm /etc/garmin-mcp 750 root:garmin-mcp
chk_perm /etc/garmin-mcp/env 640 root:garmin-mcp
chk_perm /etc/rabbit 750 root:rabbit
chk_perm /etc/rabbit/env 640 root:rabbit
for e in /etc/garmin-mcp/env /etc/rabbit/env; do
  [[ -f $e ]] || continue
  i "$e keys: $(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$e" | tr -d = | sort | tr '\n' ' ')"
  # Names that look like secrets and are set inline (not *_SECRET_NAME / *_FILE / allowlists / IDs).
  sus=$(grep -E '^[A-Za-z_]*(SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|FERNET_KEY)[A-Za-z_]*=.+' "$e" \
        | cut -d= -f1 | grep -vE '(_NAME|_FILE|_TTL_SECONDS|_BUDGET)$' | tr '\n' ' ')
  [[ -z "$sus" ]] && p "$e: no inline secret-looking values" || w "$e: inline value for $sus(should come from Secret Manager)"
done

# --- data dirs
chk_perm /var/lib/garmin-mcp 700 garmin-mcp:garmin-mcp
chk_perm /var/lib/garmin-mcp/tokens 700 garmin-mcp:garmin-mcp
chk_perm /var/lib/garmin-mcp/oauth 700 garmin-mcp:garmin-mcp
chk_perm /var/lib/rabbit 700 rabbit:rabbit
chk_perm /var/lib/rabbit/tokens 700 rabbit:rabbit
for d in /var/lib/garmin-mcp /var/lib/rabbit; do
  [[ -d $d ]] || continue
  n=$(find "$d" \( -perm -o=r -o -perm -o=w -o -perm -g=w \) 2>/dev/null | wc -l)
  (( n == 0 )) && p "$d: nothing group/world-accessible" || f "$d: $n entries group-writable or world-accessible"
  owner=$(stat -c %U "$d")
  n=$(find "$d" ! -user "$owner" 2>/dev/null | wc -l)
  (( n == 0 )) && p "$d: all files owned by $owner" || w "$d: $n entries not owned by $owner"
  plain=$(find "$d" -type f \( -name '*.json' -o -name '*.txt' -o -name '*.db' \) 2>/dev/null | wc -l)
  (( plain == 0 )) || w "$d: $plain non-.fernet data files (check they hold no plaintext secrets/health data)"
done
for a in garmin-mcp rabbit; do
  [[ -d /opt/$a/releases ]] && i "$a: $(ls -1 /opt/$a/releases | wc -l) releases kept, current -> $(basename "$(readlink -f /opt/$a/current)")"
done
REMOTE
then
  cat "$TMP/remote.out"
  NP=$((NP + $(grep -c '^PASS' "$TMP/remote.out"))); NW=$((NW + $(grep -c '^WARN' "$TMP/remote.out"))); NF=$((NF + $(grep -c '^FAIL' "$TMP/remote.out")))
else
  cat "$TMP/remote.out" 2>/dev/null
  fail "IAP SSH to $VM_NAME failed: $(grep -v '^$' "$TMP/remote.err" | tail -1)"
fi

# ---------------------------------------------------------------------------
section "Public endpoints + TLS"
seen=""
for h in "${HOSTS[@]}"; do
  [[ -n "$h" && " $seen " != *" $h "* ]] || continue
  seen="$seen $h"
  ip=$(python3 -c 'import socket,sys
try: print(socket.gethostbyname(sys.argv[1]))
except Exception: pass' "$h")
  if [[ -z "$ip" ]]; then info "$h does not resolve yet: skipped"; continue; fi
  [[ "$ip" == "${VM_IP:-$ip}" ]] && pass "$h resolves to the VM ($ip)" || warn "$h resolves to $ip, VM IP is ${VM_IP:-?}"
  end=$(echo | timeout 15 openssl s_client -connect "$h:443" -servername "$h" 2>/dev/null |
        openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [[ -z "$end" ]]; then
    fail "$h: no TLS certificate on :443"
  else
    days=$(( ( $(date -u -d "$end" +%s) - $(date -u +%s) ) / 86400 ))
    issuer=$(echo | timeout 15 openssl s_client -connect "$h:443" -servername "$h" 2>/dev/null |
             openssl x509 -noout -issuer 2>/dev/null | sed 's/.*O *= *//; s/,.*//')
    if (( days < 7 )); then fail "$h cert expires in ${days}d ($issuer): Caddy renewal is failing"
    elif (( days < 20 )); then warn "$h cert expires in ${days}d ($issuer): Caddy renews ~30d before expiry"
    else pass "$h cert valid ${days}d ($issuer)"; fi
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "https://$h/healthz")
  [[ "$code" == 200 ]] && pass "https://$h/healthz 200 (MCP server)" || fail "https://$h/healthz -> $code"
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "https://$h/app/privacy")
  [[ "$code" == 200 ]] && pass "https://$h/app/privacy 200 (Rabbit via Caddy)" || fail "https://$h/app/privacy -> $code (Rabbit)"
  hdrs=$(curl -sI -m 10 "https://$h/healthz" | tr -d '\r')
  grep -qi '^strict-transport-security:' <<<"$hdrs" && pass "$h sends HSTS" || warn "$h: no HSTS header"
  grep -qi '^content-security-policy:' <<<"$hdrs" || info "$h: no Content-Security-Policy header at the edge"
  loc=$(curl -sI -m 10 "http://$h/" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')
  [[ "$loc" == https://* ]] && pass "$h: http redirects to https" || warn "$h: http:// does not redirect to https (${loc:-no Location})"
done

# ---------------------------------------------------------------------------
section "Secret Manager (names + who can read; never values)"
if g secrets list --format='value(name.basename())' >"$TMP/secrets" 2>"$TMP/err"; then
  info "secrets: $(tr '\n' ' ' <"$TMP/secrets")"
  while read -r s; do
    [[ -n "$s" ]] || continue
    nver=$(g secrets versions list "$s" --filter='state=ENABLED' --format='value(name)' 2>/dev/null | wc -l)
    who=$(g secrets get-iam-policy "$s" --format=json 2>/dev/null | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
m=sorted({x for b in d.get("bindings",[]) if b["role"] in ("roles/secretmanager.secretAccessor","roles/secretmanager.admin","roles/owner") for x in b["members"]})
print(" ".join(m) or "-")')
    (( nver > 0 )) || info "$s has no enabled version (unused or not yet set)"
    if [[ "$who" == "-" ]]; then info "$s: no secret-level readers (project-level roles only)"
    elif [[ "$who" == "serviceAccount:${VM_SA:-x}" ]]; then pass "$s: readable only by the VM service account ($nver enabled version(s))"
    else warn "$s readers: $who"; fi
  done <"$TMP/secrets"
  info "both services share one VM service account, so Rabbit's process can read the MCP Fernet key (and vice versa)"
else
  fail "cannot list secrets: $(head -1 "$TMP/err")"
fi
if g projects get-iam-policy "$PROJECT" --format=json >"$TMP/iam.json" 2>/dev/null; then
  python3 - "$TMP/iam.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
watch = {
    "roles/owner": "owner", "roles/editor": "editor",
    "roles/secretmanager.admin": "secret admin", "roles/secretmanager.secretAccessor": "reads ALL secrets",
    "roles/iap.tunnelResourceAccessor": "IAP tunnel", "roles/compute.osAdminLogin": "root on VMs",
}
for b in d.get("bindings", []):
    if b["role"] in watch:
        print(f"INFO   project {watch[b['role']]} ({b['role'].split('/')[-1]}): {' '.join(b['members'])}")
    if b["role"] == "roles/secretmanager.secretAccessor":
        print("WARN   project-level secretAccessor grants every secret; prefer per-secret bindings")
PY
else
  warn "cannot read project IAM policy (permission)"
fi | tee "$TMP/iam.out"
NW=$((NW + $(grep -c '^WARN' "$TMP/iam.out")))

# ---------------------------------------------------------------------------
section "Guardrails: budgets, monitoring"
BA=$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' 2>/dev/null | sed 's|billingAccounts/||')
if [[ -z "$BA" ]]; then
  warn "cannot read the billing account (needs billing viewer); CHECK budgets in the console"
else
  if out=$(gcloud billing budgets list --billing-account="$BA" \
             --format='value(displayName,amount.specifiedAmount.units,amount.specifiedAmount.currencyCode)' 2>&1); then
    if [[ -n "$out" ]]; then pass "budget(s) on billing account: $(tr '\n' ';' <<<"$out")"
    else warn "no GCP budget alerts on billing account $BA"; fi
  else
    warn "cannot list budgets (permission or billingbudgets API off): CHECK live"
  fi
fi
if up=$(g monitoring uptime list-configs --format='value(displayName)' 2>/dev/null); then
  [[ -n "$up" ]] && pass "uptime checks: $(tr '\n' ';' <<<"$up")" || warn "no Cloud Monitoring uptime checks (no one is paged when /healthz dies)"
else
  warn "cannot list uptime checks (monitoring API off or no permission)"
fi
if pol=$(gcloud alpha monitoring policies list --project "$PROJECT" --format='value(displayName)' 2>/dev/null); then
  [[ -n "$pol" ]] && pass "alert policies: $(tr '\n' ';' <<<"$pol")" || warn "no alerting policies"
fi
check "Anthropic console: workspace spend limit + usage alerts for the Rabbit API key"
check "Google OAuth consent screen: publishing status (Testing => Calendar refresh tokens expire after 7 days, 100 test users)"
check "GitHub OAuth App + Oura app redirect URIs updated for the new domain"

echo
echo "== Summary: $NP pass, $NW warn, $NF fail"
(( NF == 0 ))
