// Rabbit home in race week (server: raceweek.py): one card above Up next for the 7 days before an
// A/B/main race (countdown, taper line, today's session, race grade, packing ring), and a short
// "Friends racing today" list (mutual followers who turned on Track me). Both hide when there's
// nothing to show or the request fails; no GPS, so friends' times only move when a watch syncs.
import { useEffect, useState } from 'react'
import { Flag, Radio } from 'lucide-react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { fmtDuration } from '@/lib/format'
import { getFriendsRacing, getRaceWeekCard, statusLine, type FriendRacing, type RaceWeekCard as Card } from '@/lib/raceweek'
import { friendPhotoUrl } from '@/lib/social'
import { cn } from '@/lib/utils'

function PackRing({ done, total }: { done: number; total: number }) {
  const r = 15, c = 2 * Math.PI * r, pct = total ? Math.min(1, done / total) : 0
  return (
    <span className="relative flex size-11 shrink-0 items-center justify-center" role="img" aria-label={`Packed ${done} of ${total}`}>
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="4" className="stroke-(--bg-elevated)" />
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="4" strokeLinecap="round"
          className={cn('transition-all duration-700', pct >= 1 ? 'stroke-(--brand)' : 'stroke-(--accent)')}
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <span aria-hidden className="font-mono text-[0.6471rem] font-semibold text-(--text)">{done}/{total}</span>
    </span>
  )
}

/** Seconds since the fetch, for the "racing" lines (status only moves when the server says so). */
function useTicker(on: boolean): number {
  const [t0] = useState(() => Date.now())
  const [now, setNow] = useState(t0)
  useEffect(() => {
    if (!on) return
    const id = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(id)
  }, [on])
  return Math.round((now - t0) / 1000)
}

function countdown(days: number): string {
  return days === 0 ? 'Race day' : days === 1 ? 'Tomorrow' : `${days} days to go`
}

export function RaceWeekCard({ refreshKey = 0, onOpen }: { refreshKey?: number; onOpen: (eventId: string) => void }) {
  const [card, setCard] = useState<Card | null>(null)
  const [friends, setFriends] = useState<FriendRacing[]>([])
  useEffect(() => {
    getRaceWeekCard().then((r) => setCard(r.raceweek), () => setCard(null))
    getFriendsRacing().then((r) => setFriends(r.friends), () => setFriends([]))
  }, [refreshKey])
  const since = useTicker(friends.some((f) => f.state === 'racing'))
  if (!card && !friends.length) return null
  return (
    <>
      {card && (
        <section aria-label="Race week"
          className="mx-4 mt-3 shrink-0 rounded-xl border border-(--brand)/30 bg-(--bg-surface) px-3 pb-3 pt-2.5 shadow-sm">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-(--brand) text-(--on-fill)">
              <Flag className="size-4" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
                {card.race_day ? 'Race day' : 'Race week'}
              </span>
              <span className="block truncate text-[0.9412rem] font-semibold leading-tight text-(--text)">{card.event.name}</span>
              <span className="block font-display text-[1.0588rem] leading-tight text-(--brand)">{countdown(card.days)}</span>
            </span>
            {card.packing.total > 0 && <PackRing done={card.packing.done} total={card.packing.total} />}
          </div>
          <p className="mt-1.5 text-[0.7647rem] leading-snug text-(--text-secondary)">{card.taper.text}</p>
          {(card.today.length > 0 || card.readiness || card.tracking) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {card.today.slice(0, 2).map((s) => (
                <span key={`${s.id}-${s.title}`} className="rounded-full border border-(--border) px-2 py-0.5 text-[0.7059rem] text-(--text)">
                  Today: {s.title}{s.minutes ? ` · ${fmtDuration(s.minutes)}` : ''}
                </span>
              ))}
              {card.readiness && (
                <span className="rounded-full border border-(--accent)/30 bg-(--accent-subtle) px-2 py-0.5 text-[0.7059rem] font-medium text-(--accent)">
                  Race grade {card.readiness.grade}
                </span>
              )}
              {card.tracking && (
                <span className="inline-flex items-center gap-1 rounded-full border border-(--border) px-2 py-0.5 text-[0.7059rem] text-(--text-secondary)">
                  <Radio className="size-3" aria-hidden /> Friends can follow
                </span>
              )}
            </div>
          )}
          <div className="mt-2.5">
            <Button variant="primary" className="h-11 px-4 text-[0.8235rem]" onClick={() => onOpen(card.event.id)}>
              {card.race_day ? 'Open race day' : 'Race-week plan'}
            </Button>
          </div>
        </section>
      )}
      {friends.length > 0 && (
        <section aria-label="Friends racing today" className="mx-4 mt-2 shrink-0 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2">
          <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Friends racing today</p>
          <ul className="mt-1 flex flex-col gap-1.5">
            {friends.slice(0, 4).map((f) => (
              <li key={`${f.user?.id}-${f.event.id}`} className="flex items-center gap-2">
                <Avatar name={f.user?.name ?? 'Friend'} picture={f.user?.picture ?? ''} photo={f.user ? friendPhotoUrl(f.user) : null} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.8235rem] text-(--text)">{f.user?.name ?? 'Friend'} · {f.event.name}</span>
                  <span className={cn('block truncate text-[0.7059rem]', f.state === 'finished' ? 'font-medium text-(--accent)' : 'text-(--text-secondary)')}>
                    {statusLine(f, f.state === 'racing' && f.elapsed_s != null ? f.elapsed_s + since : null)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[0.6471rem] text-(--text-muted)">Live times when their watch syncs. No live location.</p>
        </section>
      )}
    </>
  )
}
