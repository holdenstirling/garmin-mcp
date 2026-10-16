// Rabbit home "This week": all seven days at a glance (each day's sessions with sport, title,
// time or distance and done / missed / planned), today highlighted, and this week's distance
// against the goal (plan calendar, builder plans). Tap a day: the Plan tab opens on that day
// (lib/openday.ts). Data: /api/plan/week (passed in) + /api/plan/calendar for mileage.
import { useEffect, useState } from 'react'
import { Activity, Check, ChevronRight, X } from 'lucide-react'
import type { PlannedSession, PlanWeek, WeekDay } from '@/lib/api'
import { fmtDist, fmtDuration } from '@/lib/format'
import { getCalendar, SPORT_DIST_LABEL, type DistSport, type Mileage } from '@/lib/plancal'
import { SPORT_ICON } from '@/components/plan/PlanParts'
import { weekTitle } from '@/components/week/WeekStrip'
import { cn } from '@/lib/utils'

const STATE_WORD = { done: 'done', missed: 'missed', planned: 'planned', rest: 'rest' } as const

function sessionLine(s: PlannedSession, imperial: boolean): string {
  const km = s.activity?.distance_km
  if (s.status === 'done' && km) return fmtDist(km, imperial, s.sport)
  const min = s.status === 'done' ? s.activity?.minutes ?? s.minutes : s.minutes
  return min ? fmtDuration(min) : ''
}

function StateMark({ st }: { st: PlannedSession['status'] }) {
  if (st === 'done') {
    return <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)" aria-hidden>
      <Check className="size-2.5" strokeWidth={4} /></span>
  }
  if (st === 'missed') {
    return <span className="flex size-4 shrink-0 items-center justify-center rounded-full border border-(--danger)/50 text-(--danger)" aria-hidden>
      <X className="size-2.5" strokeWidth={3} /></span>
  }
  return <span className={cn('size-4 shrink-0 rounded-full border', st === 'rest' ? 'border-transparent bg-(--bg-elevated)' : 'border-(--border-strong)')} aria-hidden />
}

function DayLine({ d, imperial, onOpen }: { d: WeekDay; imperial: boolean; onOpen: (date: string) => void }) {
  const work = d.sessions.filter((s) => s.status !== 'rest')
  const label = `${d.weekday}${d.today ? ', today' : ''}: ${work.length
    ? work.map((s) => `${s.title} ${STATE_WORD[s.status]}`).join(', ')
    : d.extra.length ? d.extra.map((a) => `${a.name} done`).join(', ') : 'rest'}. Open this day in your plan`
  return (
    <li>
      <button type="button" onClick={() => onOpen(d.date)} aria-label={label}
        className={cn('flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)',
          d.today && 'bg-(--accent-subtle)')}>
        <span className="flex w-9 shrink-0 flex-col items-center leading-none">
          <span className={cn('text-[0.6471rem] font-semibold uppercase tracking-wide', d.today ? 'text-(--accent)' : 'text-(--text-muted)')}>
            {d.weekday.slice(0, 3)}
          </span>
          <span className={cn('mt-0.5 font-mono text-[0.8235rem]', d.today ? 'font-semibold text-(--accent)' : 'text-(--text-secondary)')}>
            {Number(d.date.slice(8, 10))}
          </span>
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1" aria-hidden>
          {work.length === 0 && d.extra.length === 0 && (
            <span className="text-[0.7647rem] text-(--text-muted)">{d.sessions.length ? 'Rest day' : 'Nothing planned'}</span>
          )}
          {work.map((s, i) => {
            const Icon = SPORT_ICON[s.sport] ?? Activity
            const line = sessionLine(s, imperial)
            return (
              <span key={i} className="flex min-w-0 items-center gap-2">
                <StateMark st={s.status} />
                <Icon className="size-3.5 shrink-0 text-(--text-secondary)" />
                <span className={cn('min-w-0 flex-1 truncate text-[0.7647rem]', s.status === 'missed' ? 'text-(--text-muted) line-through' : 'text-(--text)')}>
                  {s.title}
                </span>
                {line && <span className="shrink-0 font-mono text-[0.7059rem] text-(--text-muted)">{line}</span>}
              </span>
            )
          })}
          {d.extra.map((a, i) => {
            const Icon = SPORT_ICON[a.sport] ?? Activity
            return (
              <span key={`x${i}`} className="flex min-w-0 items-center gap-2">
                <StateMark st="done" />
                <Icon className="size-3.5 shrink-0 text-(--text-secondary)" />
                <span className="min-w-0 flex-1 truncate text-[0.7647rem] text-(--text)">{a.name}</span>
                <span className="shrink-0 font-mono text-[0.7059rem] text-(--text-muted)">
                  {a.distance_km ? fmtDist(a.distance_km, imperial, a.sport) : fmtDuration(a.minutes)}
                </span>
              </span>
            )
          })}
        </span>
        <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
      </button>
    </li>
  )
}

/** This week's distance against the goal, for the sports that have one. */
function MileageBars({ m, imperial }: { m: Partial<Record<DistSport, Mileage>>; imperial: boolean }) {
  const rows = (Object.entries(m) as [DistSport, Mileage][]).filter(([, v]) => v.goal > 0 || v.done > 0)
  if (!rows.length) return null
  return (
    <div className="flex flex-col gap-2 border-t border-(--border) px-3.5 py-3">
      {rows.map(([sp, v]) => {
        const pct = v.goal > 0 ? Math.min(1, v.done / v.goal) : 1
        const text = `${fmtDist(v.done, imperial, sp)}${v.goal > 0 ? ` of ${fmtDist(v.goal, imperial, sp)}` : ''}`
        return (
          <div key={sp} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2 text-[0.7059rem]">
              <span className="text-(--text-secondary)">{SPORT_DIST_LABEL[sp]} this week</span>
              <span className="font-mono text-(--text)">{text}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-(--bg-elevated)" role="progressbar"
              aria-label={`${SPORT_DIST_LABEL[sp]} this week: ${text}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)}>
              <div className={cn('h-full rounded-full transition-all duration-700', pct >= 1 ? 'bg-(--brand)' : 'bg-(--accent)')}
                style={{ width: `${Math.max(pct * 100, v.done > 0 ? 4 : 0)}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function WeekPanel({ week, loading, error, onRetry, imperial, refreshKey, onOpenDay, onOpenPlan }: {
  week: PlanWeek | null; loading: boolean; error: boolean; onRetry: () => void
  imperial: boolean
  /** bump to re-read the mileage */
  refreshKey?: number
  onOpenDay: (date: string) => void
  onOpenPlan: () => void
}) {
  const [miles, setMiles] = useState<Partial<Record<DistSport, Mileage>> | null>(null)
  useEffect(() => {
    if (!week) return
    let live = true
    getCalendar().then((r) => { if (live) setMiles(r.cal?.weeks[week.start] ?? null) }, () => {})
    return () => { live = false }
  }, [week?.start, refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!week) {
    return (
      <section aria-label="This week" className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
        {error && !loading ? (
          <button type="button" onClick={onRetry} className="min-h-11 w-full text-left text-[0.7647rem] text-(--text-muted)">
            Couldn't load this week. <span className="underline">Retry</span>
          </button>
        ) : (
          <div className="flex flex-col gap-2" aria-label="Loading this week">
            <span className="skeleton h-3 w-40" aria-hidden />
            {[0, 1, 2, 3].map((i) => <span key={i} className="skeleton h-9" aria-hidden />)}
          </div>
        )}
      </section>
    )
  }
  const { done_sessions: done, planned_sessions: planned } = week.totals
  return (
    <section aria-label="This week" className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      <div className="flex items-center gap-2 border-b border-(--border) px-3.5 py-2">
        <h2 className="min-w-0 flex-1 truncate font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          {weekTitle(week)}
        </h2>
        {planned > 0 && <span className="shrink-0 font-mono text-[0.7059rem] text-(--text-secondary)">{done}/{planned} done</span>}
      </div>
      {week.garmin_error && <p className="px-3.5 pt-2 text-[0.7059rem] text-(--warning-text)">{week.garmin_error}</p>}
      <ul className="divide-y divide-(--border)">
        {week.days.map((d) => <DayLine key={d.date} d={d} imperial={imperial} onOpen={onOpenDay} />)}
      </ul>
      {miles && <MileageBars m={miles} imperial={imperial} />}
      <button type="button" onClick={onOpenPlan}
        className="flex min-h-11 w-full items-center justify-center gap-1 border-t border-(--border) text-[0.7647rem] font-medium text-(--accent) active:bg-(--bg-inset)">
        See full plan <ChevronRight className="size-3.5" aria-hidden />
      </button>
    </section>
  )
}
