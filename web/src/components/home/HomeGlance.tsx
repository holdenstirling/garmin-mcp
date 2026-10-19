// rabbt home greeting: the date, hello, and the goal race with its countdown (the header's goal
// line hides on narrow phones, so the race lives here too). Streak, level and race grade are in
// Progress.
import { ChevronRight, Flag } from 'lucide-react'
import { RabbitNap } from '@/components/anim'

function greeting(now: Date): string {
  const h = now.getHours()
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function toGo(days: number): string {
  return days === 0 ? 'race day' : days === 1 ? 'tomorrow' : `${days} days to go`
}

export function HomeGreeting({ name, race, onRace }: {
  name: string | null | undefined
  /** the goal race and days until it (hidden once it's past) */
  race?: { title: string; days: number } | null
  /** tap the race line: its plan */
  onRace?: () => void
}) {
  const now = new Date()
  const first = name?.trim().split(/\s+/)[0]
  const h = now.getHours()
  const night = h >= 21 || h < 5  // rabbt's dozing off: a sleepy rabbit next to the greeting
  const r = race && race.days >= 0 ? race : null
  const raceText = r && (
    <span className="min-w-0"><span className="font-semibold text-(--text)">{r.title}</span> · {toGo(r.days)}</span>
  )
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1">
          <p className="m-0 text-small font-medium text-(--text-secondary)">
            {now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          <h2 className="m-0 font-display text-display-sm leading-tight text-(--brand)">{greeting(now)}{first ? `, ${first}` : ''}</h2>
        </div>
        {night && <RabbitNap size={30} mode="sleep" className="mb-1 shrink-0" />}
      </div>
      {r && (onRace ? (
        <button type="button" onClick={onRace} aria-label={`${r.title}, ${toGo(r.days)}. Open your plan`}
          className="-mx-1 flex min-h-11 items-center gap-2 self-start rounded-full px-1 text-left text-body text-(--text-secondary) active:opacity-70">
          <Flag className="size-5 shrink-0 text-(--accent)" aria-hidden />
          {raceText}
          <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      ) : (
        <p className="m-0 flex items-center gap-2 text-body text-(--text-secondary)">
          <Flag className="size-5 shrink-0 text-(--accent)" aria-hidden />{raceText}
        </p>
      ))}
      {night && <p className="m-0 text-meta text-(--text-muted)">rabbt's winding down. Sleep is training too.</p>}
    </div>
  )
}
