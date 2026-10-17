// Events on a plan calendar day (Day and Week views): the race, group run, league night or trip
// that day holds, so the plan and your events read as one schedule. Tap opens the event.
import { CalendarHeart, Flag, Plane, Repeat, Users } from 'lucide-react'
import { KIND_LABEL, type RaceEvent, type Weekday } from '@/lib/events'

const WD: Weekday[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const weekdayOf = (d: string) => WD[(new Date(`${d}T12:00:00`).getDay() + 6) % 7]!

/** Events happening on `d`: one-day, multi-day (date..end_date) or weekly repeats until `until`. */
export function eventsOn(events: RaceEvent[], d: string): RaceEvent[] {
  return events.filter((e) => {
    if (e.recurring) return d >= e.date && d <= (e.recurring.until || e.date) && weekdayOf(d) === e.recurring.weekday
    return e.end_date ? d >= e.date && d <= e.end_date : d === e.date
  })
}

export function DayEvents({ events, onOpen }: { events: RaceEvent[]; onOpen: (id: string) => void }) {
  return (
    <ul className="flex flex-col gap-1" aria-label="Events this day">
      {events.map((e) => {
        const kind = e.kind ?? 'race'
        const I = kind === 'race' ? Flag : kind === 'trip' ? Plane : kind === 'group_activity' ? Users : CalendarHeart
        return (
          <li key={e.id}>
            <button type="button" onClick={() => onOpen(e.id)}
              aria-label={`Event: ${e.name}, ${KIND_LABEL[kind]}${e.time ? ` at ${e.time}` : ''}${e.recurring ? ', repeats weekly' : ''}. Open the event`}
              className="flex min-h-11 w-full items-center gap-2.5 rounded-lg border border-(--accent)/30 bg-(--accent-subtle) px-3 py-1.5 text-left active:opacity-80">
              <I className="size-4 shrink-0 text-(--accent)" aria-hidden />
              <span className="min-w-0 flex-1" aria-hidden>
                <span className="block truncate text-[0.7647rem] font-semibold text-(--text)">{e.name}</span>
                <span className="block truncate text-[0.6471rem] text-(--text-muted)">
                  {KIND_LABEL[kind]}{e.time ? ` · ${e.time}` : ''}{e.location ? ` · ${e.location}` : ''}
                </span>
              </span>
              {e.recurring && <Repeat className="size-3.5 shrink-0 text-(--text-muted)" aria-hidden />}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
