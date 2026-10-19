// The plan as an easy calendar (server: plancal.py). Views (remembered on the device):
//   Today: one day at a time (PlanDay.tsx) with each workout in full, arrows/swipe to other days.
//   Week: each day's sessions as cards, what the week prescribes (focus + key sessions), mileage.
//   List: an agenda of the plan a few weeks at a time ("Show more weeks" to race day).
//   Month: the month at a glance with weekly/monthly mileage; tap a day to open it.
// Tapping a workout opens its full page (lib/workoutnav openWorkout: the rabbit:open-workout event); the
// pencil edits it in place (SessionSheet). "Edit" reveals Day earlier / Day later / Move or swap
// and + per day; press and hold drags a session to another day (touch: long-press). Every change
// re-balances the week and can be undone. "Plan overview" shows the phases to race day.
// Deep link: lib/plancal openPlanDay(date) (sessionStorage keys read on mount + an event).
import { smooth } from '@/lib/scrollMotion'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeftRight, Check, ChevronLeft, ChevronRight, Flag, GripVertical, Map as MapIcon, Pencil, Plane, Plus, Undo2, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/nav/Segmented'
import { Sheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/utils'
import { openActivity } from '@/lib/activitynav'
import { haptic } from '@/lib/haptics'
import { KM_PER_MI, fmtDist, fmtDuration } from '@/lib/format'
import { KIND_LABEL, type BuiltPlan, type PlanSession, type PlanWeekBuilt } from '@/lib/plan'
import {
  OPEN_PLAN_DAY_EVENT, fmtTime, PLAN_DAY_KEY, PLAN_FIX_EVENT, PLAN_VIEW_KEY, SPORT_DIST_LABEL, fixMissed, moveSession, setWeekGoal, takePlanFix, undoChange,
  type CalChange, type CalResult, type CalSession, type CalView, type DistSport, type Mileage,
} from '@/lib/plancal'
import { Card, Chip, ChipRow, Field, inputCls } from './ui'
import { SPORT_ICON, fmtDay, sessionMinutes, weekPhaseLabel } from './PlanParts'
import { MoveSheet, addDays, mondayOf, weekdayIdx } from './MoveSheet'
import { PlanDay } from './PlanDay'
import { PlanOverview } from './PlanOverview'
import { openWorkout as openWorkoutPage } from '@/lib/workoutnav'

const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
type View = 'week' | 'month' | 'day' | 'list'
const readKey = (k: string) => { try { return sessionStorage.getItem(k) } catch { return null } }
// The chosen view is remembered on this device too (sessionStorage is per tab session).
const VIEW_KEEP = 'rabbit.plancal.view.keep'
const readView = (): View => {
  let v: string | null = readKey(PLAN_VIEW_KEY)
  if (!v) { try { v = localStorage.getItem(VIEW_KEEP) } catch { v = null } }
  return v === 'month' || v === 'day' || v === 'list' ? v : 'week'
}

export function paceText(secPerKm: number, imperial: boolean) {
  const s = Math.round(secPerKm * (imperial ? KM_PER_MI : 1))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
function distText(c: CalSession | undefined, s: PlanSession, imperial: boolean) {
  if (!c) return s.meters ? fmtDist(s.meters / 1000, imperial, 'swim') : ''
  return (Object.entries(c.km) as [DistSport, number][]).filter(([, v]) => v > 0)
    .map(([sp, v]) => fmtDist(v, imperial, sp)).join(' + ')
}
const unitWord = (imperial: boolean, sport: DistSport) => sport === 'swim' ? (imperial ? 'yd' : 'm') : imperial ? 'mi' : 'km'
const toUnit = (km: number, imperial: boolean, sport: DistSport) =>
  sport === 'swim' ? Math.round(km * 1000 * (imperial ? 1.0936133 : 1)) : Math.round((imperial ? km / KM_PER_MI : km) * 10) / 10
const fromUnit = (v: number, imperial: boolean, sport: DistSport) =>
  sport === 'swim' ? v / 1000 / (imperial ? 1.0936133 : 1) : imperial ? v * KM_PER_MI : v

export type MoveTarget = { session: PlanSession; date: string; mode?: 'move' | 'swap' }

// ---------------------------------------------------------------- drag --
type Drag = { id: string; from: string; title: string; x: number; y: number; over: string | null }

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if ((o === 'auto' || o === 'scroll') && p.scrollHeight > p.clientHeight) return p
  }
  return null
}

/** Pointer drag for session cards: mouse drags after 6px, touch/pen after a 350 ms long-press. */
function useCardDrag(enabled: boolean, canDrop: (day: string) => boolean, onDrop: (id: string, from: string, to: string) => void) {
  const [drag, setDrag] = useState<Drag | null>(null)
  const dragRef = useRef<Drag | null>(null)
  dragRef.current = drag
  const suppressClick = useRef(false)
  const cfg = useRef({ canDrop, onDrop })
  cfg.current = { canDrop, onDrop }

  useEffect(() => {
    if (!drag) return
    const block = (e: TouchEvent) => { if (dragRef.current) e.preventDefault() }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrag(null) }
    document.addEventListener('touchmove', block, { passive: false })
    document.addEventListener('keydown', esc)
    let raf = 0
    const scroller = scrollParent(document.querySelector('[data-cal-root]'))
    const tick = () => {
      const d = dragRef.current
      if (d && scroller) {
        const r = scroller.getBoundingClientRect()
        const edge = 64
        if (d.y < r.top + edge) scroller.scrollTop -= Math.ceil((r.top + edge - d.y) / 6)
        else if (d.y > r.bottom - edge) scroller.scrollTop += Math.ceil((d.y - (r.bottom - edge)) / 6)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { document.removeEventListener('touchmove', block); document.removeEventListener('keydown', esc); cancelAnimationFrame(raf) }
  }, [drag !== null]) // eslint-disable-line react-hooks/exhaustive-deps

  function dayAt(x: number, y: number): string | null {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-cal-day]')
    const day = el?.dataset.calDay ?? null
    return day && cfg.current.canDrop(day) ? day : null
  }

  function bind(id: string, from: string, title: string) {
    if (!enabled) return {}
    return {
      onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
        if (e.button !== 0) return
        const el = e.currentTarget
        const sx = e.clientX, sy = e.clientY
        const pid = e.pointerId
        const touch = e.pointerType !== 'mouse'
        let started = false
        let timer = 0
        const start = (x: number, y: number) => {
          started = true
          suppressClick.current = true
          try { el.setPointerCapture(pid) } catch { /* ignore */ }
          haptic()
          setDrag({ id, from, title, x, y, over: null })
        }
        const move = (ev: PointerEvent) => {
          if (ev.pointerId !== pid) return
          if (!started) {
            const far = Math.hypot(ev.clientX - sx, ev.clientY - sy)
            if (touch) { if (far > 8) cleanup() } // a scroll, not a long-press
            else if (far > 6) start(ev.clientX, ev.clientY)
            return
          }
          setDrag((d) => d && { ...d, x: ev.clientX, y: ev.clientY, over: dayAt(ev.clientX, ev.clientY) })
        }
        const up = (ev: PointerEvent) => {
          if (ev.pointerId !== pid) return
          const d = dragRef.current
          if (started && d && ev.type === 'pointerup') {
            const to = dayAt(ev.clientX, ev.clientY)
            if (to && to !== d.from) cfg.current.onDrop(d.id, d.from, to)
          }
          if (started) setDrag(null)
          cleanup()
          window.setTimeout(() => { suppressClick.current = false }, 50)
        }
        const cleanup = () => {
          window.clearTimeout(timer)
          window.removeEventListener('pointermove', move)
          window.removeEventListener('pointerup', up)
          window.removeEventListener('pointercancel', up)
        }
        window.addEventListener('pointermove', move)
        window.addEventListener('pointerup', up)
        window.addEventListener('pointercancel', up)
        if (touch) timer = window.setTimeout(() => start(sx, sy), 350)
      },
      onContextMenu: (e: React.MouseEvent) => { if (dragRef.current) e.preventDefault() },
    }
  }
  return { drag, bind, suppressClick }
}

// -------------------------------------------------------------- pieces --
function MileBar({ m, sport, imperial, label }: { m: Mileage; sport: DistSport; imperial: boolean; label?: string }) {
  const pct = m.goal > 0 ? Math.min(100, (m.done / m.goal) * 100) : 0
  const u = unitWord(imperial, sport)
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="flex items-baseline gap-1.5">
        {label && <span className="text-caption text-(--text-muted) font-semibold">{label}</span>}
        <span className="font-mono text-body font-semibold tabular-nums text-(--text)">
          {toUnit(m.done, imperial, sport).toLocaleString()} of {toUnit(m.goal, imperial, sport).toLocaleString()} {u}
        </span>
        {m.custom && <span className="text-caption text-(--text-muted)">your goal</span>}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-(--bg-elevated)" role="progressbar" aria-valuemin={0}
        aria-valuemax={Math.round(toUnit(m.goal, imperial, sport))} aria-valuenow={Math.round(toUnit(m.done, imperial, sport))}
        aria-label={`${SPORT_DIST_LABEL[sport]} this week`}>
        <div className={cn('h-full rounded-full', pct >= 100 ? 'bg-(--success)' : 'bg-(--accent)')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function WeekMiles({ week, miles, imperial, editable, onGoal }: {
  week: string; miles: Partial<Record<DistSport, Mileage>> | undefined; imperial: boolean; editable: boolean
  onGoal: (sport: DistSport, km: number | null) => Promise<void>
}) {
  const [edit, setEdit] = useState<DistSport | null>(null)
  const [val, setVal] = useState('')
  const [busy, setBusy] = useState(false)
  const entries = (Object.entries(miles ?? {}) as [DistSport, Mileage][]).filter(([, m]) => m.goal > 0 || m.done > 0)
  useEffect(() => setEdit(null), [week])
  if (!entries.length) return null
  const multi = entries.length > 1
  async function save(km: number | null) {
    if (!edit) return
    setBusy(true)
    try { await onGoal(edit, km); setEdit(null) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2 border-b border-(--border) px-4 py-2.5">
      {entries.map(([sp, m]) => (
        <div key={sp} className="flex items-center gap-2">
          <MileBar m={m} sport={sp} imperial={imperial} label={multi ? SPORT_DIST_LABEL[sp] : 'This week'} />
          {editable && sp !== 'swim' && (
            <button type="button" className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-(--text-muted) active:bg-(--bg-inset)"
              aria-label={`Change the ${SPORT_DIST_LABEL[sp].toLowerCase()} goal for this week`}
              onClick={() => { setEdit(sp); setVal(String(toUnit(m.goal, imperial, sp))) }}>
              <Pencil className="size-4" />
            </button>
          )}
        </div>
      ))}
      {edit && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-small text-(--text-secondary)">
            Weekly goal
            <input className={cn(inputCls, 'h-9 w-20')} inputMode="decimal" value={val} aria-label={`Weekly goal in ${unitWord(imperial, edit)}`}
              onChange={(e) => setVal(e.target.value)} /> {unitWord(imperial, edit)}
          </label>
          <Button variant="primary" className="h-9 px-3 text-small" loading={busy}
            disabled={!(Number(val) > 0)} onClick={() => void save(fromUnit(Number(val), imperial, edit))}>Save</Button>
          {miles?.[edit]?.custom && <Button variant="ghost" className="h-9 px-2 text-meta" onClick={() => void save(null)}>Use the plan's</Button>}
          <Button variant="ghost" className="h-9 px-2 text-meta" onClick={() => setEdit(null)}>Cancel</Button>
        </div>
      )}
    </div>
  )
}

function StatusChip({ c }: { c: CalSession | undefined }) {
  if (!c) return null
  if (c.status === 'done') return <span className="flex shrink-0 items-center gap-0.5 rounded-full bg-(--accent-subtle) px-2 py-0.5 text-caption font-semibold text-(--accent)"><Check className="size-3.5" aria-hidden />Done</span>
  if (c.status === 'missed') return <span className="shrink-0 rounded-full bg-(--danger)/10 px-2 py-0.5 text-caption font-semibold text-(--danger)">Missed</span>
  if (c.status === 'skipped') return <span className="shrink-0 rounded-full bg-(--bg-elevated) px-2 py-0.5 text-caption font-semibold text-(--text-muted)">Skipped</span>
  return null
}

function SessionCard({ s, c, date, imperial, unread, dragging, onOpen, onEdit, onFix, dragProps, grab, editing, onShift, onMove }: {
  s: PlanSession; c: CalSession | undefined; date: string; imperial: boolean; unread: boolean; dragging: boolean
  /** the full workout page */
  onOpen?: () => void
  /** quick edit (SessionSheet) without opening the page */
  onEdit?: () => void
  onFix?: () => void; dragProps: Record<string, unknown>; grab: boolean
  /** "Edit week": show the move controls */
  editing?: boolean
  /** move one day earlier (-1) / later (+1); undefined when that day can't take it */
  onShift?: { [k in -1 | 1]?: () => void }
  onMove?: () => void
}) {
  const Icon = s.kind === 'race' ? Flag : SPORT_ICON[s.sport]
  const mins = sessionMinutes(s)
  const dist = distText(c, s, imperial)
  const pace = c?.pace ? `${paceText(c.pace.fast, imperial)}–${paceText(c.pace.slow, imperial)}/${imperial ? 'mi' : 'km'}` : ''
  const meta = [dist, mins ? fmtDuration(mins) : '', pace].filter(Boolean).join(' · ')
  const dim = c?.status === 'skipped'
  return (
    <div className={cn('rounded-xl border bg-(--bg-surface) transition-opacity', dragging ? 'opacity-40' : '',
      c?.status === 'missed' ? 'border-(--danger)/40' : 'border-(--border)', dim && 'opacity-60')}>
      <div className="flex items-stretch">
      <button type="button" onClick={onOpen} disabled={!onOpen} {...dragProps} data-session-id={s.id}
        aria-label={`${s.title}, ${fmtDay(date, { weekday: 'long' })}${s.time ? ` at ${fmtTime(s.time)}` : ''}${meta ? `, ${meta}` : ''}${c && c.status !== 'planned' ? `, ${c.status}` : ''}. Open the full workout`}
        className={cn('flex min-w-0 flex-1 items-start gap-2.5 py-2 pl-3 text-left disabled:cursor-default', !onEdit && 'pr-3', grab && 'touch-manipulation select-none')}>
        <span className={cn('mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg',
          s.kind === 'race' ? 'bg-(--brand) text-(--on-fill)' : c?.status === 'done' ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            {s.time && <span className="shrink-0 font-mono text-meta font-semibold tabular-nums text-(--text-secondary)">{fmtTime(s.time)}</span>}
            <span className={cn('min-w-0 flex-1 truncate text-body font-medium text-(--text)', dim && 'line-through')}>{s.title}</span>
            {unread && <span className="size-2 shrink-0 rounded-full bg-(--accent)" aria-label="New coach message" />}
            <StatusChip c={c} />
            {s.synced && !c?.status.match(/done|missed/) && <span className="shrink-0 text-caption text-(--accent) font-semibold">Garmin</span>}
          </span>
          {meta && <span className="block truncate font-mono text-meta tabular-nums text-(--text-secondary)">{meta}</span>}
          {!meta && s.kind !== 'race' && <span className="block truncate text-meta text-(--text-muted)">{KIND_LABEL[s.kind] ?? s.kind}</span>}
          {c?.note && c.status !== 'missed' && <span className="block truncate text-meta text-(--text-muted)">{c.note.source === 'coach' ? 'Coach: ' : ''}{c.note.line}</span>}
          {c?.missed && <span className="block text-meta leading-snug text-(--text-secondary)">{c.missed.why}</span>}
        </span>
        {grab && editing && <GripVertical className="mt-2 size-5 shrink-0 text-(--text-muted)" aria-hidden />}
      </button>
      {onEdit && (
        <button type="button" onClick={onEdit} aria-label={`Edit ${s.title}`}
          className="flex w-11 shrink-0 items-start justify-center pt-3 text-(--text-muted) active:text-(--text)">
          <Pencil className="size-4" aria-hidden />
        </button>
      )}
      </div>
      {editing && (onMove || onShift) && (
        <div className="flex items-center gap-1 border-t border-(--border) px-1.5 py-0.5">
          <button type="button" disabled={!onShift?.[-1]} onClick={onShift?.[-1]} aria-label={`Move ${s.title} one day earlier`}
            className="flex min-h-11 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-meta font-medium text-(--text-secondary) disabled:opacity-35 active:bg-(--bg-inset)">
            <ChevronLeft className="size-4" aria-hidden />Earlier
          </button>
          <button type="button" disabled={!onShift?.[1]} onClick={onShift?.[1]} aria-label={`Move ${s.title} one day later`}
            className="flex min-h-11 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-meta font-medium text-(--text-secondary) disabled:opacity-35 active:bg-(--bg-inset)">
            Later<ChevronRight className="size-4" aria-hidden />
          </button>
          {onMove && (
            <button type="button" onClick={onMove} className="ml-auto flex min-h-11 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-meta font-medium text-(--accent) active:bg-(--bg-inset)" aria-label={`Move ${s.title} to any day, or swap days`}>
              <ArrowLeftRight className="size-4" aria-hidden />Move
            </button>
          )}
        </div>
      )}
      {onFix && (
        <div className="flex justify-end border-t border-(--border) px-2 py-1">
          <Button variant="ghost" className="h-11 gap-1.5 px-3 text-small text-(--accent)" onClick={onFix}>
            <Wrench className="size-4" /> Fix my week
          </Button>
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------- sheets --
function DayChips({ days, today, raceDate, avail, from, best, onPick, busy }: {
  days: string[]; today: string; raceDate: string; avail: number[]; from: string; best?: string | null
  onPick: (d: string) => void; busy: string | null
}) {
  return (
    <ChipRow>
      {days.filter((d) => d >= today && d <= raceDate && d !== from).map((d) => (
        <Chip key={d} selected={busy === d} disabled={busy != null} onClick={() => onPick(d)}
          title={avail.includes(weekdayIdx(d)) ? undefined : 'Not one of your usual training days'}>
          <span className={cn(!avail.includes(weekdayIdx(d)) && 'text-(--text-muted)')}>
            {d === today ? 'Today' : fmtDay(d, { weekday: 'short', day: 'numeric' })}{d === best ? ' · best' : ''}
          </span>
        </Chip>
      ))}
    </ChipRow>
  )
}

function FixSheet({ s, date, c, plan, cal, today, onClose, run }: {
  s: PlanSession; date: string; c: CalSession; plan: BuiltPlan; cal: CalView; today: string; onClose: () => void
  run: (p: Promise<CalResult>) => Promise<CalResult | null>
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const mon = mondayOf(today)
  const days = Array.from({ length: 7 }, (_, i) => addDays(mon, i))
  const go = async (key: string, p: () => Promise<CalResult>) => {
    setBusy(key)
    const ok = await run(p())
    setBusy(null)
    if (ok) onClose()
  }
  const word = s.sport === 'bike' ? 'ride' : s.sport === 'swim' ? 'swim' : 'run'
  return (
    <Sheet title={`Missed: ${s.title}`} onClose={onClose} bodyClassName="settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <p className="px-1 text-body leading-snug text-(--text-secondary)">
        {fmtDay(date, { weekday: 'long' })}: {c.missed?.why} Life happens. Pick a fix and rabbt re-balances the rest of your week.
      </p>
      <Card>
        <Field label="Move it to another day">
          <DayChips days={days} today={today} raceDate={plan.race_date} avail={cal.available_days} from={date} best={c.missed?.best_day}
            onPick={(d) => void go(d, () => fixMissed(s.id, 'move', d))} busy={busy} />
        </Field>
        <div className="flex flex-col gap-2 border-t border-(--border) p-4">
          <Button variant="default" className="h-11 justify-start gap-2 text-body" loading={busy === 'easy'} disabled={busy != null}
            onClick={() => void go('easy', () => fixMissed(s.id, 'easy'))}>
            Do an easy {word} instead
          </Button>
          <Button variant="default" className="h-11 justify-start gap-2 text-body" loading={busy === 'skip'} disabled={busy != null}
            onClick={() => void go('skip', () => fixMissed(s.id, 'skip'))}>
            Skip it and spread the miles
          </Button>
          <p className="text-meta text-(--text-muted)">Easy {word}s stretch by at most 15% each and no hard day is added.</p>
        </div>
      </Card>
    </Sheet>
  )
}

// ------------------------------------------------------------- calendar --
export function PlanCalendar({ plan, cal, imperial, today, week, onWeek, editable, unread, busyLabel, onOpen, onAdd, onResult, moving, onMoving, hidden, dayExtra, onStart, onAsk, onOpenSession, onAdjust }: {
  plan: BuiltPlan; cal: CalView | null; imperial: boolean; today: string
  week: PlanWeekBuilt; onWeek: (index: number) => void
  /** drag, Move, Fix and goals (the athlete's own plan) */
  editable: boolean
  unread: string[]
  busyLabel: (d: string) => string
  onOpen: (s: PlanSession, date: string) => void
  onAdd?: (date: string) => void
  onResult: (r: CalResult) => void
  moving: MoveTarget | null; onMoving: (t: MoveTarget | null) => void
  /** sessions shown elsewhere (e.g. the TrainingPeaks copy is the source of truth) */
  hidden?: (id: string) => boolean
  /** extra items under a day's sessions (TrainingPeaks workouts) */
  dayExtra?: (date: string) => React.ReactNode
  /** Day view: open the pre-workout screen for a session */
  onStart?: (s: PlanSession, date: string) => void
  /** Day view: ask Rabbit about a session */
  onAsk?: (s: PlanSession, date: string) => void
  /** tap a session: its full workout page (default: the rabbit:open-workout event) */
  onOpenSession?: (s: PlanSession, date: string) => void
  /** Plan overview's "Adjust my plan" (levers sheet in PlanEditor) */
  onAdjust?: () => void
}) {
  const openPage = onOpenSession ?? ((s: PlanSession, date: string) => openWorkoutPage(s.id, date))
  const first = plan.weeks[0]!.days[0]!.date
  const lastW = plan.weeks[plan.weeks.length - 1]!
  const last = lastW.days[lastW.days.length - 1]!.date
  const clamp = (d: string) => d < first ? first : d > last ? last : d
  const weekOf = (d: string) => plan.weeks.find((w) => w.days.some((x) => x.date === d))
  const [view, setView] = useState<View>(readView)
  const [editing, setEditing] = useState(false)
  const [overview, setOverview] = useState(false)
  const [day, setDay] = useState<string>(() => {
    const k = readKey(PLAN_DAY_KEY)
    if (k && /^\d{4}-\d{2}-\d{2}$/.test(k)) return clamp(k)
    return week.days.some((d) => d.date === today) ? today : week.days[0]!.date
  })
  const openDay = (d: string) => {
    const c = clamp(d)
    setDay(c)
    setView('day')
    const w = weekOf(c)
    if (w && w.index !== week.index) onWeek(w.index)
  }
  const pickDay = (d: string) => { const c = clamp(d); setDay(c); const w = weekOf(c); if (w && w.index !== week.index) onWeek(w.index) }
  const [fix, setFix] = useState<{ s: PlanSession; date: string } | null>(null)
  const [change, setChange] = useState<CalChange | null>(null)
  const [toast, setToast] = useState<{ text: string; undo: string | null; n: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pos = plan.weeks.indexOf(week)
  const sessionsById = useMemo(() => {
    const m = new Map<string, { s: PlanSession; date: string }>()
    for (const w of plan.weeks) for (const d of w.days) for (const s of d.sessions) m.set(s.id, { s, date: d.date })
    return m
  }, [plan])

  useEffect(() => { try { sessionStorage.setItem(PLAN_VIEW_KEY, view); localStorage.setItem(VIEW_KEEP, view) } catch { /* ignore */ } }, [view])
  // Deep link (lib/plancal openPlanDay): keys read on mount (above), the event while mounted;
  // either way the calendar scrolls into view so the day is what you see.
  const rootRef = useRef<HTMLElement>(null)
  const reveal = () => setTimeout(() => rootRef.current?.scrollIntoView({ block: 'start', behavior: smooth() }), 120)
  useEffect(() => {
    if (readKey(PLAN_DAY_KEY)) {
      reveal()
      try { sessionStorage.removeItem(PLAN_DAY_KEY) } catch { /* ignore */ }
      if (view === 'day') { const w = weekOf(day); if (w && w.index !== week.index) onWeek(w.index) }
    }
    const on = (e: Event) => {
      const d = (e as CustomEvent<string>).detail
      try { sessionStorage.removeItem(PLAN_DAY_KEY) } catch { /* ignore */ }
      if (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d)) { openDay(d); reveal() }
    }
    window.addEventListener(OPEN_PLAN_DAY_EVENT, on)
    return () => window.removeEventListener(OPEN_PLAN_DAY_EVENT, on)
  }, [plan]) // eslint-disable-line react-hooks/exhaustive-deps
  // Another control (the phase strip) changed the week: keep the Day view inside it.
  const weekSeen = useRef(week.start)
  useEffect(() => {
    if (weekSeen.current === week.start) return  // first render: a deep-linked day may still be moving the week
    weekSeen.current = week.start
    if (!week.days.some((d) => d.date === day)) setDay(week.days.some((d) => d.date === today) ? today : week.days[0]!.date)
  }, [week.start]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 7000)
    return () => window.clearTimeout(t)
  }, [toast])
  // "Fix my week" from a Rabbit moment.
  useEffect(() => {
    const open = () => {
      const id = takePlanFix()
      const hit = id ? sessionsById.get(id) : undefined
      if (hit && cal?.sessions[hit.s.id]?.status === 'missed') {
        const w = plan.weeks.find((x) => x.days.some((d) => d.date === hit.date))
        if (w) onWeek(w.index)
        setView('week')
        setFix(hit)
      }
    }
    if (cal) open()
    window.addEventListener(PLAN_FIX_EVENT, open)
    return () => window.removeEventListener(PLAN_FIX_EVENT, open)
  }, [cal, sessionsById]) // eslint-disable-line react-hooks/exhaustive-deps

  async function run(p: Promise<CalResult>): Promise<CalResult | null> {
    setError(null)
    try {
      const r = await p
      onResult(r)
      if (r.change) {
        setChange(r.change.rebalanced.length ? r.change : null)
        setToast((t) => ({ text: r.change!.summary, undo: r.change!.id, n: (t?.n ?? 0) + 1 }))
      }
      return r
    } catch (e) {
      setError((e as Error).message)
      setToast((t) => ({ text: (e as Error).message, undo: null, n: (t?.n ?? 0) + 1 }))
      return null
    }
  }
  const canDrop = (d: string) => d >= today && d <= plan.race_date && plan.weeks.some((w) => w.days.some((x) => x.date === d))
  const { drag, bind, suppressClick } = useCardDrag(editable && !!cal, canDrop, (id, _from, to) => { void run(moveSession(id, to)) })

  const movable = (s: PlanSession, date: string) => {
    const c = cal?.sessions[s.id]
    return editable && !!cal && s.sport !== 'rest' && s.kind !== 'race' && c?.status !== 'done' && c?.status !== 'skipped' &&
      (date >= today || c?.status === 'missed')
  }

  const shift = (s: PlanSession, date: string, n: -1 | 1) => {
    const to = addDays(date, n)
    return canDrop(to) ? () => { haptic(); void run(moveSession(s.id, to)) } : undefined
  }
  const editToggle = editable && cal && (
    <button type="button" aria-pressed={editing} onClick={() => setEditing((v) => !v)}
      className={cn('flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border px-3 text-small font-medium',
        editing ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border) text-(--text-secondary) active:bg-(--bg-inset)')}>
      {editing ? <><Check className="size-4" aria-hidden />Done</> : <><Pencil className="size-4" aria-hidden />Edit</>}
    </button>
  )

  /** One day as a row (Week and List views): its sessions, workouts from your apps, + to add. */
  const dayRow = (d: { date: string; sessions: PlanSession[] }, compact = false) => {
    const past = d.date < today
    const isToday = d.date === today
    const work = d.sessions.filter((s) => s.sport !== 'rest' && !hidden?.(s.id))
    const extra = dayExtra?.(d.date)
    const done = cal?.extra?.[d.date] ?? []
    const over = drag?.over === d.date && drag.from !== d.date
    const canAdd = !!onAdd && !past && d.date <= plan.race_date && work.length < 4
    const quiet = compact && !work.length && !extra && !done.length && !over && !editing
    return (
      <div key={d.date} data-cal-day={d.date}
        className={cn('flex gap-3 px-3 transition-colors', quiet ? 'py-0.5' : 'py-2', isToday && 'bg-(--accent-subtle)',
          over && 'bg-(--accent)/15 outline-2 -outline-offset-2 outline-dashed outline-(--accent)',
          drag && !canDrop(d.date) && 'opacity-50')}>
        <span className="w-11 shrink-0 text-center leading-tight">
          <button type="button" onClick={() => openDay(d.date)} aria-label={`Open ${fmtDay(d.date, { weekday: 'long', month: 'long', day: 'numeric' })}`}
            className={cn('flex w-11 flex-col items-center justify-center rounded-lg active:bg-(--bg-inset)', quiet ? 'min-h-11 flex-row gap-1' : 'min-h-11 pt-1')}>
            <span className={cn('block text-caption font-semibold uppercase', isToday ? 'text-(--accent)' : 'text-(--text-muted)')}>
              {isToday ? 'Today' : fmtDay(d.date, { weekday: 'short' })}
            </span>
            <span className={cn('block text-small', isToday ? 'font-semibold text-(--accent)' : 'text-(--text-secondary)')}>{fmtDay(d.date, { day: 'numeric' })}</span>
          </button>
          {!quiet && busyLabel(d.date) && <span className="mt-0.5 block text-caption leading-tight text-(--warning-text)">{busyLabel(d.date)}</span>}
          {!quiet && plan.trips.some((t) => t.start <= d.date && d.date <= t.end) && <Plane className="mx-auto mt-0.5 size-3.5 text-(--accent)" aria-label="Travel day" />}
        </span>
        <div className={cn('flex min-w-0 flex-1 flex-col gap-1.5', quiet ? 'justify-center' : 'py-0.5')}>
          {work.map((s) => {
            const c = cal?.sessions[s.id]
            const mv = movable(s, d.date)
            return (
              <SessionCard key={s.id} s={s} c={c} date={d.date} imperial={imperial} unread={unread.includes(s.id)}
                dragging={drag?.id === s.id} grab={mv} dragProps={mv ? bind(s.id, d.date, s.title) : {}} editing={editing}
                onOpen={() => { if (!suppressClick.current) openPage(s, d.date) }}
                onEdit={() => onOpen(s, d.date)}
                onShift={mv && c?.status !== 'missed' ? { [-1]: shift(s, d.date, -1), 1: shift(s, d.date, 1) } : undefined}
                onMove={mv && c?.status !== 'missed' ? () => onMoving({ session: s, date: d.date }) : undefined}
                onFix={editable && cal && c?.status === 'missed' && c.missed?.this_week ? () => setFix({ s, date: d.date }) : undefined} />
            )
          })}
          {extra}
          {/* Workouts from your apps that aren't plan sessions (cal.extra): so a rest day you trained on says so. */}
          {done.map((a, i) => (
            <button key={`x${a.id ?? a.key ?? i}`} type="button" disabled={a.id == null && !a.key} onClick={() => openActivity(a.id ?? a.key!)}
              aria-label={`${a.name}, done. Open the workout`}
              className="flex min-h-11 w-full items-center gap-1.5 rounded-lg text-left text-meta text-(--accent) active:bg-(--bg-inset) disabled:cursor-default">
              <Check className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{a.name}{a.km ? ` · ${fmtDist(a.km, imperial, a.sport === 'swim' ? 'swim' : a.sport === 'bike' ? 'bike' : 'run')}` : a.minutes ? ` · ${fmtDuration(a.minutes)}` : ''}</span>
              {(a.id != null || a.key) && <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
            </button>
          ))}
          {!work.length && !extra && !done.length && <p className={cn('text-small text-(--text-muted)', !quiet && 'py-2')}>{over ? 'Drop here' : 'Rest'}</p>}
        </div>
        {canAdd && (editing || !compact) && (
          <button type="button" aria-label={`Add a workout on ${fmtDay(d.date)}`} onClick={() => onAdd!(d.date)}
            className="hit-44 mt-1.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-dashed border-(--border-strong) text-(--text-muted) active:bg-(--bg-inset)">
            <Plus className="size-4" />
          </button>
        )}
      </div>
    )
  }

  /** What the week prescribes: focus, key sessions, hours (Week view card and List week headers). */
  const keySessions = (w: PlanWeekBuilt) => w.days.flatMap((d) => d.sessions
    .filter((s) => s.sport !== 'rest' && (s.kind === 'long' || s.kind === 'race' || cal?.sessions[s.id]?.hard))
    .map((s) => `${s.title} (${fmtDay(d.date, { weekday: 'short' })})`))
  const prescription = (w: PlanWeekBuilt) => {
    const keys = keySessions(w)
    if (!w.focus && !keys.length) return null
    return (
      <div className="flex flex-col gap-0.5 border-b border-(--border) px-4 py-2.5 text-small leading-snug">
        {w.focus && <p className="text-(--text-secondary)">{w.focus}</p>}
        {keys.length > 0 && <p className="text-(--text-muted)"><span className="font-semibold text-(--text-secondary)">Key workouts:</span> {keys.join(' · ')}</p>}
      </div>
    )
  }

  const weekNav = (
    <div className="flex items-center gap-1 px-1">
      <button type="button" className="modal-close" aria-label="Previous week" disabled={pos <= 0}
        onClick={() => onWeek(plan.weeks[pos - 1]!.index)}><ChevronLeft className="size-5" /></button>
      <div className="min-w-0 flex-1 text-center">
        <p className="text-caption font-semibold text-(--text-muted)">
          Week {week.index} of {plan.weeks.length} · {weekPhaseLabel(week)} · {week.hours}h
        </p>
        <p className="text-meta text-(--text-muted)">
          {fmtDay(week.days[0]!.date, { month: 'short', day: 'numeric' })} – {fmtDay(week.days[week.days.length - 1]!.date, { month: 'short', day: 'numeric' })}
          {week.index === plan.current_week ? ' · this week' : plan.current_week && <> · <button type="button" className="hit-44 text-(--accent) underline-offset-2 hover:underline" onClick={() => onWeek(plan.current_week!)}>back to this week</button></>}
        </p>
      </div>
      <button type="button" className="modal-close" aria-label="Next week" disabled={pos >= plan.weeks.length - 1}
        onClick={() => onWeek(plan.weeks[pos + 1]!.index)}><ChevronRight className="size-5" /></button>
    </div>
  )

  return (
    <section ref={rootRef} className="flex scroll-mt-4 flex-col gap-1.5" data-cal-root data-no-tab-swipe={drag ? '' : undefined} aria-label="Plan calendar">
      <div className="w-full"><Segmented label="Calendar view" value={view} options={[['day', 'Today'], ['week', 'Week'], ['list', 'List'], ['month', 'Month']] as const}
        onChange={(v) => v === 'day' ? openDay(view === 'day' ? day : today) : setView(v)} /></div>
      <div className="flex items-center gap-2 px-1">
        <button type="button" onClick={() => setOverview(true)}
          className="flex min-h-11 items-center gap-1.5 text-small font-medium text-(--accent)">
          <MapIcon className="size-4" aria-hidden />Plan overview
        </button>
        {cal?.total.run && cal.total.run.planned > 0 && (
          <span className="min-w-0 flex-1 truncate text-right font-mono text-meta tabular-nums text-(--text-muted)">
            Run {fmtDist(cal.total.run.done, imperial, 'run', { decimals: 0 })} of {fmtDist(cal.total.run.planned, imperial, 'run', { decimals: 0 })}
          </span>
        )}
        {(view === 'week' || view === 'list') && editToggle}
      </div>

      {change && change.rebalanced.length > 0 && (
        <div className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5" role="status">
          <p className="text-small font-semibold text-(--accent)">rabbt re-balanced your week</p>
          <ul className="flex flex-col gap-0.5 text-small leading-snug text-(--text)">
            {change.rebalanced.map((l) => <li key={l}>{l}</li>)}
          </ul>
          <div className="flex gap-2">
            <Button variant="primary" className="h-9 px-4 text-small" onClick={() => setChange(null)}>Accept</Button>
            {change.rebalance_undo && (
              <Button variant="default" className="h-9 gap-1 px-3 text-small"
                onClick={() => { const id = change.rebalance_undo!; setChange(null); void run(undoChange(id)) }}>
                <Undo2 className="size-4" /> Undo
              </Button>
            )}
          </div>
        </div>
      )}

      {view === 'day' ? (
        <PlanDay plan={plan} cal={cal} imperial={imperial} today={today} date={day} onDate={pickDay} unread={unread} hidden={hidden}
          extra={dayExtra?.(day)}
          onAdd={onAdd && day >= today && day <= plan.race_date ? () => onAdd(day) : undefined}
          actions={(s) => {
            const c = cal?.sessions[s.id]
            const mv = movable(s, day)
            return {
              onEdit: (x) => onOpen(x, day),
              onOpenPage: (x) => openPage(x, day),
              onMove: mv && c?.status !== 'missed' ? (x, mode) => onMoving({ session: x, date: day, mode }) : undefined,
              onFix: editable && cal && c?.status === 'missed' && c.missed?.this_week ? (x) => setFix({ s: x, date: day }) : undefined,
              onStart: onStart ? (x) => onStart(x, day) : undefined,
              onAsk: onAsk ? (x) => onAsk(x, day) : undefined,
            }
          }} />
      ) : view === 'week' ? (
        <>
          {weekNav}
          <Card>
            {cal && <WeekMiles week={week.start} miles={cal.weeks[week.start]} imperial={imperial} editable={editable}
              onGoal={async (sp, km) => { await run(setWeekGoal(week.start, sp, km)) }} />}
            {prescription(week)}
            <div className="divide-y divide-(--border)">{week.days.map((d) => dayRow(d))}</div>
          </Card>
          <p className="px-4 text-small leading-snug text-(--text-muted)">
            {editable && cal ? (editing ? 'Press and hold a workout to drag it, or use Earlier / Later. rabbt re-balances the week.' : 'Tap a workout to see it in full. Tap Edit to move things around.') : 'Tap a workout to see it in full.'}
          </p>
        </>
      ) : view === 'list' ? (
        <PlanList plan={plan} cal={cal} imperial={imperial} today={today} dayRow={dayRow} prescription={prescription} editing={editing}
          onWeek={(i) => { onWeek(i); setView('week') }} />
      ) : (
        <MonthView plan={plan} cal={cal} imperial={imperial} today={today} anchor={week.start}
          onPickDay={openDay} />
      )}

      {error && !toast && <p className="px-4 text-small text-(--danger)" role="alert">{error}</p>}

      {drag && (
        <div className="pointer-events-none fixed z-(--z-popover) -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--text) px-3 py-1.5 text-small text-(--bg) shadow-lg"
          style={{ left: drag.x, top: drag.y }} aria-hidden>
          {drag.title}{drag.over && drag.over !== drag.from ? ` → ${fmtDay(drag.over, { weekday: 'short', day: 'numeric' })}` : ''}
        </div>
      )}
      <div role="status" aria-live="polite" aria-atomic="true">
        {toast && (
          <div key={toast.n} className="fixed left-1/2 z-(--z-toast) flex max-w-[calc(100vw-32px)] -translate-x-1/2 items-center gap-3 rounded-full bg-(--text) py-1.5 pl-4 pr-1.5 text-small text-(--bg) shadow-lg"
            style={{ bottom: 'calc(96px + env(safe-area-inset-bottom))' }}>
            <span className="min-w-0 truncate">{toast.text}</span>
            {toast.undo && (
              <button type="button" className="hit-44 shrink-0 rounded-full px-3 py-1 font-semibold text-(--bg) underline-offset-2 hover:underline"
                onClick={() => { const id = toast.undo!; setToast(null); setChange(null); void run(undoChange(id)) }}>Undo</button>
            )}
          </div>
        )}
      </div>

      {moving && cal && <MoveSheet key={`${moving.session.id}:${moving.mode ?? 'move'}`} session={moving.session} from={moving.date} initialMode={moving.mode}
        plan={plan} cal={cal} today={today} onClose={() => onMoving(null)} run={run} />}
      {overview && <PlanOverview plan={plan} onAdjust={onAdjust ? () => { setOverview(false); onAdjust() } : undefined} onClose={() => setOverview(false)} onWeek={(i) => { onWeek(i); setView('week') }} />}
      {fix && cal && cal.sessions[fix.s.id] && (
        <FixSheet s={fix.s} date={fix.date} c={cal.sessions[fix.s.id]!} plan={plan} cal={cal} today={today} onClose={() => setFix(null)} run={run} />
      )}
    </section>
  )
}

/** List view: the plan as a scrolling agenda, a few weeks at a time, grouped by week with what
 *  each week prescribes. Same day rows (and drag / Edit controls) as the Week view. */
function PlanList({ plan, cal, imperial, today, dayRow, prescription, editing, onWeek }: {
  plan: BuiltPlan; cal: CalView | null; imperial: boolean; today: string
  dayRow: (d: { date: string; sessions: PlanSession[] }, compact?: boolean) => React.ReactNode
  prescription: (w: PlanWeekBuilt) => React.ReactNode
  editing: boolean
  onWeek: (index: number) => void
}) {
  const STEP = 4
  const here = Math.max(0, plan.weeks.findIndex((w) => w.days.some((d) => d.date >= today)))
  const [from, setFrom] = useState(here)
  const [to, setTo] = useState(Math.min(plan.weeks.length, here + STEP))
  const shown = plan.weeks.slice(from, to)
  const sessionsOf = (w: PlanWeekBuilt) => w.days.flatMap((d) => d.sessions.filter((s) => s.sport !== 'rest' && s.kind !== 'race'))
  return (
    <div className="flex flex-col gap-3">
      <p className="px-1 text-small text-(--text-muted)">
        Weeks {plan.weeks[from]!.index}–{plan.weeks[to - 1]!.index} of {plan.weeks.length}. {editing ? 'Press and hold a workout to drag it, or use Earlier / Later.' : 'Tap a workout to see it in full.'}
      </p>
      {from > 0 && (
        <Button variant="default" className="h-11 text-small" onClick={() => setFrom(Math.max(0, from - STEP))}>Show earlier weeks</Button>
      )}
      {shown.map((w) => {
        const ss = sessionsOf(w)
        const done = ss.filter((s) => cal?.sessions[s.id]?.status === 'done').length
        const miles = cal?.weeks[w.start]
        const goals = miles ? (Object.entries(miles) as [DistSport, Mileage][]).filter(([, m]) => m.goal > 0) : []
        return (
          <Card key={w.start}>
            <button type="button" onClick={() => onWeek(w.index)} aria-label={`Open week ${w.index} in the Week view`}
              className="flex w-full items-center gap-2 border-b border-(--border) px-4 py-2.5 text-left active:bg-(--bg-inset)">
              <span className={cn('size-2.5 shrink-0 rounded-full', `phase-${w.recovery && w.phase !== 'taper' && w.phase !== 'race' ? 'recovery' : w.phase}`)} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-caption font-semibold text-(--text-muted)">
                  Week {w.index} · {weekPhaseLabel(w)} · {w.hours}h{w.index === plan.current_week ? ' · this week' : ''}
                </span>
                <span className="block text-meta text-(--text-secondary)">
                  {fmtDay(w.days[0]!.date, { month: 'short', day: 'numeric' })} – {fmtDay(w.days[w.days.length - 1]!.date, { month: 'short', day: 'numeric' })}
                  {goals.map(([sp, m]) => ` · ${SPORT_DIST_LABEL[sp]} ${fmtDist(m.goal, imperial, sp, { decimals: 0 })}`).join('')}
                  {ss.length > 0 && (done > 0 || w.days[0]!.date <= today) ? ` · ${done}/${ss.length} done` : ''}
                </span>
              </span>
              <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
            </button>
            {prescription(w)}
            <div className="divide-y divide-(--border)">{w.days.map((d) => dayRow(d, true))}</div>
          </Card>
        )
      })}
      {to < plan.weeks.length ? (
        <Button variant="default" className="h-11 text-small" onClick={() => setTo(Math.min(plan.weeks.length, to + STEP))}>
          Show {Math.min(STEP, plan.weeks.length - to)} more week{plan.weeks.length - to === 1 ? '' : 's'}
        </Button>
      ) : (
        <p className="px-4 text-center text-meta text-(--text-muted)">That's the whole plan, through race day.</p>
      )}
    </div>
  )
}

function MonthView({ plan, cal, imperial, today, anchor, onPickDay }: {
  plan: BuiltPlan; cal: CalView | null; imperial: boolean; today: string; anchor: string; onPickDay: (d: string) => void
}) {
  const [month, setMonth] = useState(() => (anchor < plan.first_day ? plan.first_day : anchor).slice(0, 7))
  const byDate = useMemo(() => {
    const m = new Map<string, PlanSession[]>()
    for (const w of plan.weeks) for (const d of w.days) m.set(d.date, d.sessions.filter((s) => s.sport !== 'rest'))
    return m
  }, [plan])
  const first = `${month}-01`
  const firstMon = mondayOf(first)
  const cells: string[] = []
  for (let d = firstMon; d.slice(0, 7) <= month || weekdayIdx(d) !== 0; d = addDays(d, 1)) cells.push(d)
  const months = Object.keys(cal?.months ?? {}).sort()
  const lo = months[0] ?? plan.start.slice(0, 7), hi = months[months.length - 1] ?? plan.race_date.slice(0, 7)
  const shift = (n: number) => {
    const [y, m] = month.split('-').map(Number) as [number, number]
    const d = new Date(y, m - 1 + n, 1)
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  const tot = cal?.months[month]
  const label = new Date(`${first}T12:00:00`).toLocaleDateString([], { month: 'long', year: 'numeric' })
  return (
    <>
      <div className="flex items-center gap-1 px-1">
        <button type="button" className="modal-close" aria-label="Previous month" disabled={month <= lo} onClick={() => shift(-1)}><ChevronLeft className="size-5" /></button>
        <div className="min-w-0 flex-1 text-center">
          <p className="text-caption font-semibold text-(--text-muted)">{label}</p>
          {tot && (
            <p className="truncate font-mono text-meta tabular-nums text-(--text-secondary)">
              {(Object.entries(tot) as [DistSport, { done: number; planned: number }][]).filter(([, v]) => v.planned > 0 || v.done > 0)
                .map(([sp, v]) => `${SPORT_DIST_LABEL[sp]} ${fmtDist(v.done, imperial, sp, { decimals: 0 })} of ${fmtDist(v.planned, imperial, sp, { decimals: 0 })}`).join(' · ')}
            </p>
          )}
        </div>
        <button type="button" className="modal-close" aria-label="Next month" disabled={month >= hi} onClick={() => shift(1)}><ChevronRight className="size-5" /></button>
      </div>
      <Card className="p-1">
        {/* Day buttons carry the full date in their names; the letters above are visual only. Tight
            gaps keep each day close to a 44px target on a 375px phone. */}
        <div className="grid grid-cols-[repeat(7,minmax(0,1fr))_auto] gap-px" role="group" aria-label={label}>
          {WD.map((w) => <span key={w} aria-hidden className="pb-1 text-center text-caption font-semibold uppercase text-(--text-muted)">{w.charAt(0)}</span>)}
          <span aria-hidden className="pb-1 pr-1 text-right text-caption font-semibold uppercase text-(--text-muted)">{imperial ? 'mi' : 'km'}</span>
          {cells.map((d, i) => {
            const ss = byDate.get(d) ?? []
            const inMonth = d.slice(0, 7) === month
            const isToday = d === today
            const statuses = ss.map((s) => cal?.sessions[s.id]?.status ?? 'planned')
            const wk = i % 7 === 6 ? cal?.weeks[cells[i - 6]!]?.run : undefined
            const cell = (
              <button key={d} type="button" disabled={!ss.length && !byDate.has(d)} onClick={() => onPickDay(d)}
                aria-label={`${fmtDay(d, { weekday: 'long', month: 'long', day: 'numeric' })}: ${ss.length ? ss.map((s, j) => `${s.title} ${statuses[j]}`).join(', ') : 'rest'}`}
                className={cn('flex min-h-11 flex-col items-center gap-0.5 rounded-lg py-1 disabled:cursor-default', !inMonth && 'opacity-40',
                  isToday && 'ring-1 ring-(--accent)', ss.some((s) => s.kind === 'race') && 'bg-(--brand)/10')}>
                <span className={cn('text-meta tabular-nums', isToday ? 'font-semibold text-(--accent)' : 'text-(--text-secondary)')}>{Number(d.slice(8))}</span>
                <span className="flex flex-wrap justify-center gap-0.5">
                  {ss.slice(0, 3).map((s, j) => {
                    const Icon = s.kind === 'race' ? Flag : SPORT_ICON[s.sport]
                    const st = statuses[j]
                    return <Icon key={s.id} aria-hidden className={cn('size-3.5', st === 'done' ? 'text-(--accent)' : st === 'missed' ? 'text-(--danger)' : st === 'skipped' ? 'text-(--text-muted) opacity-50' : 'text-(--text-muted)')} />
                  })}
                </span>
              </button>
            )
            return i % 7 === 6 ? [cell, (
              <span key={`${d}-w`} className="flex min-h-11 items-center justify-end pl-1 font-mono text-caption tabular-nums text-(--text-muted)">
                {wk && wk.goal > 0 ? `${toUnit(wk.done, imperial, 'run')}/${toUnit(wk.goal, imperial, 'run')}` : ''}
              </span>)] : cell
          })}
        </div>
      </Card>
      <p className="px-4 text-meta text-(--text-muted)">Tap a day to see it in full. Right column: done / goal per week.</p>
    </>
  )
}
