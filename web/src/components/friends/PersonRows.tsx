// One person in Find friends: photo, name, @handle, why they're here, Follow (or Following /
// Requested), and an optional dismiss. Follow is optimistic and reverts with the error.
import { useState } from 'react'
import { Check, UserPlus, X } from 'lucide-react'
import { PersonAvatar } from '@/components/people/PersonLink'
import { openPerson } from '@/lib/people'
import { followPerson, type FindStatus, type FindUser } from '@/lib/friends'
import { cn } from '@/lib/utils'

export function FollowButton({ uid, status, followsYou, onDone, onError, compact }: {
  uid: string; status: FindStatus; followsYou?: boolean
  onDone?: (s: FindStatus) => void; onError?: (msg: string) => void; compact?: boolean
}) {
  const [s, setS] = useState(status)
  const [busy, setBusy] = useState(false)
  if (s !== 'none') {
    return (
      <span className="inline-flex h-9 shrink-0 items-center gap-1 rounded-full bg-(--bg-inset) px-3 text-[0.7647rem] font-medium text-(--text-secondary)">
        <Check className="size-3.5" aria-hidden /> {s === 'following' ? 'Following' : 'Requested'}
      </span>
    )
  }
  async function go() {
    setBusy(true)
    try { const r = await followPerson(uid); setS(r.status); onDone?.(r.status) }
    catch (e) { onError?.((e as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <button type="button" disabled={busy} onClick={() => void go()}
      className={cn('inline-flex h-9 shrink-0 items-center gap-1 rounded-full bg-(--accent) px-3.5 text-[0.7647rem] font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60',
        compact && 'px-3')}>
      <UserPlus className="size-3.5" aria-hidden /> {followsYou ? 'Follow back' : 'Follow'}
    </button>
  )
}

export function PersonRow({ user, reason, status, followsYou, onDismiss, onFollowed, onError }: {
  user: FindUser; reason?: string; status: FindStatus; followsYou?: boolean
  onDismiss?: () => void; onFollowed?: (s: FindStatus) => void; onError?: (msg: string) => void
}) {
  const sub = [user.handle ? `@${user.handle}` : '', reason ?? ''].filter(Boolean).join(' · ')
  return (
    <li className="flex min-h-16 items-center gap-3 px-3.5 py-2.5">
      <PersonAvatar p={user} size={44} />
      <button type="button" onClick={() => openPerson(user.id)} className="min-w-0 flex-1 text-left">
        <span className="block truncate text-[0.9412rem] font-medium text-(--text)">{user.name}</span>
        {sub && <span className="block truncate text-[0.7059rem] text-(--text-muted)">{sub}</span>}
      </button>
      <FollowButton uid={user.id} status={status} followsYou={followsYou} onDone={onFollowed} onError={onError} />
      {onDismiss && (
        <button type="button" onClick={onDismiss} aria-label={`Hide ${user.name}`}
          className="-mr-1.5 flex size-9 shrink-0 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)">
          <X className="size-4" aria-hidden />
        </button>
      )}
    </li>
  )
}
