// Rabbit home "This week": all seven days at a glance (each day's sessions with sport, title,
// time or distance and done / missed / planned), today highlighted, and this week's distance
// against the goal (plan calendar, builder plans) as the "Week at a glance" header (WeekGlance). Tap a day: the Plan tab opens on that day
// (lib/plancal openPlanDay). Data: /api/plan/week (passed in) + /api/plan/calendar for mileage.
import { useEffect, useState } from 'react'
import { Activity, Check, ChevronRight, X } from 'lucide-react'
import type { PlannedSession, PlanWeek, WeekDay } from '@/lib/api'
import { fmtDist, fmtDuration } from '@/lib/format'
import { getCalendar, SPORT_DIST_LABEL, type DistSport, type Mileage } from '@/lib/plancal'
import { SPORT_ICON } from '@/components/plan/PlanParts'
import { weekTitle } from '@/components/week/WeekStrip'
import { cn } from '@/lib/utils'
import { openWorkout } from '@/lib/workoutnav'
import { openActivity } from '@/lib/activitynav'
import { PlanDaySheet } from '@/components/week/PlanDaySheet'

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

function DayLine({ d, imperial, onOpen, onSheet }: {
  d: WeekDay; imperial: boolean; onOpen: (date: string) => void
  /** a plan-file day (sessions without ids): its full details sheet */
  onSheet: (d: WeekDay) => void
}) {
  const work = d.sessions.filter((s) => s.status !== 'rest')
  const dayLabel = `${d.weekday}${d.today ? ', today' : ''}`
  const summary = `${dayLabel}: ${work.length
    ? work.map((s) => `${s.title} ${STATE_WORD[s.status]}`).join(', ')
    : d.extra.length ? d.extra.map((a) => `${a.name} done`).join(', ') : 'rest'}. Open this day in your plan`
  // Each planned workout opens its own full page (lib/workoutnav); the date and the rest of the
  // row open the day in the Schedule.
  return (
    <li className={cn('flex items-stretch', d.today && 'bg-(--accent-subtle)')}>
      <button type="button" onClick={() => onOpen(d.date)} aria-label={summary}
        className="flex w-14 shrink-0 flex-col items-center justify-center py-2 pl-1.5 leading-none active:bg-(--bg-inset)">
        <span className={cn('text-[0.6471rem] font-semibold uppercase tracking-wide', d.today ? 'text-(--accent)' : 'text-(--text-muted)')}>
          {d.weekday.slice(0, 3)}
        </span>
        <span className={cn('mt-0.5 font-mono text-[0.8235rem]', d.today ? 'font-semibold text-(--accent)' : 'text-(--text-secondary)')}>
          {Number(d.date.slice(8, 10))}
        </span>
      </button>
      <span className="flex min-w-0 flex-1 flex-col justify-center py-1">
        {work.length === 0 && d.extra.length === 0 && (
          <button type="button" onClick={() => onOpen(d.date)} tabIndex={-1} aria-hidden
            className="flex min-h-11 items-center pr-3.5 text-left text-[0.7647rem] text-(--text-muted)">
            {d.sessions.length ? 'Rest day' : 'Nothing planned'}
          </button>
        )}
        {work.map((s, i) => {
          const Icon = SPORT_ICON[s.sport] ?? Activity
          const line = sessionLine(s, imperial)
          return (
            <button key={s.id ?? i} type="button" onClick={() => (s.id ? openWorkout(s.id, d.date) : onSheet(d))}
              aria-label={`${s.title}, ${STATE_WORD[s.status]}, ${dayLabel}. Open the workout`}
              className="flex min-h-11 min-w-0 items-center gap-2 pr-3 text-left active:bg-(--bg-inset)">
              <StateMark st={s.status} />
              <Icon className="size-3.5 shrink-0 text-(--text-secondary)" aria-hidden />
              <span className={cn('min-w-0 flex-1 truncate text-[0.7647rem]', s.status === 'missed' ? 'text-(--text-muted) line-through' : 'text-(--text)')}>
                {s.title}
              </span>
              {line && <span className="shrink-0 font-mono text-[0.7059rem] text-(--text-muted)">{line}</span>}
              <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
          )
        })}
        {d.extra.map((a, i) => {
          const Icon = SPORT_ICON[a.sport] ?? Activity
          return (
            <button key={`x${i}`} type="button" onClick={() => (a.id != null ? openActivity(a.id) : onOpen(d.date))}
              aria-label={`${a.name}, done, ${dayLabel}. ${a.id != null ? 'Open the workout' : 'Open this day'}`}
              className="flex min-h-11 min-w-0 items-center gap-2 pr-3 text-left active:bg-(--bg-inset)">
              <StateMark st="done" />
              <Icon className="size-3.5 shrink-0 text-(--text-secondary)" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-[0.7647rem] text-(--text)">{a.name}</span>
              <span className="shrink-0 font-mono text-[0.7059rem] text-(--text-muted)">
                {a.distance_km ? fmtDist(a.distance_km, imperial, a.sport) : fmtDuration(a.minutes)}
              </span>
              <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
          )
        })}
      </span>
    </li>
  )
}

const dayMinutes = (d: WeekDay) => {
  const work = d.sessions.filter((s) => s.status !== 'rest')
  const planned = work.reduce((n, s) => n + (s.minutes ?? 0), 0)
  const done = work.reduce((n, s) => n + (s.status === 'done' ? s.activity?.minutes ?? s.minutes ?? 0 : 0), 0)
    + d.extra.reduce((n, a) => n + (a.minutes ?? 0), 0)
  return { planned, done }
}

/** "Week at a glance": done vs planned (miles of the main distance sport when the plan has a
 *  goal for it, else hours), one mini bar per day (outline = planned, fill = done, today marked)
 *  and how the week is trending, with the session that makes up a shortfall. Tap: Schedule week. */
export function WeekGlance({ week, miles, imperial, onOpen }: {
  week: PlanWeek; miles: Partial<Record<DistSport, Mileage>> | null; imperial: boolean; onOpen: () => void
}) {
  const per = week.days.map(dayMinutes)
  const max = Math.max(30, ...per.map((x) => Math.max(x.planned, x.done)))
  const goals = miles ? (Object.entries(miles) as [DistSport, Mileage][]).filter(([, v]) => v.goal > 0) : []
  const sport = goals.length === 1 ? goals[0] : null  // one distance sport: its miles; multisport: hours
  // Plan progress counts planned sessions only (extra workouts don't make up a missed long run);
  // the headline still shows everything you did.
  const doneMin = per.reduce((n, x) => n + x.done, 0)
  const planMin = per.reduce((n, x) => n + x.planned, 0)
  const planDone = week.days.reduce((n, d) => n + d.sessions.reduce((m, s) => m + (s.status === 'done' ? s.minutes ?? s.activity?.minutes ?? 0 : 0), 0), 0)
  const ti = week.days.findIndex((d) => d.today)
  // Expected by now: everything planned before today, plus today's if it's already done.
  const dueMin = week.days.reduce((n, d, i) => n + d.sessions.reduce((m, s) =>
    m + (s.status !== 'rest' && (i < ti || (i === ti && s.status === 'done')) ? s.minutes ?? 0 : 0), 0), 0)
  const allDone = week.totals.planned_sessions > 0 && week.totals.done_sessions >= week.totals.planned_sessions
  const head = sport
    ? `${fmtDist(sport[1].done, imperial, sport[0])} of ${fmtDist(sport[1].goal, imperial, sport[0])}`
    : planMin > 0 && doneMin <= planMin ? `${fmtDuration(doneMin)} of ${fmtDuration(planMin)}`
    : planMin > 0 ? `${fmtDuration(doneMin)} done · ${fmtDuration(planMin)} planned`
    : doneMin > 0 ? `${fmtDuration(doneMin)} done` : 'No sessions yet'
  const unit = sport ? `${SPORT_DIST_LABEL[sport[0]].toLowerCase()} this week` : planMin > 0 ? 'training this week' : 'this week'
  let trend = ''
  let tone: 'ok' | 'behind' | 'ahead' = 'ok'
  if (allDone) { trend = 'Week done. Nice work.'; tone = 'ahead' }
  else if (planMin > 0 && ti >= 0) {
    const gap = dueMin - planDone
    if (gap <= dueMin * 0.1 + 5) {
      const left = week.days.slice(ti).reduce((n, d) => n + d.sessions.filter((x) => x.status === 'planned').length, 0)
      trend = left ? `On track · ${left} session${left === 1 ? '' : 's'} left` : 'On track'
    } else {
      tone = 'behind'
      const later = week.days.slice(ti + 1).flatMap((d) => d.sessions.filter((x) => x.status === 'planned' && (x.minutes ?? 0) > 0).map((x) => ({ d, s: x })))
      const big = later.sort((x, y) => (y.s.minutes ?? 0) - (x.s.minutes ?? 0))[0]
      const short = sport && planMin > 0 ? fmtDist(sport[1].goal * (gap / planMin), imperial, sport[0]) : fmtDuration(gap)
      trend = `Behind by ${short}${big ? `: ${big.d.weekday.slice(0, 3)} ${big.s.title.toLowerCase()} makes up most of it` : ''}`
    }
  }
  const label = `Week at a glance: ${head} ${unit}. ${trend}. Open this week in your schedule`
  return (
    <button type="button" onClick={onOpen} aria-label={label}
      className="flex w-full items-end gap-3 border-b border-(--border) px-3.5 py-3 text-left active:bg-(--bg-inset)">
      <span className="min-w-0 flex-1" aria-hidden>
        <span className="block font-mono text-[0.9412rem] font-semibold tabular-nums text-(--text)">{head}</span>
        <span className="block text-[0.6471rem] text-(--text-muted)">{unit}</span>
        {trend && (
          <span className={cn('mt-1 block text-[0.7059rem] font-medium leading-snug',
            tone === 'behind' ? 'text-(--warning-text)' : tone === 'ahead' ? 'text-(--accent)' : 'text-(--text-secondary)')}>{trend}</span>
        )}
      </span>
      <span className="flex h-12 shrink-0 items-end gap-1" aria-hidden>
        {per.map((x, i) => (
          <span key={week.days[i]!.date} className="flex flex-col items-center gap-0.5">
            <span className={cn('relative flex w-3 items-end overflow-hidden rounded-sm border',
              x.planned > 0 ? 'border-(--border-strong)' : 'border-transparent', week.days[i]!.today && 'ring-1 ring-(--accent)')}
              style={{ height: `${Math.max(4, (Math.max(x.planned, x.done) / max) * 36)}px` }}>
              <span className="w-full rounded-[1px] bg-(--accent)" style={{ height: `${x.planned || x.done ? Math.min(100, (x.done / Math.max(x.planned, x.done)) * 100) : 0}%` }} />
            </span>
            <span className={cn('text-[0.6471rem] leading-none', week.days[i]!.today ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
              {week.days[i]!.weekday.slice(0, 1)}
            </span>
          </span>
        ))}
      </span>
    </button>
  )
}

export function WeekPanel({ week, loading, error, onRetry, imperial, refreshKey, onOpenDay, onOpenPlan, onOpenWeek, onAskDay }: {
  week: PlanWeek | null; loading: boolean; error: boolean; onRetry: () => void
  /** Ask Rabbit from a plan-file day's sheet */
  onAskDay: (day: WeekDay, session?: PlannedSession) => void
  imperial: boolean
  /** bump to re-read the mileage */
  refreshKey?: number
  onOpenDay: (date: string) => void
  onOpenPlan: () => void
  /** the week view in Schedule (defaults to onOpenPlan) */
  onOpenWeek?: () => void
}) {
  const [miles, setMiles] = useState<Partial<Record<DistSport, Mileage>> | null>(null)
  const [sheetDay, setSheetDay] = useState<string | null>(null)
  const sheet = week?.days.find((x) => x.date === sheetDay) ?? null
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
            <span className="skeleton h-14" aria-hidden />
            {/* Seven day rows at their real height, so the panel doesn't jump when the week lands. */}
            {[0, 1, 2, 3, 4, 5, 6].map((i) => <span key={i} className="skeleton h-10" aria-hidden />)}
          </div>
        )}
      </section>
    )
  }
  return (
    <section aria-label="This week" className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      <div className="flex items-center gap-2 border-b border-(--border) px-3.5 py-2">
        <h2 className="min-w-0 flex-1 truncate font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
          {weekTitle(week)}
        </h2>
      </div>
      <WeekGlance week={week} miles={miles} imperial={imperial} onOpen={onOpenWeek ?? onOpenPlan} />
      {week.garmin_error && <p className="px-3.5 pt-2 text-[0.7059rem] text-(--warning-text)">{week.garmin_error}</p>}
      <ul className="divide-y divide-(--border)">
        {week.days.map((d) => <DayLine key={d.date} d={d} imperial={imperial} onOpen={onOpenDay} onSheet={(x) => setSheetDay(x.date)} />)}
      </ul>
      {sheet && <PlanDaySheet day={sheet} imperial={imperial} onClose={() => setSheetDay(null)} onAsk={onAskDay} />}
      <button type="button" onClick={onOpenPlan}
        className="flex min-h-11 w-full items-center justify-center gap-1 border-t border-(--border) text-[0.7647rem] font-medium text-(--accent) active:bg-(--bg-inset)">
        See full plan <ChevronRight className="size-3.5" aria-hidden />
      </button>
    </section>
  )
}
