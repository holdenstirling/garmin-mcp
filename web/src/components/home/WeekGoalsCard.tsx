// Rabbit home, under Up next: small finishable goals and a score that moves.
// Row 1: this week's ring (plan sessions, else active-week workouts; server: weekring.py),
// "4 of 5 · one more closes your week", Mon-Sun dots; tap -> the week in Plan.
// Row 2: the main race's live grade (gradetrend.py) "Boulder 70.3 · B+ · on track" with the
// weekly delta and the 1-2 reasons it moved; tap -> the full race grade. Each row hides when
// it has nothing honest to show (no Garmin / no upcoming race).
import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Check, ChevronRight, Minus } from 'lucide-react'
import { celebrate } from '@/components/fx/motion'
import { WeekRing } from '@/components/progress/Progress'
import { cn } from '@/lib/utils'
import { getLiveGrade, getWeekRing, type LiveGrade, type RingDayState, type WeekRingData } from '@/lib/weekring'

const CLOSED_SEEN = 'rabbit.weekring.closed'
const DOT_LABEL: Record<RingDayState, string> = {
  done: 'done', partial: 'partly done', missed: 'missed', planned: 'planned', rest: 'rest day',
  extra: 'workout', empty: 'open',
}

/** Celebrate a closed week once per week on this device. */
function firstClose(week: string): boolean {
  try {
    if (window.localStorage.getItem(CLOSED_SEEN) === week) return false
    window.localStorage.setItem(CLOSED_SEEN, week)
    return true
  } catch { return false }
}

function Dots({ ring }: { ring: WeekRingData }) {
  return (
    <span className="mt-1.5 flex items-end gap-1.5" role="img"
      aria-label={`This week: ${ring.days.map((d) => `${d.weekday} ${DOT_LABEL[d.state]}`).join(', ')}`}>
      {ring.days.map((d) => {
        const done = d.state === 'done' || d.state === 'extra'
        return (
          <span key={d.date} aria-hidden className="flex w-4 flex-col items-center gap-0.5">
            <span className={cn('text-[0.6471rem] leading-none', d.today ? 'font-semibold text-(--accent)' : 'text-(--text-muted)')}>
              {d.weekday.charAt(0)}
            </span>
            <span className={cn('flex size-3 items-center justify-center rounded-full border text-(--on-fill)',
              done ? 'border-(--accent) bg-(--accent)'
                : d.state === 'partial' ? 'border-(--accent) bg-(--accent)/45'
                : d.state === 'missed' ? 'border-(--danger)/50 bg-(--danger)/10'
                : d.state === 'planned' ? 'border-(--border-strong) bg-transparent'
                : d.today ? 'border-(--accent)/60 bg-transparent'
                : 'border-transparent bg-(--bg-elevated)')}>
              {done && <Check className="size-2" strokeWidth={4} />}
            </span>
          </span>
        )
      })}
    </span>
  )
}

function Delta({ g }: { g: LiveGrade }) {
  if (g.delta === null || g.direction === null) return null
  const Icon = g.direction === 'up' ? ArrowUp : g.direction === 'down' ? ArrowDown : Minus
  const when = g.weekly ? 'this week' : 'since last check'
  const words = g.direction === 'flat' ? `steady ${when}` : `${g.direction} ${Math.abs(g.delta)} ${when}`
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-0.5 font-mono text-[0.7059rem] font-semibold tabular-nums',
      g.direction === 'up' ? 'text-(--success)' : g.direction === 'down' ? 'text-(--danger)' : 'text-(--text-muted)')}
      aria-label={`Grade ${words}`}>
      <Icon className="size-3.5" aria-hidden />
      {g.direction !== 'flat' && <span aria-hidden>{Math.abs(g.delta)}</span>}
    </span>
  )
}

export function WeekGoalsCard({ refreshKey, onOpenPlan, onOpenGrade, onRing }: {
  /** bump to re-read (a sync landed) */
  refreshKey?: number
  onOpenPlan: () => void
  onOpenGrade: (eventId: string) => void
  /** told whether the ring is showing (Up next drops its own week dots then) */
  onRing?: (shown: boolean) => void
}) {
  const [ring, setRing] = useState<WeekRingData | null>(null)
  const [grade, setGrade] = useState<LiveGrade | null>(null)
  const ringBtn = useRef<HTMLButtonElement>(null)
  const ringCb = useRef(onRing)
  ringCb.current = onRing

  useEffect(() => {
    let live = true
    getWeekRing().then((r) => { if (live) setRing(r.ring) }).catch(() => { if (live) setRing(null) })
    getLiveGrade().then((r) => { if (live) setGrade(r.race) }).catch(() => { if (live) setGrade(null) })
    return () => { live = false }
  }, [refreshKey])

  useEffect(() => { ringCb.current?.(!!ring) }, [ring])
  useEffect(() => {
    if (ring?.closed && firstClose(ring.week_start)) celebrate(ringBtn.current, 'plan')
  }, [ring?.closed, ring?.week_start])

  if (!ring && !grade) return null
  return (
    <section aria-label="This week's goals"
      className="mx-4 mt-2 shrink-0 divide-y divide-(--border) overflow-hidden rounded-xl border border-(--border) bg-(--bg-surface)">
      {ring && (
        <button ref={ringBtn} type="button" onClick={onOpenPlan}
          aria-label={`This week: ${ring.line}${ring.sub ? `. ${ring.sub}` : ''}. Open the week in Plan`}
          className="press flex min-h-11 w-full items-center gap-3 px-3 py-2.5 text-left">
          <WeekRing done={ring.done} target={ring.target} size={48} />
          <span className="min-w-0 flex-1">
            <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">
              This week{ring.kind === 'active' ? ' · active week' : ''}
            </span>
            <span className={cn('block truncate text-[0.8824rem] font-semibold leading-tight',
              ring.closed ? 'text-(--accent)' : 'text-(--text)')}>{ring.line}</span>
            {ring.sub && <span className="block truncate text-[0.7059rem] text-(--text-secondary)">{ring.sub}</span>}
            <Dots ring={ring} />
          </span>
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      )}
      {grade && (
        <button type="button" onClick={() => onOpenGrade(grade.event_id)}
          className="press flex min-h-11 w-full items-center gap-3 px-3 py-2.5 text-left">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-full border-2 border-(--brand)/40 font-mono text-[0.9412rem] font-semibold text-(--text)" aria-hidden>
            {grade.grade}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Race grade</span>
            <span className="flex items-center gap-1.5">
              <span className="min-w-0 truncate text-[0.8824rem] font-semibold leading-tight text-(--text)">{grade.line}</span>
              <Delta g={grade} />
            </span>
            {grade.reasons.length > 0 && (
              <span className="block truncate text-[0.7059rem] text-(--text-secondary)">
                {grade.reasons.map((r) => `${r.sign === '+' ? '+' : '−'} ${r.text}`).join(' · ')}
              </span>
            )}
          </span>
          <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
        </button>
      )}
    </section>
  )
}
