// Plan calendar Day view: one day at a time, every session in full. Swipe or use the arrows to
// change day; the strip jumps within the week. Each session card shows the numbers in the
// athlete's units, done/missed with what you actually did, the step-by-step, the coach or
// Rabbit note, "Learn more" (what the session is, why it's in the plan, how it should feel,
// the zones it uses), and actions: Ready to go, Move, Swap, Edit, Ask Rabbit.
import { useEffect, useRef, useState } from 'react'
import { ArrowLeftRight, BookOpen, CalendarDays, CalendarPlus, Check, ChevronDown, ChevronLeft, ChevronRight, Clock, Flag, Maximize2, MessageCircle, MoveRight, Pencil, Plane, Play, Plus, Sparkles, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitNote } from '@/components/ui/brand'
import { RabbitNap } from '@/components/anim'
import { openEvent } from '@/lib/events'
import { cn } from '@/lib/utils'
import { openActivity } from '@/lib/activitynav'
import { fmtDist, fmtDuration } from '@/lib/format'
import { KIND_GLOSSARY, ZONE_GLOSSARY } from '@/lib/glossary'
import { KIND_LABEL, fmtMin, type BuiltPlan, type PlanSession, type Step } from '@/lib/plan'
import { fmtTime, googleCalendarUrl, sessionIcsUrl, type CalSession, type CalView, type DistSport } from '@/lib/plancal'
import { HowItWent, PaceNudge, WorkoutSteps, WorkoutSummary } from './WorkoutTargets'
import { Card } from './ui'
import { WxChip } from './WxChip'
import { SPORT_ICON, SPORT_LABEL, fmtDay, sessionMinutes, weekPhaseLabel } from './PlanParts'
import { StepItem } from './SessionSheet'
import { addDays, mondayOf } from './MoveSheet'
import { paceText } from './PlanCalendar'

export type DayActions = {
  onEdit: (s: PlanSession) => void
  /** the full workout page */
  onOpenPage?: (s: PlanSession) => void
  onMove?: (s: PlanSession, mode: 'move' | 'swap') => void
  onFix?: (s: PlanSession) => void
  onStart?: (s: PlanSession) => void
  onAsk?: (s: PlanSession) => void
}

function zonesOf(steps: Step[], out = new Set<number>()): Set<number> {
  for (const s of steps) {
    if (s.type === 'repeat') zonesOf(s.steps, out)
    else if (s.zone) out.add(s.zone)
  }
  return out
}

function Learn({ s, c, cal, imperial }: { s: PlanSession; c: CalSession | undefined; cal: CalView | null; imperial: boolean }) {
  const [open, setOpen] = useState(false)
  const k = KIND_GLOSSARY[s.kind] ?? (s.sport === 'brick' ? KIND_GLOSSARY.brick : undefined)
  const zones = [...zonesOf([...s.steps, ...s.legs.flatMap((l) => l.steps)])].sort()
  if (!k && !zones.length) return null
  const src = cal?.pace_source === 'profile' ? 'the threshold pace in your profile' : cal?.pace_source === 'recent' ? 'your recent runs' : 'a typical starting point (add your threshold pace in Profile to sharpen it)'
  return (
    <div className="border-t border-(--border)">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center gap-2 px-3.5 text-left text-[0.7647rem] font-medium text-(--accent)">
        <BookOpen className="size-3.5" aria-hidden /> <span className="flex-1">Learn more about this workout</span>
        <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="flex flex-col gap-2.5 px-3.5 pb-3.5 text-[0.7647rem] leading-snug">
          {k && (
            <dl className="flex flex-col gap-1.5">
              <div><dt className="font-semibold text-(--text)">What it is</dt><dd className="text-(--text-secondary)">{k.what}</dd></div>
              <div><dt className="font-semibold text-(--text)">Why it's in your plan</dt><dd className="text-(--text-secondary)">{k.why}</dd></div>
              <div><dt className="font-semibold text-(--text)">How it should feel</dt><dd className="text-(--text-secondary)">{k.feel}</dd></div>
            </dl>
          )}
          {zones.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="font-semibold text-(--text)">Zones in this workout</p>
              <ul className="flex flex-col gap-1">
                {zones.map((z) => ZONE_GLOSSARY[z] && (
                  <li key={z} className="text-(--text-secondary)"><span className="font-medium text-(--text)">{ZONE_GLOSSARY[z]!.title}:</span> {ZONE_GLOSSARY[z]!.text}</li>
                ))}
              </ul>
            </div>
          )}
          {c?.pace && (
            <p className="text-(--text-muted)">
              Target pace {paceText(c.pace.fast, imperial)}–{paceText(c.pace.slow, imperial)}/{imperial ? 'mi' : 'km'} for the main set comes from {src}. Effort beats pace on hills, heat and tired days.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** Put this workout in the phone's calendar: .ics (Apple, Outlook, any app) or Google's add page.
 *  Same event id every time, so adding it again after a move or a new time updates it. */
function AddToCalendar({ s, date }: { s: PlanSession; date: string }) {
  const [open, setOpen] = useState(false)
  const link = 'flex min-h-11 flex-1 items-center justify-center rounded-lg border border-(--border) px-3 text-[0.7647rem] font-medium text-(--text) active:bg-(--bg-inset)'
  return (
    <div className="border-t border-(--border) px-3.5 py-1">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center gap-2 text-left text-[0.7647rem] font-medium text-(--text-secondary)">
        <CalendarPlus className="size-3.5" aria-hidden />
        <span className="flex-1">{s.time ? `Add to calendar at ${fmtTime(s.time)}` : 'Add to calendar'}</span>
        <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="flex flex-col gap-2 pb-2.5">
          <div className="flex gap-2">
            <a className={link} href={sessionIcsUrl(s.id)} download="rabbit-workout.ics">Apple / Outlook</a>
            <a className={link} href={googleCalendarUrl(s, date)} target="_blank" rel="noopener noreferrer">Google Calendar</a>
          </div>
          {!s.time && <p className="text-[0.7059rem] text-(--text-muted)">Tip: set a start time (Edit) to block the time instead of the whole day.</p>}
        </div>
      )}
    </div>
  )
}

function DaySession({ s, c, date, today, imperial, cal, unread, a }: {
  s: PlanSession; c: CalSession | undefined; date: string; today: string; imperial: boolean; cal: CalView | null; unread: boolean; a: DayActions
}) {
  const Icon = s.kind === 'race' ? Flag : SPORT_ICON[s.sport]
  const mins = sessionMinutes(s)
  const dist = c ? (Object.entries(c.km) as [DistSport, number][]).filter(([, v]) => v > 0).map(([sp, v]) => fmtDist(v, imperial, sp)).join(' + ')
    : s.meters ? fmtDist(s.meters / 1000, imperial, 'swim') : ''
  const pace = c?.pace ? `${paceText(c.pace.fast, imperial)}–${paceText(c.pace.slow, imperial)}/${imperial ? 'mi' : 'km'}` : ''
  const groups: { label?: string; steps: Step[] }[] = s.legs.length
    ? s.legs.map((l) => ({ label: `${SPORT_LABEL[l.sport]} · ${fmtMin(l.minutes)}`, steps: l.steps }))
    : s.steps.length ? [{ steps: s.steps }] : []
  const status = c?.status ?? 'planned'
  const act = c?.activity
  const canStart = !!a.onStart && date >= today && status !== 'done' && status !== 'skipped' && s.sport !== 'rest'
  return (
    <Card className={cn(status === 'missed' && 'border-(--danger)/40', status === 'skipped' && 'opacity-70')}>
      <div className="flex items-start gap-3 px-3.5 pt-3.5">
        <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl',
          s.kind === 'race' ? 'bg-(--brand) text-(--on-fill)' : status === 'done' ? 'bg-(--accent) text-(--on-fill)' : 'bg-(--accent-subtle) text-(--accent)')}>
          <Icon className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className={cn('text-[0.9412rem] font-semibold leading-tight text-(--text)', status === 'skipped' && 'line-through')}>
            {a.onOpenPage ? (
              <button type="button" onClick={() => a.onOpenPage!(s)} className="hit-44 text-left underline-offset-2 hover:underline">{s.title}</button>
            ) : s.title}
          </h3>
          <p className="mt-0.5 text-[0.7059rem] text-(--text-muted)">
            {s.time && <span className="mr-1 inline-flex items-center gap-0.5 font-semibold text-(--text)"><Clock className="size-3" aria-hidden />{fmtTime(s.time)} ·</span>}
            {SPORT_LABEL[s.sport]}{s.kind !== s.sport && KIND_LABEL[s.kind] ? ` · ${KIND_LABEL[s.kind]}` : ''}
            {s.synced ? ' · on your Garmin' : ''}{s.travel ? ' · travel version' : ''}
            {unread && <span className="ml-1 font-semibold text-(--accent)">· new coach message</span>}
          </p>
        </div>
        {status === 'planned' && date >= today && <WxChip id={s.id} date={date} />}
        {status === 'done' && <span className="flex shrink-0 items-center gap-0.5 rounded-full bg-(--accent-subtle) px-2 py-0.5 text-[0.6471rem] font-semibold text-(--accent)"><Check className="size-3" aria-hidden />Done</span>}
        {status === 'missed' && <span className="shrink-0 rounded-full bg-(--danger)/10 px-2 py-0.5 text-[0.6471rem] font-semibold text-(--danger)">Missed</span>}
        {status === 'skipped' && <span className="shrink-0 rounded-full bg-(--bg-elevated) px-2 py-0.5 text-[0.6471rem] font-semibold text-(--text-muted)">Skipped</span>}
      </div>

      {c?.targets ? <WorkoutSummary t={c.targets} dist={dist} imperial={imperial} /> : (mins || dist || pace) && (
        <dl className="mx-3.5 mt-3 flex gap-6 rounded-lg bg-(--bg-inset) px-3 py-2">
          {([['Time', mins ? fmtDuration(mins) : ''], ['Distance', dist], ['Pace', pace]] as const).filter(([, v]) => !!v).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="font-mono text-[0.6471rem] uppercase tracking-widest text-(--text-muted)">{k}</dt>
              <dd className="truncate font-mono text-[0.7647rem] font-semibold tabular-nums text-(--text)">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {s.event_id && (
        <button type="button" onClick={() => openEvent(s.event_id!)}
          className="mx-3.5 mt-2 flex min-h-11 items-center gap-1.5 text-left text-[0.7647rem] text-(--text-secondary)">
          <CalendarDays className="size-3.5 shrink-0 text-(--accent)" aria-hidden />
          <span>From your events: <span className="font-medium text-(--accent) underline-offset-2 hover:underline">open the event</span></span>
        </button>
      )}
      {c?.adjusted && (
        <p className="mx-3.5 mt-2 flex items-start gap-1.5 text-[0.7647rem] leading-snug text-(--accent)">
          <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden /><span><span className="font-semibold">Rabbit adjusted this:</span> {c.adjusted}</span>
        </p>
      )}
      {status === 'done' && c?.went && <HowItWent w={c.went} imperial={imperial} sport={s.sport === 'brick' ? 'run' : s.sport} />}
      {status === 'done' && !c?.went && act && (act.km != null || act.minutes != null) && (
        <p className="mx-3.5 mt-2 text-[0.7647rem] text-(--accent)">
          You did {[act.km != null ? fmtDist(act.km, imperial, s.sport === 'swim' ? 'swim' : s.sport) : '', act.minutes != null ? `in ${fmtDuration(act.minutes)}` : ''].filter(Boolean).join(' ')}.
        </p>
      )}
      {status === 'missed' && c?.missed && <p className="mx-3.5 mt-2 text-[0.7647rem] leading-snug text-(--text-secondary)">{c.missed.why}</p>}

      {c?.note && (c.note.source === 'coach' ? (
        <div className="mx-3.5 mt-3 flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg) px-3.5 py-3 text-[0.7647rem] leading-snug">
          <p className="section-label m-0">Coach notes</p>
          <p className="text-(--text)">{c.note.why}</p>
          {c.note.how && <p className="text-(--text-secondary)">{c.note.how}</p>}
          {c.note.cues && <p className="text-(--text-muted)">{c.note.cues}</p>}
        </div>
      ) : (
        <RabbitNote title="Why + how" className="mx-3.5 mt-3">
          <p className="m-0 text-(--text)">{c.note.why}</p>
          {c.note.how && <p className="m-0 text-(--text-secondary)">{c.note.how}</p>}
          {c.note.cues && <p className="m-0 text-(--text-muted)">{c.note.cues}</p>}
        </RabbitNote>
      ))}

      {c?.targets ? <WorkoutSteps t={c.targets} imperial={imperial} /> : groups.length > 0 && (
        <div className="mx-3.5 mt-3 flex flex-col gap-2">
          <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">The workout</p>
          {groups.map((g, i) => (
            <div key={i} className="flex flex-col gap-1">
              {g.label && <span className="text-[0.7059rem] font-medium text-(--text-secondary)">{g.label}</span>}
              <ol className="flex flex-col gap-1">{g.steps.map((x, j) => <StepItem key={j} s={x} />)}</ol>
            </div>
          ))}
        </div>
      )}
      {!groups.length && s.detail && <p className="mx-3.5 mt-3 whitespace-pre-line text-[0.7647rem] leading-snug text-(--text-secondary)">{s.detail}</p>}
      {(s.exercises?.length ?? 0) > 0 && (
        <ul className="mx-3.5 mt-3 flex flex-col gap-1">
          {s.exercises!.map((e) => <li key={e.name} className="flex gap-2 text-[0.7647rem]"><span className="flex-1 text-(--text)">{e.name}</span><span className="text-(--text-muted)">{e.dose}</span></li>)}
        </ul>
      )}
      {s.fuel && (
        <p className="mx-3.5 mt-3 text-[0.7647rem] leading-snug text-(--text-secondary)">
          <span className="font-semibold text-(--text)">Fuel:</span> about {s.fuel.carbs_g_per_h} g carbs an hour{s.fuel.note ? `. ${s.fuel.note}` : ''}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2 px-3.5 pb-3">
        {canStart && <Button variant="primary" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => a.onStart!(s)}><Play className="size-4" aria-hidden />{date === today ? 'Ready to go' : 'Preview'}</Button>}
        {a.onFix && <Button variant="primary" className="h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={() => a.onFix!(s)}><Wrench className="size-4" aria-hidden />Fix my week</Button>}
        {a.onMove && <Button variant="default" className="h-11 gap-1.5 px-3 text-[0.8235rem]" onClick={() => a.onMove!(s, 'move')} aria-label={`Move ${s.title} to another day`}><MoveRight className="size-4" aria-hidden />Move</Button>}
        {a.onMove && <Button variant="default" className="h-11 gap-1.5 px-3 text-[0.8235rem]" onClick={() => a.onMove!(s, 'swap')} aria-label={`Swap ${fmtDay(date, { weekday: 'long' })} with another day`}><ArrowLeftRight className="size-4" aria-hidden />Swap</Button>}
        {a.onOpenPage && <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.8235rem]" onClick={() => a.onOpenPage!(s)} aria-label={`Open ${s.title} in full`}><Maximize2 className="size-4" aria-hidden />Full workout</Button>}
        <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.8235rem]" onClick={() => a.onEdit(s)} aria-label={`Edit ${s.title}`}><Pencil className="size-4" aria-hidden />Edit</Button>
        {a.onAsk && <Button variant="ghost" className="h-11 gap-1.5 px-3 text-[0.8235rem]" onClick={() => a.onAsk!(s)} aria-label={`Ask Rabbit about ${s.title}`}><MessageCircle className="size-4" aria-hidden />Ask Rabbit</Button>}
      </div>
      {date >= today && s.kind !== 'race' && <AddToCalendar s={s} date={date} />}
      <Learn s={s} c={c} cal={cal} imperial={imperial} />
    </Card>
  )
}

/** Where a workout outside the plan came from (workouts.py sources). */
const SOURCE_NAME: Record<string, string> = { oura: 'Oura', whoop: 'Whoop', coros: 'Coros', apple: 'Apple Watch', manual: 'added by you' }

export function PlanDay({ plan, cal, imperial, today, date, onDate, unread, hidden, extra, actions, onAdd }: {
  plan: BuiltPlan; cal: CalView | null; imperial: boolean; today: string
  date: string; onDate: (d: string) => void
  unread: string[]
  hidden?: (id: string) => boolean
  extra?: React.ReactNode
  /** per session: which actions apply (the calendar decides what's movable / fixable) */
  actions: (s: PlanSession) => DayActions
  /** add a session on this day */
  onAdd?: () => void
}) {
  const first = plan.weeks[0]!.days[0]!.date
  const lastWeek = plan.weeks[plan.weeks.length - 1]!
  const last = lastWeek.days[lastWeek.days.length - 1]!.date
  const week = plan.weeks.find((w) => w.days.some((d) => d.date === date))
  const day = week?.days.find((d) => d.date === date)
  const work = (day?.sessions ?? []).filter((s) => s.sport !== 'rest' && !hidden?.(s.id))
  const did = cal?.extra?.[date] ?? []
  const mon = mondayOf(date)
  const strip = Array.from({ length: 7 }, (_, i) => addDays(mon, i))
  const sessionsOn = (d: string) => (plan.weeks.flatMap((w) => w.days).find((x) => x.date === d)?.sessions ?? []).filter((s) => s.sport !== 'rest')
  const go = (n: number) => { const d = addDays(date, n); if (d >= first && d <= last) onDate(d) }
  const swipe = useRef<{ x: number; y: number } | null>(null)
  const tomorrow = addDays(today, 1)
  const trip = plan.trips.find((t) => t.start <= date && date <= t.end)
  const head = date === today ? 'Today' : date === tomorrow ? 'Tomorrow' : date === addDays(today, -1) ? 'Yesterday' : fmtDay(date, { weekday: 'long' })
  const restAdd = onAdd
  // Slide the new day in from the side you're heading to (CSS respects reduced motion).
  const prev = useRef(date)
  const dir = date > prev.current ? 'next' : date < prev.current ? 'prev' : null
  useEffect(() => { prev.current = date }, [date])
  const sports = [...new Set(work.flatMap((x) => x.sport === 'brick' ? ['bike', 'run'] : [x.sport]))]

  return (
    <div className="flex flex-col gap-2" data-no-tab-swipe
      onPointerDown={(e) => { if (e.pointerType !== 'mouse') swipe.current = { x: e.clientX, y: e.clientY } }}
      onPointerUp={(e) => {
        const s = swipe.current; swipe.current = null
        if (!s) return
        const dx = e.clientX - s.x, dy = e.clientY - s.y
        if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) go(dx < 0 ? 1 : -1)
      }}
      onPointerCancel={() => { swipe.current = null }}>
      <div className="flex items-center gap-1 px-1">
        <button type="button" className="modal-close" aria-label="Previous day" disabled={date <= first} onClick={() => go(-1)}><ChevronLeft className="size-4" /></button>
        <div className="min-w-0 flex-1 text-center" aria-live="polite">
          <h2 className="text-[0.9412rem] font-semibold leading-tight text-(--text)">{head}</h2>
          <p className="text-[0.7059rem] text-(--text-muted)">
            {fmtDay(date, { month: 'long', day: 'numeric' })}{week ? ` · week ${week.index} · ${weekPhaseLabel(week)}` : ''}
            {date !== today && today >= first && today <= last && <> · <button type="button" className="hit-44 text-(--accent) underline-offset-2 hover:underline" onClick={() => onDate(today)}>Jump to today</button></>}
          </p>
        </div>
        <button type="button" className="modal-close" aria-label="Next day" disabled={date >= last} onClick={() => go(1)}><ChevronRight className="size-4" /></button>
      </div>

      <div className="grid grid-cols-7 gap-1 px-1" role="group" aria-label="Days this week">
        {strip.map((d) => {
          const ss = sessionsOn(d)
          const on = d === date
          const out = d < first || d > last
          return (
            <button key={d} type="button" disabled={out} aria-pressed={on} onClick={() => onDate(d)}
              aria-label={`${fmtDay(d, { weekday: 'long', month: 'short', day: 'numeric' })}: ${ss.length ? ss.map((s) => `${s.title}, ${cal?.sessions[s.id]?.status ?? 'planned'}`).join('; ') : 'rest'}`}
              className={cn('flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-lg border text-center disabled:opacity-30',
                on ? 'border-(--accent) bg-(--accent-subtle)' : 'border-transparent', d === today && !on && 'border-(--border-strong)')}>
              <span className={cn('text-[0.6471rem] font-semibold uppercase', on || d === today ? 'text-(--accent)' : 'text-(--text-muted)')}>{fmtDay(d, { weekday: 'narrow' })}</span>
              <span className="text-[0.7647rem] tabular-nums text-(--text)">{Number(d.slice(8))}</span>
              <span className="flex h-1.5 gap-0.5" aria-hidden>
                {ss.slice(0, 3).map((s) => {
                  const st = cal?.sessions[s.id]?.status
                  return <span key={s.id} className={cn('size-1.5 rounded-full', s.kind === 'race' ? 'bg-(--brand)' : st === 'done' ? 'bg-(--accent)' : st === 'missed' ? 'bg-(--danger)' : 'bg-(--text-muted)')} />
                })}
              </span>
            </button>
          )
        })}
      </div>

      {trip && <p className="flex items-center gap-1.5 px-2 text-[0.7647rem] text-(--accent)"><Plane className="size-3.5" aria-hidden />Travel mode: {trip.label}</p>}
      {date >= today && date <= addDays(today, 7) && sports.length > 0 && <PaceNudge sports={sports} />}

      <div key={date} className={cn('flex flex-col gap-2', dir && `day-slide day-slide--${dir}`)}>
      {work.map((s) => (
        <DaySession key={s.id} s={s} c={cal?.sessions[s.id]} date={date} today={today} imperial={imperial} cal={cal}
          unread={unread.includes(s.id)} a={actions(s)} />
      ))}
      {extra}
      {did.length > 0 && (
        <section aria-label="Workouts you did" className="flex flex-col gap-1 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3">
          <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{did.some((a) => a.source && a.source !== 'garmin') ? (work.length ? 'Also from your apps' : 'From your apps') : work.length ? 'Also from Garmin' : 'From Garmin'}</p>
          <ul className="flex flex-col">
            {did.map((a, i) => {
              const I = SPORT_ICON[(a.sport in SPORT_ICON ? a.sport : 'other') as keyof typeof SPORT_ICON] ?? Check
              return (
                <li key={a.id ?? a.key ?? i}>
                <button type="button" disabled={a.id == null && !a.key} onClick={() => openActivity(a.id ?? a.key!)}
                  aria-label={`${a.name}, done. Open the workout`}
                  className="flex min-h-11 w-full items-center gap-3 rounded-lg text-left active:bg-(--bg-inset) disabled:cursor-default">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><I className="size-4" aria-hidden /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{a.name}</span>
                    <span className="block text-[0.7059rem] text-(--text-muted)">
                      {[a.km ? fmtDist(a.km, imperial, a.sport === 'swim' ? 'swim' : a.sport === 'bike' ? 'bike' : 'run') : '', a.minutes ? fmtDuration(a.minutes) : '', a.avg_hr ? `avg ${Math.round(a.avg_hr)} bpm` : '', a.source && a.source !== 'garmin' ? `via ${SOURCE_NAME[a.source] ?? a.source}` : ''].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {a.id != null || a.key ? <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden /> : <Check className="size-4 shrink-0 text-(--accent)" aria-label="Done" />}
                </button>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {!work.length && !extra && !did.length && (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-(--border) bg-(--bg-surface) px-6 py-8 text-center">
          {!did.length && <RabbitNap size={44} mode="sleep" />}
          <p className="text-[0.9412rem] font-semibold text-(--text)">{!day ? 'Outside your plan' : did.length ? 'Nothing planned' : 'Rest day'}</p>
          {day && <p className="max-w-xs text-[0.7647rem] leading-snug text-(--text-secondary)">{did.length ? 'Nothing was on the plan today, and you got a workout in anyway.' : 'Fitness sinks in while you recover. A walk or some light stretching is plenty.'}</p>}
          {day && restAdd && date >= today && (
            <Button variant="default" className="mt-1 h-11 gap-1.5 px-4 text-[0.8235rem]" onClick={restAdd}><Plus className="size-4" aria-hidden />Add a workout</Button>
          )}
        </div>
      )}
      {(work.length > 0 || did.length > 0) && restAdd && date >= today && work.length < 4 && (
        <button type="button" onClick={restAdd}
          className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-dashed border-(--border-strong) text-[0.7647rem] text-(--text-muted) active:bg-(--bg-inset)">
          <Plus className="size-3.5" aria-hidden />Add a workout on {fmtDay(date, { weekday: 'long' })}
        </button>
      )}
      </div>
      <p className="px-4 text-[0.7059rem] text-(--text-muted)">Swipe left or right to change day.</p>
    </div>
  )
}
