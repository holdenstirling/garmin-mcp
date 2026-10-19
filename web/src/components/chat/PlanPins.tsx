// Pinned to the top of the coach log: the plan (tap to open it) and "This week",
// which expands into planned vs. done by day. Weeks follow the plan's own weeks.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Check, MessageCircle, ChevronRight, Map as MapIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Goal, PlannedSession, PlanWeek, Sport, WeekDay } from '@/lib/api'
import { SPORT_ICON } from '@/components/plan/PlanParts'
import { fmtDist } from '@/lib/format'
import { useDismiss } from '@/hooks/useDialog'

export function fmtMinutes(m: number): string {
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h}h ${r}m` : `${h}h`
}

export function fmtRange(start: string, end: string): string {
  const a = new Date(`${start}T12:00:00`)
  const b = new Date(`${end}T12:00:00`)
  const mon = (d: Date) => d.toLocaleDateString([], { month: 'short' })
  return a.getMonth() === b.getMonth()
    ? `${mon(a)} ${a.getDate()}–${b.getDate()}`
    : `${mon(a)} ${a.getDate()} – ${mon(b)} ${b.getDate()}`
}

const hasDuration = (title: string) => /\d+\s*(['’]|min\b|h\b)/i.test(title)

export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** "Week 3 of 39 · Base" (whatever is known). */
export function planLine(week: PlanWeek | null, goal: Goal): string {
  const bits: string[] = []
  if (week?.index && week.index > 0) bits.push(`Week ${week.index}${week.weeks ? ` of ${week.weeks}` : ''}`)
  if (week?.phase && week.phase !== 'post-race') bits.push(cap(week.phase))
  if (!bits.length && week?.weeks_to_race != null && week.weeks_to_race >= 1) bits.push(`${week.weeks_to_race} wks to race`)
  if (!bits.length) bits.push(goal.title)
  return bits.join(' · ')
}

export type DayState = 'done' | 'partial' | 'missed' | 'planned' | 'rest' | 'extra' | 'empty'

export function dayState(d: WeekDay): DayState {
  const work = d.sessions.filter((s) => s.status !== 'rest')
  if (work.length) {
    const done = work.filter((s) => s.status === 'done').length
    if (done === work.length) return 'done'
    if (done > 0) return 'partial'
    return work.some((s) => s.status === 'missed') ? 'missed' : 'planned'
  }
  if (d.extra.length) return 'extra'
  return d.sessions.length ? 'rest' : 'empty'
}

const DAY_STATE_LABEL: Record<DayState, string> = {
  done: 'done', partial: 'partly done', missed: 'missed', planned: 'planned', rest: 'rest day',
  extra: 'extra workout', empty: 'nothing planned',
}

export function DayDot({ day }: { day: WeekDay }) {
  const st = dayState(day)
  return (
    <span className="flex flex-col items-center gap-1" role="img"
      aria-label={`${day.weekday}${day.today ? ' (today)' : ''}: ${DAY_STATE_LABEL[st]}`}>
      <span aria-hidden className={cn('text-caption leading-none', day.today ? 'font-semibold text-(--accent)' : 'text-muted-foreground')}>
        {day.weekday.charAt(0)}
      </span>
      <span className={cn('flex size-[18px] items-center justify-center rounded-full border text-(--on-fill)',
        day.today && 'ring-2 ring-(--accent)/30 ring-offset-1 ring-offset-(--bg-surface)',
        st === 'done' || st === 'extra' ? 'border-(--accent) bg-(--accent)'
          : st === 'partial' ? 'border-(--accent) bg-(--accent)/45'
          : st === 'missed' ? 'border-(--danger)/50 bg-(--danger)/10'
          : st === 'planned' ? 'border-(--border-strong) bg-transparent'
          : 'border-transparent bg-(--bg-elevated)')}>
        {(st === 'done' || st === 'extra') && <Check className="size-3.5" strokeWidth={3} />}
      </span>
    </span>
  )
}

type Item = { key: string; sport: Sport; title: string; minutes: number | null; detail: string
  status: 'done' | 'missed' | 'planned' | 'rest' | 'extra'; doneMinutes?: number; session?: PlannedSession }

function items(day: WeekDay, imperial = true): Item[] {
  return [
    ...day.sessions.map((s, i) => ({ key: `s${i}`, sport: s.sport, title: s.title, minutes: s.minutes,
      detail: s.detail, status: s.status, doneMinutes: s.activity?.minutes, session: s })),
    ...day.extra.map((a, i) => ({ key: `x${i}`, sport: a.sport, title: a.name, minutes: null,
      detail: a.distance_km ? fmtDist(a.distance_km, imperial, a.sport) : '', status: 'extra' as const, doneMinutes: a.minutes })),
  ]
}

/** One day: a line per session; tapping a session opens its details and an Ask button.
 *  Only the Ask button starts a chat, so opening and closing details never does. */
export function DayRow({ day, openKey, onToggle, onAsk, onOpen, imperial = true }: {
  day: WeekDay; openKey: string | null; imperial?: boolean
  onToggle: (key: string | null) => void
  onAsk: (day: WeekDay, session?: PlannedSession) => void
  /** tap a session: the day's full details (components/week/PlanDaySheet) instead of the inline toggle */
  onOpen?: (day: WeekDay) => void
}) {
  const date = new Date(`${day.date}T12:00:00`)
  const list = items(day, imperial)
  return (
    <div className={cn('flex gap-3 px-2 py-1.5', list.length <= 1 && 'items-center', day.today && 'bg-(--accent-subtle)')}>
      <span className={cn('w-9 shrink-0 text-center leading-tight', list.length > 1 && 'pt-1')}>
        <span className={cn('block text-caption font-semibold uppercase', day.today ? 'text-(--accent)' : 'text-muted-foreground')}>{day.weekday}</span>
        <span className="block text-small text-foreground/80">{date.getDate()}</span>
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        {!list.length && <span className="py-1 text-small text-muted-foreground">Nothing planned</span>}
        {list.map((it) => {
          const Icon = SPORT_ICON[it.sport]
          const id = `${day.date}:${it.key}`
          const expanded = openKey === id
          const canOpen = it.status !== 'rest'
          const sheet = !!onOpen && canOpen
          const dur = it.minutes && !hasDuration(it.title) ? fmtMinutes(it.minutes) : ''
          return (
            <span key={it.key} className="flex flex-col">
              <button type="button" disabled={!canOpen} aria-expanded={canOpen && !sheet ? expanded : undefined}
                aria-haspopup={sheet ? 'dialog' : undefined}
                aria-label={sheet ? `${it.title}${it.status === 'missed' ? ', missed' : it.status === 'done' || it.status === 'extra' ? ', done' : ''}: see everything` : undefined}
                onClick={() => sheet ? onOpen!(day) : onToggle(expanded ? null : id)}
                className={cn('flex w-full items-center gap-2 py-1 text-left disabled:cursor-default', sheet && 'min-h-11 active:opacity-70')}>
                <Icon className={cn('size-4 shrink-0', it.status === 'done' || it.status === 'extra' ? 'text-(--accent)' : 'text-muted-foreground')} />
                <span className={cn('min-w-0 flex-1 truncate text-small', it.status === 'rest' ? 'text-muted-foreground' : 'text-foreground')}>
                  {it.title}{dur && <span className="text-muted-foreground"> · {dur}</span>}
                </span>
                <span className={cn('shrink-0 text-caption',
                  it.status === 'done' || it.status === 'extra' ? 'text-(--accent)' : it.status === 'missed' ? 'text-(--danger)' : 'text-muted-foreground')}>
                  {it.status === 'done' || it.status === 'extra' ? `✓ ${fmtMinutes(it.doneMinutes ?? 0)}` : it.status === 'missed' ? 'Missed' : ''}
                </span>
                {sheet && <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
              </button>
              {canOpen && !sheet && (
                <span className={cn('session-detail', expanded && 'session-detail--open')}>
                  <span className="min-h-0 overflow-hidden">
                    <span className="flex flex-col gap-2 pb-2 pl-5.5">
                      {it.detail && <span className="text-meta leading-snug text-muted-foreground">{it.detail}</span>}
                      <button type="button" tabIndex={expanded ? 0 : -1}
                        onClick={() => onAsk(day, it.session)}
                        className="hit-44 inline-flex w-fit items-center gap-1.5 rounded-full bg-(--accent-subtle) px-2.5 py-1 text-caption font-medium text-(--accent) active:opacity-70">
                        <MessageCircle className="size-4" /> Ask rabbt
                      </button>
                    </span>
                  </span>
                </span>
              )}
            </span>
          )
        })}
      </span>
    </div>
  )
}

export function PlanPins({ goal, week, loading, error = false, onRetry, onOpenPlan, onAskDay, imperial = true }: {
  goal: Goal
  /** athlete units (extra activities' distance) */
  imperial?: boolean
  week: PlanWeek | null
  loading: boolean
  /** the week couldn't be loaded (shown only while there's no week to show) */
  error?: boolean
  onRetry?: () => void
  onOpenPlan: () => void
  onAskDay: (day: WeekDay, session?: PlannedSession) => void
}) {
  const [open, setOpenState] = useState(false)
  const [openKey, setOpenKey] = useState<string | null>(null)
  // The drawer may use all the room below the card (down to the safe area).
  const cardRef = useRef<HTMLDivElement>(null)
  const [room, setRoom] = useState<number | null>(null)
  // Stay above the dimming until the drawer has finished sliding shut.
  const [raised, setRaised] = useState(false)
  const lowerTimer = useRef<number | null>(null)
  // The card is one rounded box (header + drawer) floating over the feed; this spacer keeps
  // the header's height in the layout so opening the drawer never pushes the feed.
  const headRef = useRef<HTMLButtonElement>(null)
  const [headH, setHeadH] = useState<number | null>(null)
  useLayoutEffect(() => {
    const el = headRef.current
    if (!el) return
    const measure = () => setHeadH(el.offsetHeight + 2) // + the card's 1px borders
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const setOpen = (next: boolean | ((v: boolean) => boolean)) => {
    const v = typeof next === 'function' ? next(open) : next
    if (lowerTimer.current) window.clearTimeout(lowerTimer.current)
    if (v) {
      setRaised(true)
      const bottom = headRef.current?.getBoundingClientRect().bottom
      if (bottom != null) setRoom(Math.max(200, (window.visualViewport?.height ?? window.innerHeight) - bottom - 16))
    }
    else lowerTimer.current = window.setTimeout(() => setRaised(false), 340)
    setOpenState(v)
  }
  useEffect(() => () => {
    if (lowerTimer.current) window.clearTimeout(lowerTimer.current)
  }, [])
  // The open drawer closes on Escape and the phone's Back, like the dimmed area.
  useDismiss(cardRef, () => setOpen(false), open)
  const hasPlan = !!goal.plan
  const reading = loading && hasPlan && !week
  const failed = error && !week && !loading

  // One line: where you are in the plan and which days (falls back to "This week").
  const where = week?.index && week.index > 0
    ? `Week ${week.index}${week.weeks ? ` of ${week.weeks}` : ''}${week.phase && week.phase !== 'post-race' ? ` · ${cap(week.phase)}` : ''}`
    : 'This week'

  return (
    <>
    <div className={cn('week-dim', open && 'week-dim--open')} onClick={() => setOpen(false)} aria-hidden />
    <div className="coach-pins shrink-0 border-b border-(--border) bg-(--bg) px-3 pb-2.5 pt-0">
      {/* Only the card rises above the dimming; the drawer slides down over the feed. */}
      <div className={cn('relative mx-auto max-w-2xl', raised && 'z-(--z-drawer-raised)')} style={headH ? { height: headH } : undefined}>
      <div ref={cardRef} className={cn('overflow-hidden rounded-xl border border-border bg-(--bg-surface) transition-shadow duration-300',
        headH && 'absolute inset-x-0 top-0', raised ? 'shadow-lg' : 'shadow-sm')}>
        <button ref={headRef} onClick={() => (failed && onRetry ? onRetry() : setOpen((v) => !v))} aria-expanded={open}
          className="flex w-full items-center gap-2 px-3 pb-2 pt-2 text-left">
          <span className="min-w-0 flex-1">
            <span className="flex items-baseline gap-2">
              <span className="truncate text-caption font-semibold text-muted-foreground">
                {where}{week ? ` · ${fmtRange(week.start, week.end)}` : ''}
              </span>
              {reading && <span className="ml-auto shrink-0 text-caption text-muted-foreground">Reading your plan…</span>}
            </span>
            {week ? (
              <span className="mt-1.5 flex justify-between px-1">
                {week.days.map((d) => <DayDot key={d.date} day={d} />)}
              </span>
            ) : failed ? (
              <span className="mt-1.5 flex h-[30px] items-center px-1 text-meta text-muted-foreground">
                Couldn't load this week.{onRetry ? ' Tap to retry' : ''}
              </span>
            ) : (
              <span className="mt-1.5 flex justify-between px-1">
                {Array.from({ length: 7 }, (_, i) => (
                  <span key={i} className="flex flex-col items-center gap-1">
                    <span className="h-2.5 w-2 rounded bg-(--bg-elevated)" />
                    <span className="size-[18px] animate-pulse motion-reduce:animate-none rounded-full bg-(--bg-elevated)" />
                  </span>
                ))}
              </span>
            )}
          </span>
        </button>
        <div className={cn('week-drawer', open && 'week-drawer--open')} aria-hidden={!open} inert={!open}>
          <div className="min-h-0 overflow-hidden">
          <div className="overflow-y-auto overscroll-contain border-t border-(--border) pb-1"
            style={{ maxHeight: room ? `calc(${room}px - env(safe-area-inset-bottom))` : '52dvh' }}>
            <button onClick={() => { setOpen(false); onOpenPlan() }}
              className="flex w-full items-center gap-3 border-b border-(--border) px-3 py-2.5 text-left active:bg-(--bg-inset)">
              <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)">
                <MapIcon className="size-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-body font-medium text-foreground">{hasPlan ? 'Your plan' : 'Add your plan'}</span>
                <span className="block truncate text-caption text-muted-foreground">
                  {hasPlan ? (week?.focus?.replace(/\s*\([^)]*\)\s*$/, '') || goal.title) : 'Upload it or tell rabbt about it'}
                </span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-muted-foreground" />
            </button>
            {week?.garmin_error && <p className="px-2 py-1 text-caption text-(--warning-text)">{week.garmin_error}</p>}
            {week?.plan_status === 'error' && <p className="px-2 py-1 text-caption text-muted-foreground">Couldn't read this week from your plan. Showing what you've done.</p>}
            {week?.plan_status === 'over_budget' && <p className="px-2 py-1 text-caption text-muted-foreground">Planned workouts show up tomorrow (today's limit is used up).</p>}
            <div className="divide-y divide-(--border)">
              {week?.days.map((d) => <DayRow key={d.date} day={d} imperial={imperial} openKey={openKey} onToggle={setOpenKey}
                onAsk={(day, session) => { setOpen(false); onAskDay(day, session) }} />)}
            </div>
          </div>
          </div>
        </div>
      </div>
      </div>
    </div>
    </>
  )
}
