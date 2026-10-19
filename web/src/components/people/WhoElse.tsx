// "Who else is doing this?" on a workout page (people you follow with the same sport this week)
// and an event page (people you follow, or who follow you, entered in the same race). Each
// person opens their profile; Invite sends them this workout / event as a card. `invite` adds
// "Invite friends to join" (your own planned sessions and races ahead).
import { useEffect, useState } from 'react'
import { UserPlus, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SectionLabel } from '@/components/ui/brand'
import { PersonAvatar, PersonLink } from '@/components/people/PersonLink'
import { fmtDay } from '@/components/plan/PlanParts'
import type { DMShare } from '@/lib/dm'
import { getAlsoDoing, inviteToJoin, sportWord, type AlsoDoing, type PersonRef } from '@/lib/people'

export function WhoElse({ sport, date, eventName, eventDate, share, invite }: {
  sport?: string; date?: string; eventName?: string; eventDate?: string
  share: DMShare; invite?: boolean
}) {
  const [d, setD] = useState<AlsoDoing | null>(null)
  useEffect(() => {
    let live = true
    const q = eventName && eventDate ? { event_name: eventName, event_date: eventDate } : { sport: sport && /^[a-z_]{2,20}$/.test(sport) ? sport : undefined, date }
    if (!('event_name' in q) && !q.sport) { setD({ same_sport: [], same_event: [] }); return }
    getAlsoDoing(q).then((r) => { if (live) setD(r) }, () => { if (live) setD({ same_sport: [], same_event: [] }) })
    return () => { live = false }
  }, [sport, date, eventName, eventDate])

  const rows: { p: PersonRef; line: string }[] = d ? [
    ...d.same_event.map((x) => ({ p: x.person, line: 'Entered too' })),
    ...d.same_sport.map((x) => ({ p: x.person, line: `${x.workout.title || sportWord(x.workout.sport)} · ${fmtDay(x.workout.date, { weekday: 'short' })}${x.count > 1 ? ` · ${x.count} this week` : ''}` })),
  ] : []
  if (!d || (!rows.length && !invite)) return null
  return (
    <section aria-label="Who else is doing this" className="flex flex-col gap-2">
      <SectionLabel>{eventName ? 'Who else is going?' : 'Who else is doing this?'}</SectionLabel>
      <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
        {rows.length === 0 && (
          <p className="flex items-center gap-2 px-3.5 py-3 text-small text-(--text-muted)">
            <Users className="size-5 shrink-0" aria-hidden /> None of your friends {eventName ? 'have this race on their calendar yet' : 'have done this this week yet'}.
          </p>
        )}
        {rows.map(({ p, line }) => (
          <div key={p.id} className="flex min-h-12 items-center gap-3 px-3.5 py-1.5">
            <PersonAvatar p={p} size={32} />
            <span className="min-w-0 flex-1">
              <PersonLink id={p.id} name={p.name} className="block truncate text-body font-medium text-(--text)" />
              <span className="block truncate text-meta text-(--text-muted)">{line}</span>
            </span>
            <Button variant="default" className="h-9 shrink-0 px-3 text-meta" aria-label={`Invite ${p.name}`}
              onClick={() => inviteToJoin(share, [p.id])}>Invite</Button>
          </div>
        ))}
        {invite && (
          <button type="button" onClick={() => inviteToJoin(share)}
            className="flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left text-body font-medium text-(--accent) active:bg-(--bg-inset)">
            <UserPlus className="size-5" aria-hidden /> Invite friends to join
          </button>
        )}
      </div>
    </section>
  )
}
