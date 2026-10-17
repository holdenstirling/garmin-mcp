// "Plan overview": what the plan prescribes from today to race day. Each phase with its dates,
// weeks and hours, what it's for, and the weekly hours chart (tap a week to open it).
import { SlidersHorizontal } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { ChevronRight } from 'lucide-react'
import { RabbitNote } from '@/components/ui/brand'
import { PHASE_LABEL, placedEventLabel, type BuiltPlan, type PlanWeekBuilt } from '@/lib/plan'
import { cn } from '@/lib/utils'
import { PhaseStrip, fmtDay } from './PlanParts'

const PHASE_INFO: Record<PlanWeekBuilt['phase'], string> = {
  base: 'Mostly easy miles that build your aerobic engine and the habit of training. Volume rises slowly, with a lighter week every few weeks so your body absorbs the work.',
  build: 'Workouts get more specific: tempo and threshold efforts, longer long workouts. Still mostly easy, with one or two harder days a week.',
  peak: 'Your biggest, most race-like weeks: race-pace work and the longest workouts. Recovery matters most here.',
  taper: 'Volume drops while some intensity stays, so you arrive fresh and sharp. Feeling restless is normal.',
  race: 'Short, easy workouts with a few quick openers. Rest, fuel and get to the start line ready.',
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

export function PlanOverview({ plan, onWeek, onClose, onAdjust }: { plan: BuiltPlan; onWeek: (index: number) => void; onClose: () => void; onAdjust?: () => void }) {
  const cur = plan.current_week
  return (
    <Sheet title="Plan overview" onClose={onClose} bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <RabbitNote title="Your season">
        <p className="m-0 text-(--text)">
          <b className="font-semibold">{plan.weeks.length} weeks</b> to race day ({fmtDay(plan.race_date, { weekday: 'short', month: 'short', day: 'numeric' })}),
          building from about <b className="font-semibold">{plan.start_hours}h</b> to <b className="font-semibold">{plan.peak_hours}h</b> a week.
        </p>
        <p className="m-0 text-(--text-secondary)">Tap a bar or a phase to open that week.</p>
      </RabbitNote>
      {onAdjust && (
        <Button variant="default" className="h-11 gap-1.5 text-[0.8235rem]" onClick={onAdjust}>
          <SlidersHorizontal className="size-4" aria-hidden /> Adjust my plan
        </Button>
      )}
      <div className="rounded-xl border border-(--border) bg-(--bg-surface) p-3">
        <PhaseStrip plan={plan} selected={cur ?? undefined} onSelect={(i) => { onWeek(i); onClose() }} />
      </div>
      <ol className="flex flex-col gap-2">
        {blocks(plan).map((b) => {
          const now = cur != null && b.first.index <= cur && cur <= b.last.index
          const hrs = b.weeks.map((w) => w.hours)
          const lastDay = b.last.days[b.last.days.length - 1]!.date
          return (
            <li key={`${b.phase}-${b.first.index}`}>
              <button type="button" onClick={() => { onWeek(b.first.index); onClose() }}
                aria-label={`${PHASE_LABEL[b.phase]}${now ? ', you are here' : ''}: open week ${b.first.index}`}
                className={cn('flex w-full items-start gap-3 rounded-xl border bg-(--bg-surface) p-4 text-left active:bg-(--bg-inset)', now ? 'border-(--accent)' : 'border-(--border)')}>
                <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', `phase-${b.phase}`)} aria-hidden />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="flex flex-wrap items-baseline gap-x-2 text-[0.8824rem] font-semibold text-(--text)">
                    {PHASE_LABEL[b.phase]}{now && <span className="text-[0.7059rem] font-semibold text-(--accent)">You're here</span>}
                  </span>
                  <span className="flex flex-wrap gap-x-2 font-mono text-[0.7059rem] tabular-nums text-(--text-muted)">
                    <span className="whitespace-nowrap">{fmtDay(b.first.days[0]!.date, { month: 'short', day: 'numeric' })} – {fmtDay(lastDay, { month: 'short', day: 'numeric' })}</span>
                    <span className="whitespace-nowrap">· {b.weeks.length === 1 ? `week ${b.first.index}` : `weeks ${b.first.index}–${b.last.index}`}</span>
                    <span className="whitespace-nowrap">· {Math.min(...hrs) === Math.max(...hrs) ? `${hrs[0]}h` : `${Math.min(...hrs)}–${Math.max(...hrs)}h`} a week</span>
                  </span>
                  <span className="text-[0.7647rem] leading-snug text-(--text-secondary)">{PHASE_INFO[b.phase]}</span>
                </span>
                <ChevronRight className="mt-0.5 size-4 shrink-0 text-(--text-muted)" aria-hidden />
              </button>
            </li>
          )
        })}
      </ol>
      {plan.events.length > 0 && (
        <div className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) p-3.5">
          <p className="section-label m-0">Also in this plan</p>
          <ul className="flex flex-col gap-0.5 text-[0.7647rem] text-(--text-secondary)">
            {plan.events.map((e) => <li key={`${e.name}-${e.date}`}>{e.name} · {fmtDay(e.date, { month: 'short', day: 'numeric' })} · {placedEventLabel(e)}</li>)}
          </ul>
        </div>
      )}
    </Sheet>
  )
}
