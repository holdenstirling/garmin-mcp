// Shared pieces of the built plan: the phase strip (one bar per week) and a compact week list.
import { Activity, Bike, Dumbbell, Flag, Footprints, Layers, Moon, Waves } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Sport } from '@/lib/api'
import { KIND_LABEL, PHASE_LABEL, fmtMin, type BuiltPlan, type PlanSession, type PlanWeekBuilt } from '@/lib/plan'

export const SPORT_ICON: Record<Sport, typeof Bike> = {
  swim: Waves, bike: Bike, run: Footprints, brick: Layers, strength: Dumbbell, rest: Moon, other: Activity,
}
export const SPORT_LABEL: Record<Sport, string> = {
  swim: 'Swim', bike: 'Bike', run: 'Run', brick: 'Brick', strength: 'Strength', rest: 'Rest', other: 'Other',
}

export function fmtDay(date: string, opts: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' }) {
  return new Date(`${date}T12:00:00`).toLocaleDateString([], opts)
}
/** The device's local date. Prefer the server's (``planToday``) where a plan is loaded. */
export const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
/** "Today" in the athlete's time zone, as the server sees it (the device's as a fallback). */
export const planToday = (plan: BuiltPlan | null | undefined) => plan?.today ?? todayStr()

export function weekPhaseLabel(w: PlanWeekBuilt) {
  return w.recovery && w.phase !== 'taper' && w.phase !== 'race' ? `${PHASE_LABEL[w.phase]} · recovery` : PHASE_LABEL[w.phase]
}

export function sessionMinutes(s: PlanSession) {
  return s.minutes ?? s.legs.reduce((a, l) => a + l.minutes, 0)
}

/** One bar per week, height = planned hours, colored by phase. Tap a bar to pick that week. */
export function PhaseStrip({ plan, selected, onSelect }: {
  plan: BuiltPlan; selected?: number; onSelect?: (index: number) => void
}) {
  const max = Math.max(...plan.weeks.map((w) => w.hours), 1)
  const phases = [...new Set(plan.weeks.map((w) => w.phase))]
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-14 items-end gap-[2px]" role={onSelect ? 'listbox' : undefined} aria-label="Weeks">
        {plan.weeks.map((w) => {
          const cur = w.index === plan.current_week
          const sel = selected === w.index
          return (
            <button key={w.index} type="button" disabled={!onSelect} onClick={() => onSelect?.(w.index)}
              aria-label={`Week ${w.index}: ${weekPhaseLabel(w)}, ${w.hours} hours`} aria-selected={sel}
              className="flex h-full min-w-0 flex-1 flex-col justify-end disabled:cursor-default">
              <span className={cn('block w-full rounded-t-[3px] transition-opacity', `phase-${w.recovery && w.phase !== 'taper' && w.phase !== 'race' ? 'recovery' : w.phase}`,
                selected != null && !sel && 'opacity-45', cur && 'ring-1 ring-(--brand) ring-offset-1 ring-offset-(--bg-surface)')}
                style={{ height: `${Math.max(10, (w.hours / max) * 100)}%` }} />
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {phases.map((p) => (
          <span key={p} className="flex items-center gap-1.5 text-[0.6471rem] text-(--text-muted)">
            <span className={cn('size-2 rounded-full', `phase-${p}`)} />{PHASE_LABEL[p]}
          </span>
        ))}
        <span className="ml-auto font-mono text-[0.6471rem] text-(--text-muted)">{plan.weeks.length} wks · peak {plan.peak_hours}h</span>
      </div>
    </div>
  )
}

/** A session as one line: icon, title, duration, synced mark. */
export function SessionLine({ s, onClick, unread }: { s: PlanSession; onClick?: () => void; unread?: boolean }) {
  const Icon = s.kind === 'race' ? Flag : SPORT_ICON[s.sport] ?? Activity
  const mins = sessionMinutes(s)
  const rest = s.sport === 'rest'
  return (
    <button type="button" onClick={onClick} disabled={!onClick}
      className="flex w-full items-center gap-2.5 py-1.5 text-left disabled:cursor-default">
      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-lg',
        rest ? 'bg-(--bg-elevated) text-(--text-muted)' : s.kind === 'race' ? 'bg-(--brand) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
        <Icon className="size-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn('block truncate text-[0.8235rem]', rest ? 'text-(--text-muted)' : 'text-(--text)')}>{s.title}</span>
        {!rest && (
          <span className="block truncate text-[0.6471rem] text-(--text-muted)">
            {KIND_LABEL[s.kind] ?? s.kind}{mins ? ` · ${fmtMin(mins)}` : ''}{s.meters ? ` · ${s.meters} m` : ''}
          </span>
        )}
      </span>
      {unread && <span className="size-2 shrink-0 rounded-full bg-(--accent)" aria-label="New coach message" />}
      {s.synced && <span className="shrink-0 rounded-full bg-(--accent-subtle) px-2 py-0.5 font-mono text-[0.6471rem] uppercase tracking-wider text-(--accent)">Garmin</span>}
    </button>
  )
}

/** Read-only week: header plus each day's sessions. */
export function WeekPreview({ week }: { week: PlanWeekBuilt }) {
  return (
    <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      <div className="flex items-baseline gap-2 border-b border-(--border) px-4 py-2.5">
        <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          Week {week.index} · {weekPhaseLabel(week)}
        </span>
        <span className="ml-auto font-mono text-[0.6471rem] text-(--text-muted)">{week.hours}h</span>
      </div>
      {week.focus && <p className="px-4 pt-2.5 text-[0.7647rem] leading-snug text-(--text-secondary)">{week.focus}</p>}
      <div className="divide-y divide-(--border) px-4">
        {week.days.map((d) => (
          <div key={d.date} className="flex gap-3 py-1.5">
            <span className="w-10 shrink-0 pt-2 text-[0.6471rem] font-semibold uppercase text-(--text-muted)">{fmtDay(d.date, { weekday: 'short' })}</span>
            <div className="min-w-0 flex-1">
              {d.sessions.length ? d.sessions.map((s) => <SessionLine key={s.id} s={s} />)
                : <p className="py-2 text-[0.7647rem] text-(--text-muted)">Rest</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
