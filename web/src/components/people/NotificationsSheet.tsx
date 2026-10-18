// The notifications inbox (server: people.py inbox), opened from the bell in every tab header.
// Each row opens its exact item (Chat.tsx handles lib/people openTarget); opening one marks it
// read; "Mark all read" clears the dot.
import { useEffect, useState } from 'react'
import { Bell, CalendarCheck, Heart, MessageCircle, UserPlus, Users, X } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { Avatar } from '@/components/Avatar'
import { RabbitLoader } from '@/components/RabbitLoader'
import { timeAgo } from '@/lib/dm'
import { getNotifications, markNotificationsRead, notifsChanged, openTarget, personPhoto, type Notif } from '@/lib/people'
import { acceptRequest, declineRequest } from '@/lib/social'
import { FollowButton } from '@/components/friends/PersonRows'

const KIND_ICON: Record<string, typeof Bell> = {
  dm: MessageCircle, dm_request: MessageCircle, follow_request: UserPlus, follower: UserPlus,
  kudos: Heart, comment: MessageCircle, post: Users, club_invite: Users, race: CalendarCheck,
}

export function NotificationsSheet({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<Notif[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getNotifications().then((r) => setItems(r.items), (e: Error) => setError(e.message)) }, [])
  const unread = items?.filter((i) => i.unread).length ?? 0

  function open(n: Notif) {
    void markNotificationsRead([n.key]).then(notifsChanged, () => {})
    onClose()
    openTarget(n.open)
  }
  async function readAll() {
    try { const r = await markNotificationsRead(); setItems(r.items); notifsChanged() } catch (e) { setError((e as Error).message) }
  }

  return (
    <Sheet title="Notifications" onClose={onClose}
      actions={unread > 0 ? <Button variant="ghost" className="h-9 px-2.5 text-[0.7647rem]" onClick={() => void readAll()}>Mark all read</Button> : undefined}>
      {!items && !error && <RabbitLoader className="py-10" label="Loading notifications" />}
      {error && <p className="px-4 py-10 text-center text-[0.8235rem] text-(--text-muted)" role="alert">{error}</p>}
      {items && items.length === 0 && (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <Bell className="size-6 text-(--text-muted)" aria-hidden />
          <p className="text-[0.8235rem] font-medium text-(--text)">You're all caught up</p>
          <p className="text-[0.7647rem] text-(--text-muted)">Kudos, comments, messages, new followers and race reminders show up here.</p>
        </div>
      )}
      {items && items.length > 0 && (
        <ul className="flex flex-col pb-3" aria-label={unread ? `${unread} unread` : 'Notifications'}>
          {items.map((n) => {
            const I = KIND_ICON[n.kind] ?? Bell
            return (
              <li key={n.key} className={`flex items-center ${n.unread ? 'bg-(--accent-subtle)/40' : ''}`}>
                <button type="button" onClick={() => open(n)}
                  className="flex min-h-14 min-w-0 flex-1 items-start gap-3 py-2.5 pl-4 pr-2 text-left active:bg-(--bg-inset)">
                  <span className="relative shrink-0">
                    {n.person ? <Avatar name={n.person.name} picture={n.person.picture ?? ''} photo={personPhoto(n.person)} size={36} />
                      : <span className="flex size-9 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)"><I className="size-4" aria-hidden /></span>}
                    {n.person && <span className="absolute -bottom-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full bg-(--bg) text-(--accent) ring-1 ring-(--border)"><I className="size-2.5" aria-hidden /></span>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block text-[0.8235rem] leading-snug ${n.unread ? 'font-semibold text-(--text)' : 'text-(--text-secondary)'}`}>{n.title}</span>
                    {n.body && <span className="line-clamp-2 block text-[0.7059rem] text-(--text-muted)">{n.body}</span>}
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                    <span className="text-[0.6471rem] text-(--text-muted)">{timeAgo(n.ts)}</span>
                    {n.unread && <span className="size-2 rounded-full bg-(--accent)" aria-label="Unread" />}
                  </span>
                </button>
                {n.kind === 'follower' && n.follow_back && n.person && (
                  <span className="shrink-0 pr-4"><FollowButton uid={n.person.id} status="none" followsYou compact /></span>
                )}
                {n.kind === 'follow_request' && n.edge_id && <RequestButtons edge={n.edge_id} />}
              </li>
            )
          })}
        </ul>
      )}
    </Sheet>
  )
}

/** Accept / decline a follow request right in the list. */
function RequestButtons({ edge }: { edge: string }) {
  const [done, setDone] = useState<'accepted' | 'declined' | null>(null)
  const [busy, setBusy] = useState(false)
  if (done) return <span className="shrink-0 pr-4 text-[0.7059rem] text-(--text-muted)">{done === 'accepted' ? 'Accepted' : 'Declined'}</span>
  const go = async (yes: boolean) => {
    setBusy(true)
    try { await (yes ? acceptRequest(edge) : declineRequest(edge)); setDone(yes ? 'accepted' : 'declined') } catch { /* stays */ } finally { setBusy(false) }
  }
  return (
    <span className="flex shrink-0 items-center gap-1 pr-3">
      <button type="button" disabled={busy} onClick={() => void go(true)}
        className="h-9 rounded-full bg-(--accent) px-3 text-[0.7059rem] font-semibold text-(--on-fill) active:opacity-80 disabled:opacity-60">Accept</button>
      <button type="button" disabled={busy} onClick={() => void go(false)} aria-label="Decline"
        className="flex size-9 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)"><X className="size-4" aria-hidden /></button>
    </span>
  )
}
