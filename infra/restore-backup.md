# Restoring Rabbit + Garmin MCP data

Two independent backups exist:

| Backup | Made by | Kept | Survives |
|---|---|---|---|
| Boot-disk snapshot, daily 09:00 UTC | `infra/cloudshell/10-backups.sh` (`garmin-mcp-daily` policy) | 14 days | a bad deploy, `rm`, a broken VM |
| Off-server archive, daily ~08:20 UTC: `gs://<project>-rabbit-backups/daily/<vm>/<UTC>.tgz`, plus `monthly/` on the 1st | `infra/cloudshell/14-offsite-backups.sh` (timer `rabbit-backup.timer` on the VM) | 30 daily, 12 monthly | losing the VM, its disk and its snapshots |

Both hold **Fernet-encrypted** files only. They are readable only with the keys in Secret Manager
(`garmin-mcp-fernet-key` for `/var/lib/garmin-mcp`, `garmin-mcp-rabbit-fernet-key` for
`/var/lib/rabbit`). Never destroy or disable those secret versions, and keep an offline copy.

Run everything below from Cloud Shell in the repo, after `source infra/config.env`.
Check health first: `bash infra/cloudshell/9-audit.sh`.

## A. Restore from Cloud Storage (whole data dirs, or one user)

1. Pick the archive. The newest is last:

   ```bash
   BUCKET=${BACKUP_BUCKET:-$PROJECT-rabbit-backups}
   gcloud storage ls -l "gs://$BUCKET/daily/**" | sort -k2 | tail -5
   OBJ=gs://$BUCKET/daily/$VM_NAME/20261016T082000Z.tgz   # the one you want
   ```

   Only you (the project owner) can read the bucket. The VM can add archives but not read them.
   Versioning keeps a replaced object for 7 days: `gcloud storage ls -a "$OBJ"`.

2. Download it, check it, and copy it to the VM:

   ```bash
   gcloud storage cp "$OBJ" /tmp/restore.tgz
   gzip -t /tmp/restore.tgz && tar -tzf /tmp/restore.tgz | head
   gcloud compute scp /tmp/restore.tgz "$VM_NAME:/tmp/restore.tgz" --zone "$ZONE" --tunnel-through-iap
   gcloud compute ssh "$VM_NAME" --zone "$ZONE" --tunnel-through-iap
   ```

3. On the VM, unpack it next to the live data (nothing live changes yet):

   ```bash
   sudo mkdir -m 0700 /var/tmp/restore && sudo tar -xzf /tmp/restore.tgz -C /var/tmp/restore
   sudo ls /var/tmp/restore/var/lib/rabbit /var/tmp/restore/var/lib/garmin-mcp
   ```

4. **Everything** (the whole data dir is lost or corrupt). Stop the services, keep the current
   state aside, put the backup in place, fix ownership, start:

   ```bash
   sudo systemctl stop rabbit garmin-mcp
   STAMP=$(date -u +%Y%m%dT%H%M%SZ)
   sudo mv /var/lib/rabbit /var/lib/rabbit.before-restore-$STAMP
   sudo mv /var/lib/garmin-mcp /var/lib/garmin-mcp.before-restore-$STAMP
   sudo mv /var/tmp/restore/var/lib/rabbit /var/lib/rabbit
   sudo mv /var/tmp/restore/var/lib/garmin-mcp /var/lib/garmin-mcp
   sudo chown -R rabbit:rabbit /var/lib/rabbit && sudo chmod 0700 /var/lib/rabbit
   sudo chown -R garmin-mcp:garmin-mcp /var/lib/garmin-mcp && sudo chmod 0700 /var/lib/garmin-mcp
   sudo systemctl start garmin-mcp rabbit
   curl -fsS http://127.0.0.1:8001/healthz && curl -fsS http://127.0.0.1:8000/healthz
   ```

   `"data_writable": true` in both answers means the services can save again. Sign in to the app
   and open a few screens. Remove the `.before-restore-*` copies once you're sure.

   Only the Rabbit app: do the same with `rabbit` alone and leave `garmin-mcp` running.

5. **One person's data** (an accidental delete, a bad edit). Rabbit keeps each person's documents
   in `/var/lib/rabbit/users/<user_id>/<doc>.fernet` (`<user_id>` as in the allowlist, `u_<hex>`
   for invited members, `coach_<hash>` for coaches). Restore one document or the whole folder:

   ```bash
   U=holden                     # the user id
   sudo systemctl stop rabbit   # so nothing writes the doc while it's replaced
   sudo cp -a /var/lib/rabbit/users/$U /var/lib/rabbit/users.$U.before-restore-$(date -u +%s)
   sudo cp -a /var/tmp/restore/var/lib/rabbit/users/$U/events.fernet /var/lib/rabbit/users/$U/   # one doc
   # or the whole person:  sudo rsync -a --delete /var/tmp/restore/var/lib/rabbit/users/$U/ /var/lib/rabbit/users/$U/
   sudo chown -R rabbit:rabbit /var/lib/rabbit/users/$U && sudo chmod 0700 /var/lib/rabbit/users/$U
   sudo systemctl start rabbit
   ```

   Global docs (sessions, members, social graph, clubs, community) are `/var/lib/rabbit/*.fernet`:
   restoring one of those rolls back everyone's part of it, so prefer restoring the whole dir.
   Garmin tokens are `/var/lib/garmin-mcp/tokens/<user>.fernet` (Rabbit's copy:
   `/var/lib/rabbit/tokens/`); Garmin may have rotated them since, so a restored token can need
   `garmin-mcp-login` again.

6. Clean up: `sudo rm -rf /var/tmp/restore /tmp/restore.tgz` (VM) and `rm /tmp/restore.tgz` (Cloud Shell).

To look inside a document (check before restoring), decrypt it with the right key, e.g. on the VM:

```bash
sudo -u rabbit env $(sudo grep -E '^GCP_PROJECT=' /etc/rabbit/env) /opt/rabbit/current/.venv/bin/python - <<'PY'
import os
from cryptography.fernet import Fernet
from garmin_mcp.secrets import get_secret
key = get_secret("garmin-mcp-rabbit-fernet-key", "NO_ENV_FALLBACK", os.environ["GCP_PROJECT"])  # never print it
print(Fernet(key).decrypt(open("/var/tmp/restore/var/lib/rabbit/users/holden/events.fernet", "rb").read())[:400])
PY
```

## B. Restore from a disk snapshot (the VM or disk is broken)

1. Find a snapshot: `gcloud compute snapshots list --filter="sourceDisk~/disks/$VM_NAME\$" --sort-by=~creationTimestamp --limit 5`
2. Make a disk from it: `gcloud compute disks create restore-$(date +%Y%m%d) --source-snapshot <SNAPSHOT> --zone "$ZONE" --type pd-standard`
3. Either **swap the boot disk** (stop the VM, `gcloud compute instances detach-disk "$VM_NAME" --disk <old> --zone "$ZONE"`,
   `gcloud compute instances attach-disk "$VM_NAME" --disk restore-... --boot --zone "$ZONE"`, start it; the static IP,
   service account and firewall tags stay with the instance), or **copy files only**: attach it as a second disk
   (`attach-disk ... --device-name restore`), `sudo mount -o ro /dev/disk/by-id/google-restore-part1 /mnt`, and
   copy from `/mnt/var/lib/...` as in A.4/A.5. Then `sudo umount /mnt` and detach/delete the extra disk.
4. If the VM itself is gone: create a VM from the disk (`gcloud compute instances create "$VM_NAME" --disk name=restore-...,boot=yes`
   with the same service account, scopes `cloud-platform`, tags and static IP as in `infra/setup.sh`), then `./deploy.sh --rabbit`.

## After any restore

* `bash infra/cloudshell/9-audit.sh` (services, `/healthz` data_writable, backup ages).
* Anything written after the archive/snapshot time is gone from the server. People's in-app drafts
  and queued saves (kept on their devices) are retried automatically when they next open the app.
