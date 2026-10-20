// The two things most people come to rabbt for, side by side at the top of Home: things to do
// near you (clubs, events, meetups, or start your own) and your training plan. Everything else
// on Home sits below. Big, plain, one tap each.
import { CalendarDays, ChevronRight, MapPin, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'

function Tile({ icon, title, line, onClick, tone }: {
  icon: React.ReactNode; title: string; line: string; onClick: () => void; tone: 'accent' | 'brand'
}) {
  return (
    <button type="button" onClick={onClick}
      className={cn('flex min-h-[132px] min-w-0 flex-col items-start gap-2 rounded-2xl border p-4 text-left active:scale-[0.99]',
        tone === 'accent' ? 'border-(--accent)/30 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <span className="flex size-10 items-center justify-center rounded-xl bg-(--accent) text-(--on-fill)">{icon}</span>
      <span className="flex w-full items-center gap-1 text-body-lg font-semibold leading-tight text-(--text)">
        <span className="min-w-0 flex-1">{title}</span><ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
      </span>
      <span className="text-small leading-snug text-(--text-secondary)">{line}</span>
    </button>
  )
}

export function HomeStart({ hasPlan, planLine, onLocal, onNewEvent, onPlan, onSetup }: {
  hasPlan: boolean
  /** "Today: Easy run, 30 min" when there's a plan */
  planLine?: string | null
  onLocal: () => void
  onNewEvent: () => void
  onPlan: () => void
  onSetup: () => void
}) {
  return (
    <section aria-label="Start here" className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3">
        <Tile tone="accent" icon={<MapPin className="size-5" aria-hidden />} title="Near you"
          line="Clubs, group runs, leagues and events" onClick={onLocal} />
        <Tile tone="brand" icon={<CalendarDays className="size-5" aria-hidden />} title={hasPlan ? 'Your plan' : 'Get a plan'}
          line={hasPlan ? (planLine || 'See your weeks and adjust') : 'For a race or just to get fitter'} onClick={hasPlan ? onPlan : onSetup} />
      </div>
      <button type="button" onClick={onNewEvent}
        className="inline-flex min-h-11 items-center gap-1.5 self-start px-1 text-small font-semibold text-(--accent)">
        <Plus className="size-4" aria-hidden /> Create an event or meetup
      </button>
    </section>
  )
}
