// Me -> "Sign-in and invites": your passkeys (add / remove), and for the owner (or members
// when MEMBERS_CAN_INVITE) invite links and the member list. Server: passkey_web.py.
import { useCallback, useEffect, useId, useState } from 'react'
import { Ban, Check, Copy, KeyRound, Link, Share2, Trash2, UserMinus, UserPlus } from 'lucide-react'
import { Screen } from '@/components/plan/ui'
import { Group, Icon, Row } from '@/components/settings/Grouped'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import {
  addPasskey, copyLink, createInvite, getAccess, passkeyError, removeMember, removePasskey, revokeInvite,
  shareLink, supportsPasskeys, type AccessInfo, type Invite,
} from '@/lib/passkey'

const day = (t: number | null | undefined) =>
  t ? new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''

const STATUS: Record<Invite['status'], string> = { active: 'Open', expired: 'Expired', full: 'Used up', revoked: 'Revoked' }

const btn = 'inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-1.5 rounded-full px-3 text-[0.7647rem] font-medium'

export function AccessScreen({ onClose }: { onClose: () => void }) {
  const [info, setInfo] = useState<AccessInfo | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [newLink, setNewLink] = useState<string | null>(null)
  const [copied, setCopied] = useState<'shared' | 'copied' | 'failed' | null>(null)
  const [uses, setUses] = useState(10)
  const [days, setDays] = useState(14)
  const [confirm, setConfirm] = useState<string | null>(null)
  const usesId = useId(), daysId = useId()

  const load = useCallback(() => {
    setLoadError(null)
    getAccess().then(setInfo).catch((e: Error) => setLoadError(e.message))
  }, [])
  useEffect(load, [load])

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setError(null)
    try { await fn(); load() } catch (e) { setError(passkeyError(e)) } finally { setBusy(null); setConfirm(null) }
  }

  if (!info) {
    return (
      <Screen title="Sign-in and invites" onClose={onClose}>
        {loadError ? <ErrorState message={loadError} onRetry={load} /> : <RabbitLoader size={48} label="Loading…" />}
      </Screen>
    )
  }
  const onlyKey = !info.google && info.passkeys.length <= 1
  return (
    <Screen title="Sign-in and invites" onClose={onClose}>
      {error && <p role="alert" className="rounded-xl bg-(--danger-subtle) px-3 py-2 text-[0.7647rem] text-(--danger)">{error}</p>}

      <Group label="Passkeys" footer={info.google
        ? 'Add a passkey and you can sign in with your face, fingerprint or device PIN instead of Google.'
        : 'Passkeys are how you sign in. Add one on each phone or computer you use.'}>
        {info.passkeys.map((p) => (
          <Row key={p.id} icon={<Icon><KeyRound /></Icon>} title={p.name}
            subtitle={`Added ${day(p.created)}${p.last_used ? ` · last used ${day(p.last_used)}` : ''}`}
            trailing={onlyKey ? undefined : confirm === p.id ? (
              <button type="button" className={btn + ' bg-(--danger-subtle) text-(--danger)'} disabled={!!busy}
                onClick={() => void run(p.id, () => removePasskey(p.id))}>Remove</button>
            ) : (
              <button type="button" className={btn + ' text-(--text-muted)'} aria-label={`Remove passkey ${p.name}`}
                onClick={() => setConfirm(p.id)}><Trash2 className="size-4" aria-hidden /></button>
            )} />
        ))}
        {supportsPasskeys()
          ? <Row icon={<Icon><KeyRound /></Icon>} title={busy === 'add' ? 'Waiting for your device…' : 'Add a passkey on this device'}
              onClick={busy ? undefined : () => void run('add', addPasskey)} disabled={!!busy} />
          : <Row title="This browser can't make passkeys" subtitle="Try Safari, Chrome or Edge." />}
      </Group>

      {info.can_invite && (
        <Group label="Invite links" footer="Anyone with an open link can join until it expires or is used up. Revoke a link to close it.">
          {newLink ? (
            <div className="flex flex-col gap-2 px-4 py-3">
              <p className="text-[0.8235rem] font-medium text-(--text)">Your new invite link</p>
              <p className="break-all rounded-lg bg-(--bg-inset) px-3 py-2 font-mono text-[0.7059rem] text-(--text)">{newLink}</p>
              <p className="text-[0.7059rem] text-(--text-muted)">Share it now: for safety Rabbit keeps only a fingerprint of it and can't show it again.</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={btn + ' bg-(--accent) text-(--on-fill)'}
                  onClick={() => void shareLink(newLink).then(setCopied)}><Share2 className="size-4" aria-hidden />Share</button>
                <button type="button" className={btn + ' border border-(--border) text-(--text)'}
                  onClick={() => void copyLink(newLink).then(setCopied)}>
                  {copied === 'copied' ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
                  {copied === 'copied' ? 'Copied' : 'Copy'}
                </button>
                <button type="button" className={btn + ' text-(--text-muted)'} onClick={() => { setNewLink(null); setCopied(null) }}>Done</button>
              </div>
              <p aria-live="polite" className="text-[0.7059rem] text-(--text-muted)">
                {copied === 'failed' ? "Couldn't copy. Press and hold the link to copy it." : copied === 'shared' ? 'Shared.' : ''}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-3 px-4 py-3">
              <div className="flex gap-3">
                <label htmlFor={usesId} className="flex flex-1 flex-col gap-1 text-[0.7059rem] text-(--text-muted)">
                  People who can join
                  <select id={usesId} value={uses} onChange={(e) => setUses(Number(e.target.value))}
                    className="h-11 rounded-md border border-input bg-transparent px-2 text-base text-(--text)">
                    {[1, 5, 10, 25].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
                <label htmlFor={daysId} className="flex flex-1 flex-col gap-1 text-[0.7059rem] text-(--text-muted)">
                  Open for
                  <select id={daysId} value={days} onChange={(e) => setDays(Number(e.target.value))}
                    className="h-11 rounded-md border border-input bg-transparent px-2 text-base text-(--text)">
                    {[1, 7, 14, 30].map((n) => <option key={n} value={n}>{n} day{n === 1 ? '' : 's'}</option>)}
                  </select>
                </label>
              </div>
              <button type="button" className={btn + ' bg-(--accent) text-(--on-fill)'} disabled={!!busy}
                onClick={() => void run('invite', async () => { const r = await createInvite(uses, days); setNewLink(r.url); setCopied(null) })}>
                <UserPlus className="size-4" aria-hidden />{busy === 'invite' ? 'Creating…' : 'Create invite link'}
              </button>
            </div>
          )}
          {info.invites.map((inv) => (
            <Row key={inv.id} icon={<Icon tone={inv.status === 'active' ? 'accent' : 'muted'}><Link /></Icon>}
              title={`${STATUS[inv.status]} · ${inv.uses} of ${inv.max_uses} joined`}
              subtitle={`Made ${day(inv.created)} · ${inv.status === 'active' ? 'closes' : 'closed'} ${day(inv.expires)}`
                + (inv.joined.length ? ` · ${inv.joined.map((j) => j.name || 'someone').join(', ')}` : '')}
              trailing={inv.status === 'active' ? (
                <button type="button" className={btn + ' text-(--danger)'} disabled={!!busy} aria-label="Revoke this invite link"
                  onClick={() => void run(inv.id, () => revokeInvite(inv.id))}><Ban className="size-4" aria-hidden />Revoke</button>
              ) : undefined} />
          ))}
        </Group>
      )}

      {info.owner && (
        <Group label="Members" footer="People who joined with an invite link. Removing someone signs them out everywhere and deletes their passkeys; their training data stays until you delete it.">
          {info.members.length === 0 && <Row title="No one has joined with a link yet" />}
          {info.members.map((m) => (
            <Row key={m.user_id} icon={<Icon tone="muted"><UserPlus /></Icon>} title={m.name || 'Member'}
              subtitle={`${m.email} · joined ${day(m.joined)}`}
              trailing={confirm === m.user_id ? (
                <button type="button" className={btn + ' bg-(--danger-subtle) text-(--danger)'} disabled={!!busy}
                  onClick={() => void run(m.user_id, () => removeMember(m.user_id))}>Remove</button>
              ) : (
                <button type="button" className={btn + ' text-(--text-muted)'} aria-label={`Remove ${m.name || 'member'}`}
                  onClick={() => setConfirm(m.user_id)}><UserMinus className="size-4" aria-hidden /></button>
              )} />
          ))}
        </Group>
      )}
    </Screen>
  )
}
