// Build → review → adjust → feedback (server: planflow.py, races.py).
//   * PlanSummaryView: what a plan prescribes (setup Review, Adjust my plan): weeks and the
//     hours ramp, phases with dates, the long-session progression and the first two weeks.
//   * LeverFields: the few levers people actually change (training days, long day, hours a
//     week, how hard it should feel, start date).
//   * AdjustPlanSheet: the levers any time, with what changes shown before applying + Undo.
//   * RaceSwitcher: which race the plan trains for; each race keeps its own plan.
//   * WeekCheckCard: "How was this week?" (Friday to Monday, or on demand) -> suggested
//     changes to next week, accepted or skipped in one tap.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, CalendarCheck, Check, ChevronDown, Flag, MessageCircleHeart, Plane, Plus, SlidersHorizontal, Trophy, Undo2 } from 'lucide-react'
import { Sheet } from '@/components/ui/Sheet'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { openTravel } from '@/lib/plantools'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import { PHASE_LABEL, fmtMin, type AthleteFull, type BuiltPlan } from '@/lib/plan'
import {
  INTENSITY, WEEKDAYS, applyLevers, announcePlanReload, getRaces, getWeekCheck, makeTuneUp, previewPlan, trainFor, undoLevers, weekCheck,
  type CheckinAnswers, type CheckinProposal, type Levers, type PlanDiff, type PlanSummary, type Race,
} from '@/lib/planflow'
import { Card, Chip, ChipRow, Field, NumberStepper, inputCls } from './ui'
import { SPORT_ICON, fmtDay } from './PlanParts'
import { useSick } from './SickHost'

const bodyCls = 'settings flex flex-col gap-4 overflow-y-auto p-4 pb-[max(16px,env(safe-area-inset-bottom))]'
const day = (d: string) => fmtDay(d, { weekday: 'short', month: 'short', day: 'numeric' })

// ------------------------------------------------------------- summary --
export function PlanSummaryView({ s, compact }: { s: PlanSummary; compact?: boolean }) {
  const max = Math.max(...s.hours, 1)
  const longs = s.long_minutes.filter((m) => m > 0)
  const longLine = longs.length ? [longs[0], longs[Math.min(2, longs.length - 1)], Math.max(...longs)] : []
  const firstWeeks = s.first_two_weeks.filter((d) => d.sessions.length)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1 px-1">
        <p className="text-lead font-semibold leading-snug text-(--text)">
          {s.weeks} weeks, {s.start_hours === s.peak_hours ? `about ${s.peak_hours}h a week` : `building from about ${s.start_hours}h to ${s.peak_hours}h a week`}
        </p>
        {s.first_session && (
          <p className="text-small text-(--text-secondary)">
            Starts {day(s.first_session.date)} with <b className="font-semibold text-(--text)">{s.first_session.title} · {fmtMin(s.first_session.minutes)}</b>
          </p>
        )}
        {s.note && <p className="text-small text-(--warning-text)">{s.note}</p>}
      </div>
      <Card className="p-3">
        <div className="flex h-16 items-end gap-[2px]" role="img"
          aria-label={`Weekly hours from ${s.hours[0] ?? 0} to a peak of ${s.peak_hours}, over ${s.weeks} weeks`}>
          {s.hours.map((h, i) => (
            <span key={i} className={cn('block min-w-0 flex-1 rounded-t-[3px]', `phase-${phaseAt(s, i)}`)}
              style={{ height: `${Math.max(8, (h / max) * 100)}%` }} />
          ))}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {s.phases.filter((p, i, a) => a.findIndex((x) => x.phase === p.phase) === i).map((p) => (
            <span key={p.phase} className="flex items-center gap-1.5 text-caption text-(--text-muted)">
              <span className={cn('size-2 rounded-full', `phase-${p.phase}`)} />{PHASE_LABEL[p.phase]}
            </span>
          ))}
        </div>
      </Card>
      {!compact && (
        <ol className="flex flex-col gap-1.5">
          {s.phases.map((p, i) => (
            <li key={i} className="flex items-start gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5">
              <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full', `phase-${p.phase}`)} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-body font-semibold text-(--text)">
                  {PHASE_LABEL[p.phase]} · {p.weeks} {p.weeks === 1 ? 'week' : 'weeks'}
                </span>
                <span className="block text-meta text-(--text-muted)">
                  {day(p.from)} – {day(p.to)} · {p.hours_from === p.hours_to ? `${p.hours_from}h` : `${p.hours_from}h → ${p.hours_to}h`} a week
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
      {longLine.length > 0 && (
        <p className="px-1 text-small text-(--text-secondary)">
          <b className="font-semibold text-(--text)">Long workout:</b> {longLine[0]}′ to start, {longLine[1]}′ by week 3, up to {longLine[2]}′ at its longest. It grows about 10% a week at most.
        </p>
      )}
      {!compact && firstWeeks.length > 0 && (
        <Card>
          <Field label="Your first two weeks">
            <ul className="flex flex-col">
              {firstWeeks.map((d) => (
                <li key={d.date} className="flex min-h-10 items-center gap-3 border-b border-(--border) py-1.5 last:border-b-0">
                  <span className="w-20 shrink-0 text-meta text-(--text-muted)">{day(d.date)}</span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    {d.sessions.map((x, i) => {
                      const I = SPORT_ICON[x.sport as keyof typeof SPORT_ICON]
                      return (
                        <span key={i} className="flex items-center gap-1.5 text-small text-(--text)">
                          {I && <I className="size-4 shrink-0 text-(--text-muted)" aria-hidden />}
                          <span className="truncate">{x.title}</span>
                          <span className="ml-auto shrink-0 font-mono tabular-nums text-(--text-muted)">{fmtMin(x.minutes)}</span>
                        </span>
                      )
                    })}
                  </span>
                </li>
              ))}
            </ul>
          </Field>
        </Card>
      )}
    </div>
  )
}

function phaseAt(s: PlanSummary, i: number): string {
  let n = 0
  for (const p of s.phases) { n += p.weeks; if (i < n) return p.phase }
  return 'race'
}

// -------------------------------------------------------------- levers --
export function LeverFields({ v, set, start, setStart, minStart, maxStart }: {
  v: Levers; set: (p: Partial<Levers>) => void
  start?: string; setStart?: (d: string) => void; minStart?: string; maxStart?: string
}) {
  const days = v.available_days ?? []
  return (
    <Card>
      <Field label="Days you can train" hint={`${days.length} ${days.length === 1 ? 'day' : 'days'} a week`}>
        <ChipRow>
          {WEEKDAYS.map(([d, l]) => (
            <Chip key={d} selected={days.includes(d)}
              onClick={() => set({ available_days: days.includes(d) ? days.filter((x) => x !== d) : WEEKDAYS.map(([k]) => k).filter((k) => k === d || days.includes(k)) })}>{l}</Chip>
          ))}
        </ChipRow>
      </Field>
      <Field label="Long session on" className="border-t border-(--border)">
        <ChipRow>
          {WEEKDAYS.filter(([d]) => days.includes(d)).map(([d, l]) => (
            <Chip key={d} selected={v.long_day === d} onClick={() => set({ long_day: d })}>{l}</Chip>
          ))}
        </ChipRow>
      </Field>
      <Field label="Most hours a week" className="border-t border-(--border)" hint="A ceiling: rabbt starts near what you do now and builds slowly toward it.">
        <NumberStepper label="hours a week" value={v.weekly_hours ?? null} min={1} max={25} step={0.5} decimals={1} suffix="h"
          typical={[3, 4, 5, 6, 8, 10, 12]} onChange={(n) => set({ weekly_hours: n })} />
      </Field>
      <Field label="How hard should it feel?" className="border-t border-(--border)">
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="How hard should it feel?">
          {INTENSITY.map(([k, l, hint]) => {
            const on = (v.plan_intensity ?? 'normal') === k
            return (
              <button key={k} type="button" role="radio" aria-checked={on} onClick={() => set({ plan_intensity: k })}
                className={cn('flex min-h-16 flex-col items-start gap-0.5 rounded-xl border px-2.5 py-2 text-left',
                  on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
                <span className={cn('text-small font-semibold', on ? 'text-(--accent)' : 'text-(--text)')}>{l}</span>
                <span className="text-caption leading-tight text-(--text-muted)">{hint}</span>
              </button>
            )
          })}
        </div>
      </Field>
      {setStart && (
        <Field label="Start the plan on" className="border-t border-(--border)">
          <input type="date" className={inputCls} value={start ?? ''} min={minStart} max={maxStart}
            onChange={(e) => e.target.value && setStart(e.target.value)} />
        </Field>
      )}
    </Card>
  )
}

/** Debounced preview of a plan for these answers (nothing is saved). */
export function usePreview(body: Parameters<typeof previewPlan>[0] | null) {
  const [state, setState] = useState<{ summary?: PlanSummary; diff?: PlanDiff; error?: string; busy: boolean }>({ busy: false })
  const key = body ? JSON.stringify(body) : ''
  const seq = useRef(0)
  useEffect(() => {
    if (!body) return
    const n = ++seq.current
    setState((s) => ({ ...s, busy: true, error: undefined }))
    const t = window.setTimeout(() => {
      previewPlan(body).then((r) => { if (n === seq.current) setState({ summary: r.summary, diff: r.diff, busy: false }) },
        (e) => { if (n === seq.current) setState((s) => ({ ...s, busy: false, error: (e as Error).message })) })
    }, 350)
    return () => window.clearTimeout(t)
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return state
}

function DiffView({ d }: { d: PlanDiff }) {
  const weeks = d.weeks.filter((w) => w.before !== w.after).slice(0, 6)
  if (!d.changed_days && !d.changed_weeks) {
    return <p className="px-1 text-small text-(--text-muted)">No change to your plan yet. Change a setting above to see what moves.</p>
  }
  return (
    <Card>
      <Field label="What changes" hint={`${d.changed_days} ${d.changed_days === 1 ? 'day' : 'days'} from today on${d.peak_hours.before !== d.peak_hours.after ? ` · peak week ${d.peak_hours.before}h → ${d.peak_hours.after}h` : ''}.`}>
        <ul className="flex flex-col gap-1.5">
          {d.days.map((x) => (
            <li key={x.date} className="flex flex-col text-small">
              <span className="font-semibold text-(--text)">{day(x.date)}</span>
              <span className="flex flex-wrap items-center gap-1 text-(--text-secondary)">
                <span className="line-through decoration-(--text-muted)">{x.before}</span>
                <ArrowRight className="size-3.5 text-(--text-muted)" aria-label="becomes" />
                <span className="text-(--text)">{x.after}</span>
              </span>
            </li>
          ))}
        </ul>
        {weeks.length > 0 && (
          <p className="mt-2 font-mono text-meta tabular-nums text-(--text-muted)">
            Weekly hours: {weeks.map((w) => `${fmtDay(w.start, { month: 'short', day: 'numeric' })} ${w.before ?? '–'}→${w.after ?? '–'}`).join(' · ')}
          </p>
        )}
      </Field>
    </Card>
  )
}

// ------------------------------------------------------- adjust sheet --
export function AdjustPlanSheet({ athlete, onClose, onApplied, onCheckIn }: {
  athlete: Partial<AthleteFull>
  onClose: () => void
  onApplied: (plan: BuiltPlan, undo: string) => void
  onCheckIn?: () => void
}) {
  const initial: Levers = {
    available_days: athlete.available_days?.length ? athlete.available_days : ['tue', 'wed', 'thu', 'sat', 'sun'],
    long_day: athlete.long_day ?? 'sat', weekly_hours: athlete.weekly_hours ?? null,
    plan_intensity: athlete.plan_intensity ?? 'normal',
  }
  const [v, setV] = useState<Levers>(initial)
  const set = (p: Partial<Levers>) => setV((x) => {
    const n = { ...x, ...p }
    if (n.long_day && !(n.available_days ?? []).includes(n.long_day)) n.long_day = (n.available_days ?? []).slice(-1)[0] ?? null
    return n
  })
  const changed = JSON.stringify(v) !== JSON.stringify(initial)
  const tooFew = (v.available_days ?? []).length < 2
  const prev = usePreview(changed && !tooFew ? { athlete: v } : null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function apply() {
    setBusy(true); setErr(null)
    try { const r = await applyLevers(v); announcePlanReload(); onApplied(r.plan, r.undo); onClose() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <Sheet title="Adjust my plan" onClose={onClose} portal className="modal--tall" bodyClassName={bodyCls} dismissible={!busy}
      footer={
        <div className="flex gap-2">
          <Button variant="default" className="h-11 px-5 text-body" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" className="h-11 flex-1 text-body" loading={busy} disabled={!changed || tooFew || prev.busy || !!prev.error}
            onClick={() => void apply()}>
            {tooFew ? 'Pick at least 2 days' : !changed ? 'Change something above' : 'Update my plan'}
          </Button>
        </div>
      }>
      <p className="px-1 text-small leading-snug text-(--text-secondary)">
        Change what fits your life. rabbt rebuilds from today, keeps the slow build, and shows what moves before anything changes. You can undo it.
      </p>
      <LeverFields v={v} set={set} />
      {changed && !tooFew && (prev.busy && !prev.diff ? (
        <RabbitLoader inline className="px-1 text-small" label="Working out what changes…" />
      ) : prev.error ? (
        <p className="px-1 text-small text-(--danger)" role="alert">{prev.error}</p>
      ) : prev.diff ? <DiffView d={prev.diff} /> : null)}
      {prev.summary && changed && <PlanSummaryView s={prev.summary} compact />}
      {onCheckIn && (
        <button type="button" onClick={() => { onClose(); onCheckIn() }}
          className="flex min-h-12 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
          <MessageCircleHeart className="size-5 shrink-0 text-(--accent)" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-body text-(--text)">Check in on my week</span>
            <span className="block text-meta text-(--text-muted)">Tired, sore, busy next week? rabbt suggests changes.</span>
          </span>
        </button>
      )}
      <button type="button" onClick={() => { onClose(); openTravel() }}
        className="flex min-h-12 items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-2.5 text-left active:bg-(--bg-inset)">
        <Plane className="size-5 shrink-0 text-(--accent)" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-body text-(--text)">Travelling or away?</span>
          <span className="block text-meta text-(--text-muted)">Travel mode swaps those days for a hotel gym, treadmill or runs.</span>
        </span>
      </button>
      {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

/** "Plan updated · Undo" after Adjust my plan. */
export function UndoBar({ id, onUndone, onDone }: { id: string; onUndone: (p: BuiltPlan) => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { const t = window.setTimeout(onDone, 15000); return () => window.clearTimeout(t) }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div role="status" className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2">
      <Check className="size-5 shrink-0 text-(--accent)" aria-hidden />
      <p className="min-w-0 flex-1 text-small text-(--accent)">{err ?? 'Plan updated from today.'}</p>
      <Button variant="default" className="h-9 gap-1 px-3 text-small" loading={busy}
        onClick={() => { setBusy(true); undoLevers(id).then((r) => { announcePlanReload(); onUndone(r.plan) }, (e) => setErr((e as Error).message)).finally(() => setBusy(false)) }}>
        <Undo2 className="size-4" aria-hidden /> Undo
      </Button>
    </div>
  )
}

// ------------------------------------------------------- race switcher --
export function RaceSwitcher({ title, date, sub, onSwitched, onAddRace, onBuild }: {
  title: string; date: string | null
  /** short facts under the race ("231 days to go", "Week 1 of 34"); a " · " string is split */
  sub?: string | string[]
  /** the plan for the newly picked race (null: it has no plan yet) */
  onSwitched: (plan: BuiltPlan | null) => void
  onAddRace: () => void
  /** build a plan for the active race (setup) */
  onBuild: () => void
}) {
  const [open, setOpen] = useState(false)
  const facts = (Array.isArray(sub) ? sub : (sub ?? '').split(' · ')).map((x) => x.trim()).filter(Boolean)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" aria-label={`${title}${date ? `, ${fmtDay(date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}` : ''}. ${facts.join(', ')}. Change race`}
        className="flex w-full flex-col rounded-xl border border-(--border) bg-(--bg-surface) text-left active:bg-(--bg-inset)">
        <span className="flex items-start gap-3.5 px-4 pb-3 pt-4">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><Flag className="size-5" aria-hidden /></span>
          <span className="min-w-0 flex-1">
            <span className="block text-lead font-semibold leading-snug text-(--text)">{title}</span>
            {date && <span className="mt-0.5 block text-small leading-snug text-(--text-secondary)">{fmtDay(date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}</span>}
            {facts.length > 0 && (
              <span className="mt-2 flex flex-wrap gap-2">
                {facts.map((f) => <span key={f} className="rounded-full bg-(--bg-inset) px-3 py-1 text-meta font-medium text-(--text-secondary)">{f}</span>)}
              </span>
            )}
          </span>
        </span>
        <span className="flex min-h-12 items-center justify-between gap-2 border-t border-(--border) px-4 text-body font-semibold text-(--accent)">
          Change race <ChevronDown className="size-5" aria-hidden />
        </span>
      </button>
      {open && <RaceSheet onClose={() => setOpen(false)} onSwitched={(p) => { setOpen(false); onSwitched(p) }}
        onAddRace={() => { setOpen(false); onAddRace() }} onBuild={() => { setOpen(false); onBuild() }} />}
    </>
  )
}

function RaceSheet({ onClose, onSwitched, onAddRace, onBuild }: {
  onClose: () => void; onSwitched: (plan: BuiltPlan | null) => void; onAddRace: () => void; onBuild: () => void
}) {
  const [races, setRaces] = useState<Race[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => { getRaces().then((r) => setRaces(r.races), (e) => setErr((e as Error).message)) }, [])
  async function train(r: Race) {
    setBusy(r.id); setErr(null)
    try { const out = await trainFor(r.id); announcePlanReload(); onSwitched(out.has_plan ? out.plan : null) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  async function tune(r: Race) {
    if (!r.event_id) return
    setBusy(`t${r.id}`); setErr(null)
    try { const out = await makeTuneUp(r.event_id); setRaces(out.races); setMsg(`${r.title} is now a tune-up race. Update your plan to fit it in.`); announcePlanReload() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const upcoming = (races ?? []).filter((r) => !r.past)
  const past = (races ?? []).filter((r) => r.past)
  return (
    <Sheet title="Your races" onClose={onClose} portal bodyClassName={bodyCls} dismissible={!busy}
      footer={<Button variant="default" className="h-11 w-full gap-1.5 text-body" onClick={onAddRace}><Plus className="size-5" aria-hidden /> Add a race</Button>}>
      <p className="px-1 text-small leading-snug text-(--text-secondary)">
        Your plan trains for one race at a time. Switch anytime: each race keeps its own plan, so switching back brings it back as it was.
      </p>
      {races === null && !err && <RabbitLoader className="py-6" label="Finding your races" />}
      {upcoming.map((r) => (
        <div key={r.id} className={cn('flex flex-col gap-2 rounded-xl border px-3.5 py-3', r.active ? 'border-(--accent) bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
          <div className="flex items-start gap-3">
            <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', r.active ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--bg-inset) text-(--text-muted)')}>
              {r.active ? <Trophy className="size-5" aria-hidden /> : <Flag className="size-5" aria-hidden />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-body-lg font-semibold text-(--text)">{r.title}</span>
              <span className="block text-meta text-(--text-muted)">
                {[r.date && fmtDay(r.date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }), r.distance,
                  r.active ? 'Your plan trains for this' : r.has_plan ? 'Has a saved plan' : r.priority && r.priority !== 'A' ? `${r.priority} race on your calendar` : 'No plan yet'].filter(Boolean).join(' · ')}
              </span>
            </span>
            {r.active && <Check className="size-5 shrink-0 text-(--accent)" aria-label="Active" />}
          </div>
          {r.active ? (!r.has_plan && (
            <Button variant="primary" className="h-11 text-body" onClick={onBuild}>Build a plan for this race</Button>
          )) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" className="h-11 flex-1 text-small" loading={busy === r.id} disabled={!!busy} onClick={() => void train(r)}>
                {r.has_plan ? 'Switch my plan to this' : 'Train for this race'}
              </Button>
              {r.kind === 'event' && r.priority !== 'B' && r.priority !== 'C' && (
                <Button variant="default" className="h-11 flex-1 text-small" loading={busy === `t${r.id}`} disabled={!!busy} onClick={() => void tune(r)}>
                  Tune-up in my plan
                </Button>
              )}
            </div>
          )}
        </div>
      ))}
      {past.length > 0 && (
        <details className="rounded-xl border border-(--border) bg-(--bg-surface)">
          <summary className="flex min-h-11 cursor-pointer list-none items-center px-3.5 text-small text-(--text-secondary) [&::-webkit-details-marker]:hidden">Past races ({past.length})</summary>
          <ul className="flex flex-col px-3.5 pb-2">
            {past.map((r) => <li key={r.id} className="py-1 text-small text-(--text-muted)">{r.title}{r.date ? ` · ${fmtDay(r.date, { month: 'short', day: 'numeric', year: 'numeric' })}` : ''}</li>)}
          </ul>
        </details>
      )}
      {msg && <p className="px-1 text-small text-(--accent)" role="status">{msg}</p>}
      {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

// ----------------------------------------------------- weekly check-in --
const ENERGY: [NonNullable<CheckinAnswers['energy']>, string][] = [['low', 'Low'], ['ok', 'OK'], ['great', 'Great']]
const SORE: [NonNullable<CheckinAnswers['soreness']>, string][] = [['none', 'Not sore'], ['some', 'A bit'], ['a_lot', 'Quite sore']]
const TIME: [NonNullable<CheckinAnswers['time']>, string][] = [['less', 'Less'], ['same', 'Same'], ['more', 'More']]

/** Friday to Monday (once per plan week) at the top of Schedule; `force` opens it on demand. */
export function WeekCheckCard({ force, onApplied, onClose }: { force?: boolean; onApplied: (plan: BuiltPlan) => void; onClose?: () => void }) {
  const [due, setDue] = useState(!!force)
  const [open, setOpen] = useState(!!force)
  const sick = useSick()  // no weekly check-in while sick or easing back
  useEffect(() => { if (!force) getWeekCheck().then((r) => setDue(r.due), () => {}) }, [force])
  if (!due || (!force && (sick?.active || sick?.returning))) return null
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="flex min-h-14 items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5 text-left active:opacity-80">
        <CalendarCheck className="size-6 shrink-0 text-(--accent)" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-body font-semibold text-(--accent)">How was this week?</span>
          <span className="block text-meta text-(--text-secondary)">Three taps, and rabbt fits next week to how you feel.</span>
        </span>
        <ArrowRight className="size-5 shrink-0 text-(--accent)" aria-hidden />
      </button>
    )
  }
  return <WeekCheckSheet onClose={() => { setOpen(false); if (force) onClose?.() }} onDone={(p) => { setDue(false); setOpen(false); if (p) onApplied(p); onClose?.() }} />
}

function WeekCheckSheet({ onClose, onDone }: { onClose: () => void; onDone: (plan: BuiltPlan | null) => void }) {
  const [a, setA] = useState<CheckinAnswers>({ off_days: [] })
  const [prop, setProp] = useState<CheckinProposal | null>(null)
  const [calHint, setCalHint] = useState<string | null>(null)  // calinsights: one calendar-aware line
  const [busy, setBusy] = useState<'preview' | 'apply' | 'skip' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const set = (p: Partial<CheckinAnswers>) => { setA((x) => ({ ...x, ...p })); setProp(null) }
  const answered = !!(a.energy || a.soreness || a.time || (a.off_days ?? []).length || a.long_day)
  async function go(action: 'preview' | 'apply' | 'skip') {
    setBusy(action); setErr(null)
    try {
      const r = await weekCheck(action, a, prop?.id)
      if (action === 'preview') { setProp(r.proposal); setCalHint(r.calendar_hint ?? null) }
      else { if (r.applied) announcePlanReload(); onDone(r.applied && r.plan ? r.plan : null) }
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const changes = prop?.changes ?? []
  const label = useMemo(() => !answered ? 'Answer one question to start' : prop ? (prop.status === 'suggest' ? `Apply ${changes.length} ${changes.length === 1 ? 'change' : 'changes'}` : 'Keep next week as planned') : 'See suggestions', [answered, prop, changes.length])
  return (
    <Sheet title="How was this week?" onClose={onClose} portal className="modal--tall" bodyClassName={bodyCls} dismissible={!busy}
      footer={
        <div className="flex gap-2">
          <Button variant="default" className="h-11 px-4 text-body" loading={busy === 'skip'} disabled={!!busy} onClick={() => void go('skip')}>Skip</Button>
          <Button variant="primary" className="h-11 flex-1 text-body" loading={busy === 'preview' || busy === 'apply'} disabled={!answered || !!busy}
            onClick={() => void go(!prop ? 'preview' : prop.status === 'suggest' ? 'apply' : 'skip')}>{label}</Button>
        </div>
      }>
      <Card>
        <Field label="Energy"><Pick v={a.energy} opts={ENERGY} on={(x) => set({ energy: x })} /></Field>
        <Field label="Soreness" className="border-t border-(--border)"><Pick v={a.soreness} opts={SORE} on={(x) => set({ soreness: x })} /></Field>
        <Field label="Time next week" className="border-t border-(--border)"><Pick v={a.time} opts={TIME} on={(x) => set({ time: x })} /></Field>
        <Field label="Days you can't train next week" className="border-t border-(--border)">
          <ChipRow>
            {WEEKDAYS.map(([d, l]) => {
              const on = (a.off_days ?? []).includes(d)
              return <Chip key={d} selected={on} onClick={() => set({ off_days: on ? (a.off_days ?? []).filter((x) => x !== d) : [...(a.off_days ?? []), d] })}>{l}</Chip>
            })}
          </ChipRow>
        </Field>
        <Field label="Long session on (optional)" className="border-t border-(--border)">
          <ChipRow>
            {WEEKDAYS.map(([d, l]) => <Chip key={d} selected={a.long_day === d} onClick={() => set({ long_day: a.long_day === d ? undefined : d })}>{l}</Chip>)}
          </ChipRow>
        </Field>
      </Card>
      {prop && (
        <Card>
          <Field label={prop.status === 'suggest' ? "rabbt suggests for next week" : 'Next week'}>
            {(prop.reasons ?? []).map((r) => <p key={r} className="text-small leading-snug text-(--text-secondary)">{r}</p>)}
            {calHint && <p className="text-small leading-snug text-(--text-secondary)"><span className="font-semibold text-(--text)">From your calendar:</span> {calHint}</p>}
            {changes.length > 0 && (
              <ul className="mt-1 flex flex-col gap-2">
                {changes.map((c) => (
                  <li key={c.session_id + c.action} className="flex flex-col rounded-lg bg-(--bg-inset) px-3 py-2 text-small">
                    <span className="font-semibold text-(--text)">
                      {c.from.title}
                      {c.action === 'relocate' ? ` → ${fmtDay(c.date, { weekday: 'long' })}` : c.action === 'rest' ? ' → dropped' : ''}
                      {c.to.minutes && c.from.minutes && c.to.minutes !== c.from.minutes ? ` · ${fmtDuration(c.from.minutes)} → ${fmtDuration(c.to.minutes)}` : ''}
                      {c.action === 'ease' ? ' · easy' : ''}
                    </span>
                    <span className="text-(--text-muted)">{c.why}</span>
                  </li>
                ))}
              </ul>
            )}
          </Field>
        </Card>
      )}
      {err && <p className="px-1 text-small text-(--danger)" role="alert">{err}</p>}
    </Sheet>
  )
}

function Pick<T extends string>({ v, opts, on }: { v: T | undefined; opts: [T, string][]; on: (v: T) => void }) {
  return <ChipRow>{opts.map(([k, l]) => <Chip key={k} selected={v === k} onClick={() => on(k)}>{l}</Chip>)}</ChipRow>
}

export { SlidersHorizontal as AdjustIcon }
