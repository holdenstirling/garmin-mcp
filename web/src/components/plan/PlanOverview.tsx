// "Plan overview": what the plan prescribes from today to race day. Each phase with its dates,
// weeks and hours, what it's for, and the weekly hours chart (tap a week to open it).
import { Sheet } from '@/components/ui/Sheet'
import { PHASE_LABEL, placedEventLabel, type BuiltPlan, type PlanWeekBuilt } from '@/lib/plan'
import { cn } from '@/lib/utils'
import { PhaseStrip, fmtDay } from './PlanParts'

const PHASE_INFO: Record<PlanWeekBuilt['phase'], string> = {
  base: 'Mostly easy miles that build your aerobic engine and the habit of training. Volume rises slowly, with a lighter week every few weeks so your body absorbs the work.',
  build: 'Workouts get more specific: tempo and threshold efforts, longer long sessions. Still mostly easy, with one or two harder days a week.',
  peak: 'Your biggest, most race-like weeks: race-pace work and the longest sessions. Recovery matters most here.',
  taper: 'Volume drops while some intensity stays, so you arrive fresh and sharp. Feeling restless is normal.',
  race: 'Short, easy sessions with a few quick openers. Rest, fuel and get to the start line ready.',
}

type Block = { phase: PlanWeekBuilt['phase']; first: PlanWeekBuilt; last: PlanWeekBuilt; weeks: PlanWeekBuilt[] }

function blocks(plan: BuiltPlan): Block[] {
  const out: Block[] = []
  for (const w of plan.weeks) {
    const b = out[out.length - 1]
    if (b && b.phase === w.phase) { b.last = w; b.weeks.push(w) } else out.push({ phase: w.phase, first: w, last: w, weeks: [w] })
  }
  return out
}

export function PlanOverview({ plan, onWeek, onClose }: { plan: BuiltPlan; onWeek: (index: number) => void; onClose: () => void }) {
  const cur = plan.current_week
  return (
    <Sheet title="Plan overview" onClose={onClose} bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <p className="text-[0.8235rem] leading-snug text-(--text-secondary)">
        {plan.weeks.length} weeks to race day ({fmtDay(plan.race_date, { weekday: 'short', month: 'short', day: 'numeric' })}),
        building from about {plan.start_hours}h to {plan.peak_hours}h a week. Tap a week to open it.
      </p>
      <div className="rounded-xl border border-(--border) bg-(--bg-surface) p-3">
        <PhaseStrip plan={plan} selected={cur ?? undefined} onSelect={(i) => { onWeek(i); onClose() }} />
      </div>
      <ol className="flex flex-col gap-2">
        {blocks(plan).map((b) => {
          const now = cur != null && b.first.index <= cur && cur <= b.last.index
          const hrs = b.weeks.map((w) => w.hours)
          const lastDay = b.last.days[b.last.days.length - 1]!.date
          return (
            <li key={`${b.phase}-${b.first.index}`}
              className={cn('flex flex-col gap-1 rounded-xl border bg-(--bg-surface) p-3.5', now ? 'border-(--accent)' : 'border-(--border)')}>
              <div className="flex items-center gap-2">
                <span className={cn('size-2.5 shrink-0 rounded-full', `phase-${b.phase}`)} aria-hidden />
                <p className="flex-1 text-[0.8824rem] font-semibold text-(--text)">{PHASE_LABEL[b.phase]}{now && <span className="ml-1.5 text-[0.7059rem] font-semibold text-(--accent)">You're here</span>}</p>
                <button type="button" onClick={() => { onWeek(b.first.index); onClose() }}
                  className="hit-44 text-[0.7059rem] font-medium text-(--accent)">Open</button>
              </div>
              <p className="font-mono text-[0.7059rem] tabular-nums text-(--text-muted)">
                {fmtDay(b.first.days[0]!.date, { month: 'short', day: 'numeric' })} – {fmtDay(lastDay, { month: 'short', day: 'numeric' })}
                {' · '}{b.weeks.length === 1 ? `week ${b.first.index}` : `weeks ${b.first.index}–${b.last.index}`}
                {' · '}{Math.min(...hrs) === Math.max(...hrs) ? `${hrs[0]}h` : `${Math.min(...hrs)}–${Math.max(...hrs)}h`} a week
              </p>
              <p className="text-[0.7647rem] leading-snug text-(--text-secondary)">{PHASE_INFO[b.phase]}</p>
            </li>
          )
        })}
      </ol>
      {plan.events.length > 0 && (
        <div className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Also in this plan</p>
          <ul className="flex flex-col gap-0.5 text-[0.7647rem] text-(--text-secondary)">
            {plan.events.map((e) => <li key={`${e.name}-${e.date}`}>{e.name} · {fmtDay(e.date, { month: 'short', day: 'numeric' })} · {placedEventLabel(e)}</li>)}
          </ul>
        </div>
      )}
    </Sheet>
  )
}
