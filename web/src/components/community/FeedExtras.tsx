// What keeps the Feed alive on rest days (server: feedlife.py), on the first page of the main
// Feed: the Monday crew recap (last week, only people who share workouts), club runs and
// friends' shared races coming up (club runs I'm already going to stay in "You're going"), and
// who just joined my clubs. No health numbers from anyone who didn't share them.
import { useState } from 'react'
import { CalendarDays, Flag, MapPin, PartyPopper, Trophy, UserPlus, X } from 'lucide-react'
import { fmtDist, fmtDuration } from '@/lib/format'
import { meetupWhen, rsvpMeetup, type FeedExtras as Extras, type LifeJoined, type LifeRecap, type LifeShout, type LifeUpcoming } from '@/lib/community'
import { cn } from '@/lib/utils'

const RECAP_KEY = 'rabbt.recap.hidden'

function names(ps: { name: string }[], total: number): string {
  const n = ps.map((p) => p.name)
  if (!n.length) return `${total} ${total === 1 ? 'person' : 'people'}`
  const rest = total - n.length
  if (rest > 0) return `${n.join(', ')} and ${rest} more`
  return n.length > 1 ? `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}` : n[0]
}

function raceWhen(day: string): string {
  const d = new Date(`${day}T12:00:00`)
  const days = Math.round((d.getTime() - new Date().setHours(12, 0, 0, 0)) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days < 7) return `In ${days} days`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function FeedExtras({ extras, imperial, onOpenClub }: {
  extras: Extras | null | undefined; imperial: boolean; onOpenClub?: (id: string) => void
}) {
  if (!extras) return null
  const upcoming = extras.upcoming.filter((u) => !(u.kind === 'meetup' && u.my_rsvp === 'going'))
  return (
    <>
      {extras.recap && <Recap r={extras.recap} imperial={imperial} />}
      {upcoming.length > 0 && <Upcoming items={upcoming} onOpenClub={onOpenClub} />}
      {extras.joined.map((j) => <Joined key={`${j.club.id}-${j.ts}`} j={j} onOpenClub={onOpenClub} />)}
    </>
  )
}

// ------------------------------------------------------------------ recap --
function shoutLine(s: LifeShout, imperial: boolean): string {
  switch (s.kind) {
    case 'most': return `${s.person.name} showed up ${s.workouts} times`
    case 'longest': return `${s.person.name}: longest effort, ${fmtDuration(s.minutes)} (${s.title.toLowerCase()})`
    case 'farthest': return `${s.person.name}: farthest, ${fmtDist(s.km, imperial, null, { decimals: 1 })}`
  }
}

function Recap({ r, imperial }: { r: LifeRecap; imperial: boolean }) {
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(RECAP_KEY) === r.week } catch { return false } })
  if (hidden) return null
  const hide = () => { setHidden(true); try { localStorage.setItem(RECAP_KEY, r.week) } catch { /* this visit only */ } }
  return (
    <section aria-label="Last week with your crew" className="relative flex flex-col gap-3 rounded-2xl bg-(--accent) p-5 text-(--on-fill)">
      <button type="button" aria-label="Hide this week's recap" onClick={hide}
        className="absolute right-1.5 top-1.5 flex size-11 items-center justify-center rounded-full opacity-80 active:opacity-100">
        <X className="size-5" aria-hidden />
      </button>
      <p className="m-0 flex items-center gap-2 text-meta font-semibold opacity-90">
        <PartyPopper className="size-4" aria-hidden /> Last week, your crew
      </p>
      <div className="grid grid-cols-3 gap-2">
        {([
          [fmtDist(r.km, imperial, null, { decimals: r.km >= 100 ? 0 : 1 }), 'together'],
          [String(r.workouts), r.workouts === 1 ? 'workout' : 'workouts'],
          [String(r.people), r.people === 1 ? 'person' : 'people'],
        ] as const).map(([v, label]) => (
          <div key={label} className="flex flex-col">
            <span className="text-title font-bold leading-tight tabular-nums">{v}</span>
            <span className="text-meta opacity-90">{label}</span>
          </div>
        ))}
      </div>
      {r.shoutouts.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {r.shoutouts.map((s) => (
            <li key={s.kind} className="flex items-start gap-2 text-small font-medium leading-snug">
              <Trophy className="mt-0.5 size-4 shrink-0" aria-hidden />{shoutLine(s, imperial)}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// --------------------------------------------------------------- upcoming --
function Upcoming({ items, onOpenClub }: { items: LifeUpcoming[]; onOpenClub?: (id: string) => void }) {
  return (
    <section aria-labelledby="life-up-h" className="flex flex-col gap-3">
      <h2 id="life-up-h" className="section-title m-0 px-1">Coming up with your crew</h2>
      <div className="-mx-5 flex snap-x gap-3 overflow-x-auto px-5 pb-1 no-scrollbar">
        {items.map((u) => u.kind === 'meetup'
          ? <MeetupTile key={`m-${u.meetup_id}-${u.when}`} m={u} onOpenClub={onOpenClub} />
          : <RaceTile key={`r-${u.title}-${u.when}`} r={u} />)}
      </div>
    </section>
  )
}

const tile = 'flex w-[15rem] shrink-0 snap-start flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-4 text-left'

function MeetupTile({ m, onOpenClub }: { m: Extract<LifeUpcoming, { kind: 'meetup' }>; onOpenClub?: (id: string) => void }) {
  const [rsvp, setRsvp] = useState(m.my_rsvp)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const count = m.count + (rsvp === 'going' && m.my_rsvp !== 'going' ? 1 : 0)
  async function go() {
    setBusy(true); setNote(null)
    try { await rsvpMeetup(m.club.id, m.meetup_id, 'going'); setRsvp('going') }
    catch (e) { setNote((e as Error).message || 'Open the club to RSVP.') }
    finally { setBusy(false) }
  }
  return (
    <div className={tile}>
      <button type="button" onClick={() => onOpenClub?.(m.club.id)} className="flex flex-col gap-1 text-left active:opacity-80">
        <span className="flex items-center gap-1.5 text-meta font-semibold text-(--accent)">
          <CalendarDays className="size-4" aria-hidden />{meetupWhen(m.when)}
        </span>
        <span className="line-clamp-2 text-body-lg font-semibold leading-snug text-(--text)">{m.title}</span>
        <span className="truncate text-meta text-(--text-secondary)"><span aria-hidden>{m.club.emoji} </span>{m.club.name}</span>
        {m.where && (
          <span className="flex items-center gap-1 text-meta text-(--text-muted)">
            <MapPin className="size-4 shrink-0" aria-hidden /><span className="truncate">{m.where}</span>
          </span>
        )}
        <span className="text-meta text-(--text-secondary)">
          {count > 0 ? `${m.people.length ? names(m.people, count) : `${count}`} going` : 'Be the first one in'}
        </span>
      </button>
      {rsvp === 'going' ? (
        <span role="status" className="mt-1 inline-flex min-h-11 items-center justify-center rounded-lg bg-(--accent-subtle) text-body font-semibold text-(--accent)">You're in 🐇</span>
      ) : (
        <button type="button" disabled={busy} onClick={() => void go()}
          className={cn('mt-1 inline-flex min-h-11 items-center justify-center rounded-lg bg-(--accent) text-body font-semibold text-(--on-fill) active:opacity-90', busy && 'opacity-60')}>
          {busy ? 'Saving…' : "I'm going"}
        </button>
      )}
      {note && <span className="text-meta text-(--text-muted)">{note}</span>}
    </div>
  )
}

function RaceTile({ r }: { r: Extract<LifeUpcoming, { kind: 'race' }> }) {
  return (
    <div className={tile}>
      <span className="flex items-center gap-1.5 text-meta font-semibold text-(--accent)"><Flag className="size-4" aria-hidden />{raceWhen(r.when)}</span>
      <span className="line-clamp-2 text-body-lg font-semibold leading-snug text-(--text)">{r.title}</span>
      {r.distance && <span className="text-meta text-(--text-secondary)">{r.distance}</span>}
      <span className="text-meta text-(--text-secondary)">{names(r.people, r.people.length)} {r.people.length === 1 ? 'is' : 'are'} racing. Cheer them on!</span>
    </div>
  )
}

// ----------------------------------------------------------------- joined --
function Joined({ j, onOpenClub }: { j: LifeJoined; onOpenClub?: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onOpenClub?.(j.club.id)}
      className="flex min-h-14 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3 text-left active:bg-(--bg-inset)">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-(--accent)" aria-hidden>
        <UserPlus className="size-5" />
      </span>
      <span className="min-w-0 flex-1 text-body leading-snug text-(--text)">
        <span className="font-semibold">{names(j.people, j.count)}</span> joined <span aria-hidden>{j.club.emoji} </span>{j.club.name}. Say hi!
      </span>
    </button>
  )
}
