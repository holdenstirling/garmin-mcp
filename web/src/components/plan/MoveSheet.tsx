// Move one plan session to another day (or swap two whole days). Shared by the plan calendar
// (Week and Day views) and the home "Up next" card (MoveSessionSheet loads what it needs).
// Each day lists what's already on it and flags clashes: two hard days together, a day you
// don't usually train. The server (plancal.py) re-balances the week and returns a summary
// that can be undone.
import { useEffect, useMemo, useState } from 'react'
import { TriangleAlert, ArrowLeftRight, Check, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { RabbitLoader } from '@/components/RabbitLoader'
import { cn } from '@/lib/utils'
import { haptic } from '@/lib/haptics'
import { getPlan, type BuiltPlan, type PlanSession } from '@/lib/plan'
import { getCalendar, moveSession, swapDays, undoChange, type CalChange, type CalResult, type CalView } from '@/lib/plancal'
import { Card, Chip, ChipRow } from './ui'
import { SPORT_ICON, fmtDay } from './PlanParts'

export const addDays = (d: string, n: number) => {
  const x = new Date(`${d}T12:00:00`)
  x.setDate(x.getDate() + n)
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
}
/** 0 = Monday */
export const weekdayIdx = (d: string) => (new Date(`${d}T12:00:00`).getDay() + 6) % 7
export const mondayOf = (d: string) => addDays(d, -weekdayIdx(d))

type DayInfo = { date: string; sessions: PlanSession[]; off: boolean; clash: string | null }

export function MoveSheet({ session, from, plan, cal, today, initialMode = 'move', inline, onClose, run }: {
  session: PlanSession; from: string; plan: BuiltPlan; cal: CalView; today: string
  initialMode?: 'move' | 'swap'
  /** show the result and Undo inside the sheet (home); otherwise close and let the calendar toast it */
  inline?: boolean
  onClose: () => void
  /** resolves to the result, or null when it failed (the caller reports the error) */
  run: (p: Promise<CalResult>) => Promise<CalResult | null>
}) {
  const [mode, setMode] = useState<'move' | 'swap'>(initialMode)
  const [pick, setPick] = useState<string | null>(null)
  const [busy, setBusy] = useState<'go' | 'undo' | null>(null)
  const [done, setDone] = useState<{ change: CalChange; to: string } | null>(null)
  const [undone, setUndone] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const byDate = useMemo(() => {
    const m = new Map<string, PlanSession[]>()
    for (const w of plan.weeks) for (const d of w.days) m.set(d.date, d.sessions.filter((s) => s.sport !== 'rest'))
    return m
  }, [plan])
  const hard = (s: PlanSession) => !!cal.sessions[s.id]?.hard
  const movingHard = hard(session)
  const others = (d: string) => (byDate.get(d) ?? []).filter((s) => s.id !== session.id)
  const info = (d: string): DayInfo => {
    const ss = others(d)
    let clash: string | null = null
    if (mode === 'move' && movingHard) {
      if (ss.some(hard)) clash = 'Already a hard day'
      else if (others(addDays(d, -1)).some(hard) || others(addDays(d, 1)).some(hard)) clash = 'Next to a hard day'
    }
    return { date: d, sessions: ss, off: !cal.available_days.includes(weekdayIdx(d)), clash }
  }
  const valid = (d: string) => d >= today && d <= plan.race_date && d !== from && byDate.has(d)
  const mon = mondayOf(from < today ? today : from)
  const thisWeek = Array.from({ length: 7 }, (_, i) => addDays(mon, i)).filter(valid).map(info)
  const nextWeek = Array.from({ length: 7 }, (_, i) => addDays(mon, i + 7)).filter(valid).map(info)

  const tomorrow = addDays(today, 1)
  const tomorrowOk = mode === 'move' && valid(tomorrow)
  const best = mode === 'move'
    ? [...thisWeek, ...nextWeek].filter((d) => d.date > tomorrow && !d.clash)
        .sort((a, b) => Number(!!a.clash) - Number(!!b.clash) || Number(a.off) - Number(b.off) || a.sessions.length - b.sessions.length || a.date.localeCompare(b.date))[0]
    : undefined

  useEffect(() => { setPick(null); setErr(null) }, [mode])

  async function go() {
    if (!pick) return
    setBusy('go'); setErr(null)
    const r = await run(mode === 'move' ? moveSession(session.id, pick) : swapDays(from, pick)).catch((e: Error) => { setErr(e.message); return null })
    setBusy(null)
    if (!r) return
    haptic()
    if (inline && r.change) setDone({ change: r.change, to: pick })
    else onClose()
  }
  async function undo() {
    if (!done?.change.id) return
    setBusy('undo'); setErr(null)
    const r = await run(undoChange(done.change.id)).catch((e: Error) => { setErr(e.message); return null })
    setBusy(null)
    if (r) setUndone(true)
  }

  const dayLabel = (d: string) => d === today ? 'Today' : d === tomorrow ? 'Tomorrow' : fmtDay(d, { weekday: 'long', month: 'short', day: 'numeric' })
  const verb = mode === 'move' ? 'Move' : 'Swap with'
  const body = 'settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]'

  if (done) {
    return (
      <Sheet title={undone ? 'Put back' : 'Moved'} onClose={onClose} bodyClassName={body}>
        <div role="status" aria-live="polite" className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-3">
          <p className="flex items-center gap-1.5 text-body font-semibold text-(--accent)">
            <Check className="size-5" aria-hidden />
            {undone ? `${session.title} is back on ${dayLabel(from)}.` : done.change.summary}
          </p>
          {!undone && done.change.rebalanced.length > 0 && (
            <>
              <p className="text-small text-(--text-secondary)">rabbt also re-balanced your week:</p>
              <ul className="flex list-disc flex-col gap-0.5 pl-5 text-small leading-snug text-(--text)">
                {done.change.rebalanced.map((l) => <li key={l}>{l}</li>)}
              </ul>
            </>
          )}
        </div>
        {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
        <div className="flex gap-2">
          <Button variant="primary" className="h-11 flex-1 text-body" onClick={onClose}>Done</Button>
          {!undone && done.change.id && (
            <Button variant="default" className="h-11 gap-1.5 px-4 text-body" loading={busy === 'undo'} onClick={() => void undo()}>
              <Undo2 className="size-5" aria-hidden /> Undo
            </Button>
          )}
        </div>
      </Sheet>
    )
  }

  const Icon = SPORT_ICON[session.sport]
  const dayRow = (d: DayInfo) => {
    const on = pick === d.date
    return (
      <li key={d.date}>
        <button type="button" aria-pressed={on} onClick={() => setPick(d.date)}
          aria-label={`${verb} ${dayLabel(d.date)}: ${d.sessions.length ? d.sessions.map((s) => s.title).join(', ') : 'rest day'}${d.clash ? `. ${d.clash}` : ''}${d.off ? '. Not one of your usual training days' : ''}`}
          className={cn('flex min-h-12 w-full items-center gap-3 px-3.5 py-2 text-left active:bg-(--bg-inset)', on && 'bg-(--accent-subtle)')}>
          <span className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border', on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border-strong)')}>
            {on && <Check className="size-3.5" aria-hidden />}
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn('block text-body font-medium', d.off ? 'text-(--text-secondary)' : 'text-(--text)')}>
              {dayLabel(d.date)}{best?.date === d.date && best.date !== tomorrow && <span className="ml-1.5 text-meta font-semibold text-(--accent)">Best fit</span>}
            </span>
            <span className="block text-small text-(--text-muted)">
              {d.sessions.length ? d.sessions.map((s) => s.title).join(' · ') : 'Rest day, nothing planned'}
              {d.off && ' · not a usual training day'}
            </span>
          </span>
          {d.clash && (
            <span className="flex shrink-0 items-center gap-1 text-meta font-medium text-(--warning-text)">
              <TriangleAlert className="size-3.5" aria-hidden />{d.clash}
            </span>
          )}
        </button>
      </li>
    )
  }
  const group = (label: string, days: DayInfo[]) => days.length > 0 && (
    <Card className="shrink-0">
      <p className="border-b border-(--border) px-4 py-2.5 text-meta font-semibold text-(--text-secondary)">{label}</p>
      <ul className="divide-y divide-(--border)">{days.map(dayRow)}</ul>
    </Card>
  )

  return (
    <Sheet title={`Move ${session.title}`} onClose={onClose} bodyClassName={body}
      footer={
        <div className="flex gap-2 border-t border-(--border) bg-(--bg) px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <Button variant="primary" className="h-11 flex-1 text-body" disabled={!pick} loading={busy === 'go'} onClick={() => void go()}>
            {pick ? `${verb} ${dayLabel(pick).split(',')[0]}` : mode === 'move' ? 'Pick a day' : 'Pick a day to swap with'}
          </Button>
        </div>
      }>
      <div className="flex items-center gap-3 px-1">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><Icon className="size-5" aria-hidden /></span>
        <p className="min-w-0 flex-1 text-small leading-snug text-(--text-secondary)">
          Now on {from === today || from === tomorrow ? dayLabel(from).toLowerCase() : dayLabel(from)}. rabbt keeps hard days apart and your weekly miles on track.
        </p>
      </div>
      <ChipRow>
        <Chip selected={mode === 'move'} onClick={() => setMode('move')}>Move this workout</Chip>
        <Chip selected={mode === 'swap'} onClick={() => setMode('swap')}><ArrowLeftRight className="mr-1 inline size-4" aria-hidden />Swap whole days</Chip>
      </ChipRow>
      {mode === 'move' && (tomorrowOk || best) && (
        <ChipRow>
          {tomorrowOk && <Chip selected={pick === tomorrow} onClick={() => setPick(tomorrow)}>Tomorrow</Chip>}
          {best && best.date !== tomorrow && (
            <Chip selected={pick === best.date} onClick={() => setPick(best.date)}>Best fit · {fmtDay(best.date, thisWeek.some((d) => d.date === best.date) ? { weekday: 'short' } : { weekday: 'short', month: 'short', day: 'numeric' })}</Chip>
          )}
        </ChipRow>
      )}
      {group('This week', thisWeek)}
      {group('Next week', nextWeek)}
      {!thisWeek.length && !nextWeek.length && <p className="px-1 text-body text-(--text-secondary)">There's no free day left before race day to move this to.</p>}
      {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
      {!inline && <p className="px-1 text-meta text-(--text-muted)">Tip: on the week calendar you can also press and hold a workout, then drag it to a day.</p>}
    </Sheet>
  )
}

/** Self-contained Move for a session id (home "Up next"): loads the plan and calendar first. */
export function MoveSessionSheet({ sessionId, onClose, onMoved }: { sessionId: string; onClose: () => void; onMoved: () => void }) {
  const [data, setData] = useState<{ plan: BuiltPlan; cal: CalView } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    Promise.all([getPlan(), getCalendar()]).then(([p, c]) => {
      if (p.plan && c.cal) setData({ plan: p.plan, cal: c.cal })
      else setErr("This workout isn't in a plan built in rabbt, so it can't be moved here.")
    }, (e: Error) => setErr(e.message))
  }, [])
  const hit = useMemo(() => {
    if (!data) return null
    for (const w of data.plan.weeks) for (const d of w.days) for (const s of d.sessions) if (s.id === sessionId) return { s, date: d.date }
    return null
  }, [data, sessionId])
  if (!data || !hit) {
    return (
      <Sheet title="Move this session" onClose={onClose} bodyClassName="flex flex-col gap-4 p-4 pb-[max(16px,env(safe-area-inset-bottom))]">
        {err || (data && !hit)
          ? <p className="text-body text-(--text-secondary)" role="alert">{err ?? "Couldn't find this workout in your plan. Open Schedule to move it."}</p>
          : <RabbitLoader className="py-10" label="Loading your week" cycle={['Loading your week…', 'Finding free days…']} />}
      </Sheet>
    )
  }
  return (
    <MoveSheet session={hit.s} from={hit.date} plan={data.plan} cal={data.cal} today={data.cal.today} inline onClose={onClose}
      run={async (p) => { const r = await p; setData({ plan: r.plan, cal: r.cal }); onMoved(); return r }} />
  )
}
