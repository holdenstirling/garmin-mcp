// The plan week in two sizes, sharing PlanPins' day logic: seven compact dots (Today card's
// collapsed row on Rabbit) and the full day-by-day list (top of the Plan tab).
import { useState } from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PlannedSession, PlanWeek, WeekDay } from '@/lib/api'
import { DayRow, cap, dayState, fmtRange } from '@/components/chat/PlanPins'

const STATE_LABEL = {
  done: 'done', partial: 'partly done', missed: 'missed', planned: 'planned', rest: 'rest day',
  extra: 'extra workout', empty: 'nothing planned',
} as const

/** "Week 3 of 12 · Base · Oct 13–19" (falls back to "This week"). */
export function weekTitle(week: PlanWeek): string {
  const where = week.index && week.index > 0
    ? `Week ${week.index}${week.weeks ? ` of ${week.weeks}` : ''}${week.phase && week.phase !== 'post-race' ? ` · ${cap(week.phase)}` : ''}`
    : 'This week'
  return `${where} · ${fmtRange(week.start, week.end)}`
}

/** Seven small day dots: done, partly done, missed, planned, rest. */
export function WeekDots({ days, className }: { days: WeekDay[]; className?: string }) {
  return (
    <span className={cn('flex shrink-0 items-end gap-1', className)} role="img"
      aria-label={`This week: ${days.map((d) => `${d.weekday} ${STATE_LABEL[dayState(d)]}`).join(', ')}`}>
      {days.map((d) => {
        const st = dayState(d)
        return (
          <span key={d.date} aria-hidden className="flex w-4 flex-col items-center gap-0.5">
            <span className={cn('text-[0.6471rem] leading-none', d.today ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
              {d.weekday.charAt(0)}
            </span>
            <span className={cn('flex size-3 items-center justify-center rounded-full border text-white',
              st === 'done' || st === 'extra' ? 'border-(--accent) bg-(--accent)'
                : st === 'partial' ? 'border-(--accent) bg-(--accent)/45'
                : st === 'missed' ? 'border-(--danger)/50 bg-(--danger)/10'
                : st === 'planned' ? 'border-(--border-strong) bg-transparent'
                : 'border-transparent bg-(--bg-elevated)')}>
              {(st === 'done' || st === 'extra') && <Check className="size-2" strokeWidth={4} />}
            </span>
          </span>
        )
      })}
    </span>
  )
}

/** The week, day by day: tap a session for its details and an "Ask Rabbit" button. */
export function WeekList({ week, loading, error, onRetry, onAskDay, imperial = false }: {
  week: PlanWeek | null; loading: boolean; error: boolean; onRetry: () => void
  onAskDay: (day: WeekDay, session?: PlannedSession) => void
  imperial?: boolean
}) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  if (!week) {
    return (
      <div className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
        {error && !loading ? (
          <button type="button" onClick={onRetry} className="min-h-11 w-full text-left text-[0.7647rem] text-(--text-muted)">
            Couldn't load this week. <span className="underline">Retry</span>
          </button>
        ) : (
          <div className="flex flex-col gap-2" aria-label="Loading this week">
            <span className="skeleton h-3 w-40" aria-hidden />
            <span className="skeleton h-24" aria-hidden />
          </div>
        )}
      </div>
    )
  }
  return (
    <section aria-label="This week" className="settings-group overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      <h2 className="border-b border-(--border) px-3.5 py-2.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
        {weekTitle(week)}
      </h2>
      {week.garmin_error && <p className="px-3.5 pt-2 text-[0.7059rem] text-(--warning-text)">{week.garmin_error}</p>}
      {week.plan_status === 'error' && <p className="px-3.5 pt-2 text-[0.7059rem] text-(--text-muted)">Couldn't read this week from your plan. Showing what you've done.</p>}
      {week.plan_status === 'over_budget' && <p className="px-3.5 pt-2 text-[0.7059rem] text-(--text-muted)">Planned sessions show up tomorrow (today's limit is used up).</p>}
      <div className="divide-y divide-(--border)">
        {week.days.map((d) => <DayRow key={d.date} day={d} imperial={imperial} openKey={openKey} onToggle={setOpenKey} onAsk={onAskDay} />)}
      </div>
    </section>
  )
}
