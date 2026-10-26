// Guided setup: race (or no race: a training block) -> goal -> you -> your numbers -> your week
// -> review, then rabbt builds a periodized plan and (optionally) puts the next sessions on your
// Garmin. Answers are kept as a local draft so leaving halfway loses nothing.
import { useEffect, useMemo, useRef, useState } from 'react'
import { TARGET_PRESETS, TimeFields } from '@/components/ui/TimeFields'
import { CalendarDays, HeartPulse, Route, Target, Upload, User, Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { celebrate } from '@/components/fx/motion'
import { RabbitLogo } from '@/components/RabbitLogo'
import { RabbitLoader } from '@/components/RabbitLoader'
import { GarminEmpty } from '@/components/garmin/GarminEmpty'
import { ATTACH_INPUT_ID } from '@/components/chat/Composer'
import type { Me } from '@/lib/api'
import {
  DISTANCES, cmToFtIn, fmtPace, getGarminNumbers, guessUnits, kgToLb, KM_PER_MI,
  setupPlan, sportsFor, syncGarmin, weeksUntil,
  type AthleteFull, type BuiltPlan, type GoalFull, type SyncResult,
} from '@/lib/plan'
import { Card, Chip, ChipRow, Field, MultiChoice, OptionCard, Progress, Screen, StepIntro, areaCls } from './ui'
import { SetupReview } from './SetupReview'
import { PhaseStrip, SPORT_ICON, WeekPreview } from './PlanParts'
import { GarminFill, NumbersFields, WeekFields, YouFields } from './ProfileFields'
import { RhythmGrid, StrengthOptInSheet } from './WeekRhythm'
import { clean as cleanRhythm, summary as rhythmSummary, syncDays, toggle as toggleRhythm, type Day, type WeekRhythm } from '@/lib/rhythm'
import { LeverFields, usePreview } from './PlanFlow'
import { EventBasics } from '@/components/events/EventForm'
import { TYPE_DISTANCES, listEvents, type EventFields, type EventType } from '@/lib/events'
import { track } from '@/lib/usage'
import { clearDraft, readDraft, writeDraft } from '@/lib/drafts'
import { hoursLine } from '@/lib/planflow'
import { RabbitNap } from '@/components/anim'

const STEPS = ['intro', 'race', 'goal', 'you', 'numbers', 'week', 'rhythm', 'review', 'done'] as const
type StepName = typeof STEPS[number]
const STEP_NAME: Partial<Record<StepName, string>> = {
  race: 'Your goal', goal: 'A great day', you: 'About you', numbers: 'Your numbers', week: 'Your week', review: 'Your plan',
}

// No race: what the block trains for, and the distance it builds toward (sets the sports).
type Focus = 'run' | 'bike' | 'tri' | 'fitness'
const FOCUS: { id: Focus; title: string; description: string; distance: string; options?: string[] }[] = [
  { id: 'run', title: 'Running', description: 'Run more, run faster, or build to a distance.', distance: '10k', options: ['5k', '10k', 'half marathon', 'marathon'] },
  { id: 'bike', title: 'Cycling', description: 'Longer, stronger rides.', distance: 'century ride' },
  { id: 'tri', title: 'Triathlon', description: 'Swim, bike and run together.', distance: 'olympic triathlon', options: ['sprint triathlon', 'olympic triathlon', '70.3'] },
  { id: 'fitness', title: 'All-round fitness', description: 'A mix of running, riding and strength to get fitter.', distance: 'other' },
]
const BLOCK_WEEKS = [6, 8, 12, 16] as const
const focusOf = (distance: string | undefined): Focus => {
  const s = sportsFor(distance)
  return distance === 'other' || !distance ? 'fitness' : s.includes('swim') ? 'tri' : s.length === 1 && s[0] === 'bike' ? 'bike' : 'run'
}
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// lib/drafts key (per user, 14 days, like every other form). The wizard keeps its own merge
// rules (server values win for anything the server already has), so it uses the raw helpers.
const DRAFT_KEY = 'setup'
const LEGACY_KEY = 'rabbit.setup.v1' // pre-lib/drafts drafts (not per user): read once, then dropped

type Draft = {
  goalId: string | null       // the goal this draft was started for
  newGoal: boolean
  event: EventFields
  goal: Partial<GoalFull>
  athlete: Partial<AthleteFull>
  start_date: string
  /** no race: how many weeks the block runs */
  blockWeeks?: number
}

const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const TIME_RE = /^(\d{1,2}):([0-5]\d)(:([0-5]\d))?$/

const hasValue = (v: unknown) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0)
/** The draft's answers for fields the server doesn't have. The server copy may be newer
 *  than the draft (edited elsewhere since), so whatever it has wins. */
function missingOnly<T extends object>(saved: Partial<T> | undefined, server: Partial<T> | null | undefined): Partial<T> {
  const out: Partial<T> = {}
  if (!saved) return out
  for (const k of Object.keys(saved) as (keyof T)[]) {
    const v = saved[k]
    if (v !== undefined && !hasValue(server?.[k])) out[k] = v
  }
  return out
}

function initialDraft(me: Me): Draft {
  const a = (me.athlete ?? {}) as AthleteFull
  const g = (me.goal ?? null) as GoalFull | null
  const fresh: Draft = {
    goalId: g?.id ?? null,
    newGoal: !g,
    event: { type: typeForDistance(g?.distance) },
    goal: g ? {
      title: g.title, event: g.event, distance: g.distance || undefined, date: g.date, priority: g.priority ?? 'A',
      course: g.course ?? '', goal_type: g.goal_type ?? (g.target ? 'time' : 'finish'), target_time: g.target_time ?? '',
      priorities: g.priorities ?? '', limiters: g.limiters ?? [], no_race: g.no_race ?? false,
    } : { priority: 'A', goal_type: 'finish', limiters: [] },
    athlete: {
      units: a.units ?? guessUnits(), sex: a.sex ?? null, age: a.age ?? null, height_cm: a.height_cm ?? null,
      weight_kg: a.weight_kg ?? null, level: a.level ?? null, injuries: a.injuries ?? '', experience: a.experience ?? '',
      resting_hr: a.resting_hr ?? null, max_hr: a.max_hr ?? null, threshold_hr: a.threshold_hr ?? null,
      ftp_w: a.ftp_w ?? null, run_threshold_pace: a.run_threshold_pace ?? null, swim_css: a.swim_css ?? null,
      weekly_hours: a.weekly_hours ?? null,
      longest_run_min: a.longest_run_min ?? null, longest_ride_min: a.longest_ride_min ?? null,
      available_days: a.available_days?.length ? a.available_days : ['tue', 'wed', 'thu', 'sat', 'sun'],
      long_day: a.long_day ?? 'sat', equipment: a.equipment ?? [],
    },
    start_date: todayIso(),
    blockWeeks: g?.no_race && g.date ? Math.max(4, Math.round(((new Date(`${g.date}T12:00:00`).getTime() - Date.now()) / 86_400_000 + 1) / 7)) : 12,
  }
  try {
    let saved = readDraft<Draft>(DRAFT_KEY)
    const legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) ?? 'null') as (Draft & { at: number }) | null
    if (legacy) {
      localStorage.removeItem(LEGACY_KEY)
      if (!saved && Date.now() - legacy.at < 14 * 86_400_000) saved = legacy
    }
    if (saved) {
      const athlete = { ...fresh.athlete, ...missingOnly<AthleteFull>(saved.athlete, a) }
      // Race answers only come back for the same goal, and never a half-made "new race"
      // (it would otherwise be applied to the current goal). The saved event's details
      // give way to the server's below, once the events list loads.
      if (saved.goalId === fresh.goalId && !saved.newGoal) {
        return { ...fresh, event: { ...fresh.event, ...(saved.event ?? {}) },
          goal: { ...fresh.goal, ...missingOnly<GoalFull>(saved.goal, g) }, athlete }
      }
      return { ...fresh, athlete }
    }
  } catch { /* storage unavailable: start fresh */ }
  return fresh
}

export function SetupWizard({ me, onClose, onDone, onOpenPlan, onUploadPlan }: {
  me: Me
  onClose: () => void
  onDone: () => void            // plan saved (refresh goal/plan elsewhere)
  onOpenPlan: () => void
  onUploadPlan: () => void
  /** kept for callers; Garmin now connects in the app's connect popup, which refreshes /me */
  onMeChanged?: () => void
}) {
  const [draft, setDraftState] = useState<Draft>(() => initialDraft(me))
  // The draft is saved only once the user has changed something: merely opening the
  // wizard mustn't store the server's current values as a "draft" over later edits.
  const changed = useRef(false)
  const setDraft: typeof setDraftState = (v) => { changed.current = true; setDraftState(v) }
  const [step, setStep] = useState<StepName>('intro')
  const [closing, setClosing] = useState(false)
  const [liftAsk, setLiftAsk] = useState<Day | null>(null)  // "Add strength workouts?" from the rhythm step
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [plan, setPlan] = useState<BuiltPlan | null>(null)
  const [sync, setSync] = useState<{ days: number; result: SyncResult | null; busy: boolean; error: string | null }>({ days: 14, result: null, busy: false, error: null })

  // Start from the main event's real type, location and lookup details.
  useEffect(() => {
    const eid = me.goal?.event_id
    if (!eid || draft.newGoal) return
    let live = true
    listEvents().then((r) => {
      const ev = r.events.find((e) => e.id === eid)
      if (!live || !ev) return
      // The server's event wins over a restored draft for whatever it has.
      setDraftState((d) => d.newGoal ? d : ({ ...d, event: { ...d.event, type: ev.type,
        ...(ev.location ? { location: ev.location } : {}), ...(ev.url ? { url: ev.url } : {}),
        ...(ev.info ? { info: ev.info } : {}) } }))
    }, () => {})
    return () => { live = false }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step === 'done' || !changed.current) return
    writeDraft(DRAFT_KEY, draft, 'plan setup')
  }, [draft, step])

  const g = draft.goal
  const a = draft.athlete
  const imperial = a.units !== 'metric'
  const sports = sportsFor(g.distance)
  const setG = (p: Partial<GoalFull>) => setDraft((d) => ({ ...d, goal: { ...d.goal, ...p } }))
  const setA = (p: Partial<AthleteFull>) => setDraft((d) => ({ ...d, athlete: { ...d.athlete, ...p } }))
  // The rhythm step: lifting / riding days become training days, Rest days stop being one.
  const setRhythm = (r: WeekRhythm) => {
    const days = syncDays(a.available_days, r)
    setA({ week_rhythm: r, available_days: days, long_day: days.includes(a.long_day ?? '') ? a.long_day : days[days.length - 1] ?? null })
  }
  const noRace = !!g.no_race
  // A training block has no race-day goal, so its "A great day" step is skipped.
  const shown = STEPS.filter((s) => !(noRace && s === 'goal'))
  const pos = shown.indexOf(step)
  // lib/usage: setup funnel (the optional rhythm step counts as "week" until usage.py lists it)
  useEffect(() => { if (step !== 'done') track('setup_step', { step: step === 'rhythm' ? 'week' : step }) }, [step])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  // ------------------------------------------------------- validation ---
  const weeks = weeksUntil(g.date)
  const problem = useMemo((): string | null => {
    if (step === 'race' && noRace) {
      if (!g.distance) return 'Pick what you want to train for.'
    } else if (step === 'race') {
      if (!g.distance) return 'Pick the race distance.'
      if (!g.date) return 'Add the race date.'
      if (g.date <= todayIso()) return 'The race date needs to be in the future.'
    }
    if (step === 'goal' && g.goal_type === 'time' && !TIME_RE.test((g.target_time ?? '').trim())) {
      return 'Enter your target time: hours, minutes and seconds.'
    }
    if (step === 'week') {
      if (!a.weekly_hours) return 'How many hours a week do you train now?'
      if ((a.available_days ?? []).length < 2) return 'Pick at least two training days.'
    }
    if (step === 'rhythm' && (a.available_days ?? []).length < 2) return 'Leave at least two days that aren\'t Rest.'
    return null
  }, [step, g, a])

  const next = () => {
    if (problem) { setError(problem); return }
    setError(null); setNote(null)
    setStep(shown[Math.min(pos + 1, shown.length - 1)]!)
  }
  const back = () => { setError(null); setNote(null); setStep(shown[Math.max(0, pos - 1)]!) }

  async function fillFromGarmin() {
    setBusy(true); setNote(null)
    try {
      const { numbers } = await getGarminNumbers()
      const filled: string[] = []
      const patch: Partial<AthleteFull> = {}
      for (const [k, v] of Object.entries(numbers) as [keyof AthleteFull, unknown][]) {
        if (v == null || (a[k] != null && a[k] !== '')) continue
        ;(patch as Record<string, unknown>)[k] = v
        filled.push(k.replace(/_/g, ' '))
      }
      setA(patch)
      setNote(filled.length ? `Filled in from Garmin: ${filled.join(', ')}.` : 'Nothing new from Garmin; your answers stay as they are.')
    } catch (e) {
      setNote((e as Error).message)
    } finally { setBusy(false) }
  }

  // What the server builds from (setup and the live Review preview send the same thing).
  const payload = () => {
    const goal: Partial<GoalFull> = { ...g }
    const dist = DISTANCES.find((d) => d.value === g.distance)
    if (g.no_race) {
      // A block: it ends the day before the same weekday N weeks after the start.
      const weeks = draft.blockWeeks ?? 12
      const f = FOCUS.find((x) => x.id === focusOf(g.distance))!
      goal.date = addDays(draft.start_date, weeks * 7 - 1)
      goal.title = `${weeks}-week ${f.id === 'fitness' ? 'fitness' : f.title.toLowerCase()} block`
      goal.event = ''
      goal.goal_type = 'finish'
      goal.priority = 'A'
    } else {
      goal.title = (g.title || g.event || dist?.label || 'My race').trim()
      goal.no_race = false
    }
    if (g.goal_type !== 'time' || g.no_race) goal.target_time = null
    const athlete: Partial<AthleteFull> = { ...a }
    for (const k of Object.keys(athlete) as (keyof AthleteFull)[]) {
      if (athlete[k] === '' && k !== 'injuries' && k !== 'experience') delete athlete[k]
    }
    if (athlete.long_day && !(athlete.available_days ?? []).includes(athlete.long_day)) athlete.long_day = null
    athlete.week_rhythm = cleanRhythm(athlete.week_rhythm)
    if (athlete.strength_opt_in == null) delete athlete.strength_opt_in
    return { athlete, goal }
  }
  const newGoal = (draft.newGoal && !!me.goal) || !me.goal
  // Levers keep the long day on a training day.
  const setLevers = (p: Partial<AthleteFull>) => setA({ ...p, ...(p.available_days && a.long_day && !p.available_days.includes(a.long_day) ? { long_day: p.available_days.slice(-1)[0] ?? null } : {}) })
  const preview = usePreview(step === 'review' && !busy ? { ...payload(), start_date: draft.start_date, new_goal: newGoal } : null)

  async function build() {
    setBusy(true); setError(null)
    try {
      const { athlete, goal } = payload()
      const r = await setupPlan({ athlete, goal, event: goal.no_race ? undefined : draft.event, start_date: draft.start_date, new_goal: draft.newGoal && !!me.goal })
      setPlan(r.plan)
      clearDraft(DRAFT_KEY)
      setStep('done')
      celebrate(null, 'plan') // a new plan: carrots fly (haptic; nothing moves under reduced motion)
      track('setup_complete')
      onDone()
    } catch (e) {
      setError((e as Error).message)
    } finally { setBusy(false) }
  }

  async function doSync() {
    setSync((s) => ({ ...s, busy: true, error: null }))
    try {
      const r = await syncGarmin(sync.days)
      setPlan(r.plan)
      setSync((s) => ({ ...s, busy: false, result: r.result }))
    } catch (e) {
      setSync((s) => ({ ...s, busy: false, error: (e as Error).message }))
    }
  }

  // ------------------------------------------------------------ steps ---
  const showProgress = step !== 'intro' && step !== 'done'
  const footer = step === 'intro' ? null : step === 'done' ? (
    <>
      <Button variant="default" className="h-11 flex-1 text-body" onClick={close}>Done</Button>
      <Button variant="primary" className="h-11 flex-1 text-body" onClick={onOpenPlan}>See my plan</Button>
    </>
  ) : (
    <>
      {pos > 1 && <Button variant="default" className="h-11 px-5 text-body" onClick={back}>Back</Button>}
      {step === 'review' ? (
        <Button variant="primary" className="h-11 flex-1 gap-1.5 text-body" loading={busy} onClick={() => void build()}>
          <Route className="size-5" aria-hidden /> Start this plan
        </Button>
      ) : (
        <Button variant="primary" className="h-11 flex-1 text-body" onClick={next}>
          {step === 'numbers' && !hasNumbers(a) ? 'Skip for now' : step === 'rhythm' && !rhythmSummary(a.week_rhythm ?? {}) ? 'Skip' : 'Continue'}
        </Button>
      )}
    </>
  )

  return (
    <Screen title={step === 'done' ? 'Your plan' : 'Plan setup'} closing={closing} onClose={close}
      onBack={pos > 0 && step !== 'done' ? back : undefined}
      headerExtra={showProgress ? <Progress step={pos - 1} total={shown.length - 2} names={shown.slice(1, -1).map((s) => STEP_NAME[s] ?? '')} /> : undefined}
      footer={footer}>

      {step === 'intro' && (
        <>
          <div className="flex flex-col items-center px-2 pt-4 text-center">
            <span className="logo-tile mb-4 flex size-[72px] items-center justify-center rounded-[20px] bg-(--brand) shadow-md">
              <RabbitLogo size={60} />
            </span>
            <h3 className="font-display text-display leading-tight text-(--brand)">Let's build your plan</h3>
            <p className="mt-2 max-w-sm text-body-lg leading-snug text-(--text-secondary)">
              A few questions about your goal and your week. Training for a race or not, rabbt turns
              them into a week-by-week plan with structured workouts, and can put them on your Garmin.
            </p>
          </div>
          <Card>
            {[
              [Target, 'Your goal', 'A race, or just getting fitter'],
              [User, 'About you', 'Experience, body and any injuries'],
              [HeartPulse, 'Your numbers', 'Heart rate, FTP and paces, if you know them'],
              [CalendarDays, 'Your week', 'Hours, training days and equipment'],
            ].map(([Icon, t, s]) => {
              const I = Icon as typeof Target
              return (
                <div key={t as string} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><I className="size-[17px]" /></span>
                  <span className="min-w-0">
                    <span className="block text-lead text-(--text)">{t as string}</span>
                    <span className="block text-small text-(--text-muted)">{s as string}</span>
                  </span>
                </div>
              )
            })}
          </Card>
          <p className="px-1 text-center text-meta text-(--text-muted)">
            About 3 minutes.{me.garmin.connected ? ' rabbt can fill in what Garmin already knows.' : ''}
          </p>
          <div className="flex flex-col gap-2">
            <Button variant="primary" className="h-12 text-body-lg" onClick={next}>Get started</Button>
            <Button asChild variant="default" className="h-11 gap-1.5 text-body">
              <label htmlFor={ATTACH_INPUT_ID} onClick={onUploadPlan}><Upload className="size-5" /> I already have a plan</label>
            </Button>
          </div>
        </>
      )}

      {step === 'race' && (
        <>
          <StepIntro eyebrow="Your goal" title="What are you training for?">
            A race gives the plan a date to build toward. No race? rabbt builds a training block instead.
          </StepIntro>
          <div className="flex flex-col gap-2">
            <OptionCard selected={!noRace} title="A race or event" description="Your plan works back from race day."
              onClick={() => setG({ no_race: false, ...(g.no_race ? { distance: undefined, date: null } : {}) })} />
            <OptionCard selected={noRace} title="No race, just train" description="Get fitter, build to a distance, or stay consistent."
              onClick={() => setG({ no_race: true, goal_type: 'finish', ...(!g.no_race ? { distance: undefined } : {}) })} />
          </div>
          {me.goal && !noRace && (
            <Card>
              <Field label="This plan is for">
                <ChipRow>
                  <Chip selected={!draft.newGoal} onClick={() => setDraft((d) => ({ ...d, newGoal: false }))}>{me.goal.title}</Chip>
                  <Chip selected={draft.newGoal} onClick={() => setDraft((d) => ({ ...d, newGoal: true, event: { type: 'triathlon' }, goal: { priority: 'A', goal_type: 'finish', limiters: [] } }))}>A new race</Chip>
                </ChipRow>
              </Field>
            </Card>
          )}
          {noRace ? (
            <>
              <Card>
                <Field label="What do you want to work on?">
                  <div className="flex flex-col gap-2">
                    {FOCUS.map((f) => (
                      <OptionCard key={f.id} selected={!!g.distance && focusOf(g.distance) === f.id} title={f.title} description={f.description}
                        onClick={() => setG({ distance: f.distance })} />
                    ))}
                  </div>
                </Field>
                {(() => {
                  const f = g.distance ? FOCUS.find((x) => x.id === focusOf(g.distance)) : null
                  return f?.options ? (
                    <Field label="Build toward (optional)" className="border-t border-(--border)" hint="Sets the long workouts. Pick the one closest to what you want.">
                      <ChipRow>
                        {f.options.map((d) => (
                          <Chip key={d} selected={g.distance === d} onClick={() => setG({ distance: d })}>{DISTANCES.find((x) => x.value === d)?.label ?? d}</Chip>
                        ))}
                      </ChipRow>
                    </Field>
                  ) : null
                })()}
                <Field label="How long?" className="border-t border-(--border)" hint="You can start another block when this one ends.">
                  <ChipRow>
                    {BLOCK_WEEKS.map((w) => (
                      <Chip key={w} selected={(draft.blockWeeks ?? 12) === w} onClick={() => setDraft((d) => ({ ...d, blockWeeks: w }))}>{w} weeks</Chip>
                    ))}
                  </ChipRow>
                </Field>
              </Card>
            </>
          ) : (
            <>
              <EventBasics value={{ name: g.event ?? '', type: draft.event.type, distance: g.distance ?? '', date: g.date ?? '',
                location: draft.event.location, url: draft.event.url, info: draft.event.info ?? undefined }}
                onChange={(p) => {
                  const gp: Partial<GoalFull> = {}
                  if (p.name !== undefined) { gp.event = p.name; gp.title = p.name }
                  if (p.distance !== undefined) gp.distance = p.distance
                  if (p.date !== undefined) gp.date = p.date || null
                  if (p.course !== undefined && !g.course) gp.course = p.course
                  if (Object.keys(gp).length) setG(gp)
                  const { type, location, url, info } = p
                  const ep: EventFields = Object.fromEntries(Object.entries({ type, location, url, info }).filter(([, v]) => v !== undefined))
                  if (Object.keys(ep).length) setDraft((d) => ({ ...d, event: { ...d.event, ...ep } }))
                }} />
              {weeks != null && g.date && g.date > todayIso() && <p className="-mt-3 px-4 text-small text-(--text-muted)">{runwayHint(weeks)}</p>}
              <Card>
                <Field label="Course notes" hint="Optional: hilly, hot, wetsuit, altitude…">
                  <textarea className={areaCls} value={g.course ?? ''} maxLength={300} onChange={(e) => setG({ course: e.target.value })}
                    placeholder="Anything about the course" />
                </Field>
              </Card>
            </>
          )}
        </>
      )}

      {step === 'goal' && (
        <>
          <StepIntro eyebrow="Your goal" title="What would make it a great day?" />
          <div className="flex flex-col gap-2">
            <OptionCard selected={g.goal_type === 'finish'} title="Finish strong" description="Get to the line healthy and enjoy it." onClick={() => setG({ goal_type: 'finish' })} />
            <OptionCard selected={g.goal_type === 'time'} title="Hit a time" description="You have a target time in mind." onClick={() => setG({ goal_type: 'time' })} />
            <OptionCard selected={g.goal_type === 'compete'} title="Compete" description="Chasing a podium, an age-group place or a qualifying spot." onClick={() => setG({ goal_type: 'compete' })} />
          </div>
          <Card>
            {g.goal_type === 'time' && (
              <Field label="Target time">
                <TimeFields label="Target time" value={g.target_time} onChange={(v) => setG({ target_time: v })}
                  presets={TARGET_PRESETS[g.distance ?? '']} scrollOnMount />
              </Field>
            )}
            {sports.length > 1 && (
              <Field label="Which sport needs the most work? (optional)" hint="rabbt adds a little extra time there. Skip it if none of these fit.">
                <MultiChoice value={(g.limiters ?? []) as ('swim' | 'bike' | 'run')[]}
                  options={sports.filter((s): s is 'swim' | 'bike' | 'run' => s === 'swim' || s === 'bike' || s === 'run').map((s) => [s, s[0]!.toUpperCase() + s.slice(1)] as const)}
                  onChange={(v) => setG({ limiters: v })} />
                {(g.limiters ?? []).length > 0 && (
                  <button type="button" className="min-h-11 self-start text-small font-medium text-(--accent)" onClick={() => setG({ limiters: [] })}>None of these</button>
                )}
              </Field>
            )}
            <Field label="Anything else that matters?" hint="Optional: worries, priorities, why this race, or anything the options above missed.">
              <textarea className={areaCls} value={g.priorities ?? ''} maxLength={600} onChange={(e) => setG({ priorities: e.target.value })}
                placeholder="e.g. First half Ironman, nervous about the swim" />
            </Field>
          </Card>
        </>
      )}

      {step === 'you' && (
        <>
          <StepIntro eyebrow="About you" title="Tell rabbt about yourself">
            This sets how hard the plan ramps up. All of it is optional except your experience.
          </StepIntro>
          {me.garmin.connected && <GarminFill busy={busy} onClick={() => void fillFromGarmin()} />}
          {note && <p className="px-1 text-small text-(--accent)">{note}</p>}
          <YouFields a={a} setA={setA} sports={sports} />
        </>
      )}

      {step === 'numbers' && (
        <>
          <StepIntro eyebrow="Your numbers" title="Training zones">
            These set the targets on your watch. Skip any you don't know: workouts then use
            your Garmin heart-rate zones.
          </StepIntro>
          {me.garmin.connected && <GarminFill busy={busy} onClick={() => void fillFromGarmin()} />}
          {note && <p className="px-1 text-small text-(--accent)">{note}</p>}
          <NumbersFields a={a} setA={setA} sports={sports} />
        </>
      )}

      {step === 'week' && (
        <>
          <StepIntro eyebrow="Your week" title="When can you train?">
            rabbt starts close to what you do now and builds gradually from there.
          </StepIntro>
          <WeekFields a={a} setA={setA} sports={sports} />
        </>
      )}

      {step === 'rhythm' && (
        <>
          <StepIntro eyebrow="Optional" title="Want a set weekly rhythm?">
            Like lifting Mon, Wed, Fri and biking Tue, Thu, Sat. Leave a day on Any and rabbt picks. Skip it and rabbt plans the whole week.
          </StepIntro>
          <RhythmGrid value={a.week_rhythm ?? {}} onChange={setRhythm} strengthOptIn={a.strength_opt_in}
            onNeedOptIn={(d) => setLiftAsk(d)} />
          {liftAsk && (
            <StrengthOptInSheet
              onYes={() => { const d = liftAsk; setLiftAsk(null); setA({ strength_opt_in: true }); setRhythm(toggleRhythm(a.week_rhythm ?? {}, d, 'strength')) }}
              onNo={() => setLiftAsk(null)} />
          )}
        </>
      )}

      {step === 'review' && busy && (
        <div className="flex flex-col items-center px-2 pt-6 text-center">
          <h3 className="font-display text-display-sm leading-tight text-(--brand)">Building your plan</h3>
          <RabbitLoader size={72} className="pt-4" label="Building your plan"
            cycle={['Mapping your weeks…', 'Placing long workouts…', 'Balancing hard and easy days…', 'Tapering into race day…']} />
        </div>
      )}

      {step === 'review' && !busy && (
        <>
          <StepIntro eyebrow="Review" title="Here's your plan">
            Tweak anything below and the plan updates right away. Nothing is saved until you start it.
          </StepIntro>
          {preview.summary ? (
            <SetupReview s={preview.summary}
              levers={{ available_days: a.available_days, long_day: a.long_day, weekly_hours: a.weekly_hours, plan_intensity: a.plan_intensity }}
              setLevers={setLevers}
              start={draft.start_date} setStart={(d) => setDraft((x) => ({ ...x, start_date: d }))} minStart={todayIso()} maxStart={noRace ? undefined : g.date ?? undefined} />
          ) : preview.error ? (
            <p className="px-1 text-small text-(--danger)" role="alert">{preview.error}</p>
          ) : <RabbitLoader className="py-6" label="Sketching your plan" cycle={['Mapping your weeks…', 'Placing long workouts…', 'Balancing hard and easy days…']} />}
          {preview.busy && preview.summary && <RabbitLoader inline className="px-1 text-meta" label="Updating…" />}
          <details className="rounded-xl border border-(--border) bg-(--bg-surface)">
            <summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-x-3 px-4 py-2 text-body font-semibold text-(--text) [&::-webkit-details-marker]:hidden">
              <span className="flex-1">Adjust your plan</span><span className="text-meta text-(--accent)">Days, hours, start</span>
            </summary>
            <div className="border-t border-(--border)">
              <LeverFields v={{ available_days: a.available_days, long_day: a.long_day, weekly_hours: a.weekly_hours, plan_intensity: a.plan_intensity }}
                set={setLevers}
                start={draft.start_date} setStart={(d) => setDraft((x) => ({ ...x, start_date: d }))} minStart={todayIso()} maxStart={noRace ? undefined : g.date ?? undefined} />
            </div>
          </details>
          <details className="rounded-xl border border-(--border) bg-(--bg-surface)">
            <summary className="flex min-h-12 cursor-pointer list-none items-center px-4 text-body font-medium text-(--text) [&::-webkit-details-marker]:hidden">
              <span className="flex-1">Your answers</span><span className="text-meta text-(--accent)">Edit</span>
            </summary>
            <div className="border-t border-(--border)">
              <ReviewRow label={noRace ? 'Block' : 'Race'} onEdit={() => setStep('race')}
                value={noRace
                  ? `${draft.blockWeeks ?? 12} weeks of ${FOCUS.find((f) => f.id === focusOf(g.distance))?.title.toLowerCase() ?? 'training'}${g.distance && g.distance !== 'other' ? `, toward ${DISTANCES.find((d) => d.value === g.distance)?.label ?? g.distance}` : ''}`
                  : [DISTANCES.find((d) => d.value === g.distance)?.label, g.event, g.date && new Date(`${g.date}T12:00:00`).toLocaleDateString([], { dateStyle: 'medium' })].filter(Boolean).join(', ')} />
              {!noRace && (
                <ReviewRow label="Goal" onEdit={() => setStep('goal')}
                  value={[g.goal_type === 'time' ? `Target ${g.target_time}` : g.goal_type === 'compete' ? 'Compete' : 'Finish strong',
                    (g.limiters ?? []).length ? `More ${(g.limiters ?? []).join(' and ')}` : ''].filter(Boolean).join(', ')} />
              )}
              <ReviewRow label="Your week" onEdit={() => setStep('rhythm')}
                value={[rhythmSummary(a.week_rhythm ?? {}) ?? 'rabbt picks each day', a.strength_opt_in ? 'strength workouts on' : null].filter(Boolean).join(', ')} />
              <ReviewRow label="You" onEdit={() => setStep('you')}
                value={[levelLabel(a.level), a.age && `${a.age} yrs`, a.height_cm && (imperial ? `${cmToFtIn(a.height_cm).ft}'${cmToFtIn(a.height_cm).inch}"` : `${a.height_cm} cm`),
                  a.weight_kg && (imperial ? `${kgToLb(a.weight_kg)} lb` : `${a.weight_kg} kg`)].filter(Boolean).join(', ') || 'Not set'} />
              <ReviewRow label="Numbers" onEdit={() => setStep('numbers')}
                value={[a.threshold_hr && `Threshold heart rate ${a.threshold_hr}`, a.ftp_w && `Threshold power ${a.ftp_w} W`,
                  a.run_threshold_pace && `Threshold pace ${fmtPace(imperial ? a.run_threshold_pace * KM_PER_MI : a.run_threshold_pace)}/${imperial ? 'mi' : 'km'}`,
                  a.swim_css && `Swim pace ${fmtPace(a.swim_css)}/100m`].filter(Boolean).join(', ') || 'Heart-rate zones from Garmin'} />
            </div>
          </details>
          {me.goal?.plan && !draft.newGoal && (
            <p className="px-1 text-small text-(--warning-text)">
              {noRace && !me.goal.no_race
                ? `This replaces your current plan. ${me.goal.title} stays saved in your goals, so you can build for it again later.`
                : `This replaces the current plan for ${me.goal.title}.`} Workouts already synced to Garmin get cleaned up on the next sync.
            </p>
          )}
        </>
      )}

      {step === 'done' && plan && (
        <>
          <div className="flex flex-col items-center px-2 pt-2 text-center">
            <RabbitNap size={56} mode="cheer" className="mb-2" />
            <h3 className="font-display text-display-sm leading-tight text-(--brand)">Your plan is ready</h3>
            <p className="mt-1.5 text-body text-(--text-secondary)">
              {plan.no_race ? `${plan.weeks.length} weeks of training` : `${plan.weeks.length} weeks to ${g.title || 'race day'}`}, {hoursLine(plan.start_hours, plan.peak_hours)}.
            </p>
            {plan.note && <p className="mt-1.5 text-small text-(--text-muted)">{plan.note}</p>}
          </div>
          <Card className="p-4"><PhaseStrip plan={plan} /></Card>
          <WeekPreview week={plan.weeks.find((w) => w.index === plan.current_week) ?? plan.weeks[0]!} />

          <Card>
            <Field label="Put it on your watch" hint="rabbt adds upcoming sessions to your Garmin calendar as structured workouts. Re-sync anytime from the plan.">
              {me.garmin.connected ? (
                <div className="flex flex-col gap-2.5">
                  <ChipRow>
                    {[7, 14, 28].map((d) => <Chip key={d} selected={sync.days === d} onClick={() => setSync((s) => ({ ...s, days: d }))}>Next {d} days</Chip>)}
                  </ChipRow>
                  <Button variant="primary" className="h-11 gap-1.5 text-body" loading={sync.busy} onClick={() => void doSync()}>
                    <Watch className="size-5" /> {sync.result ? 'Sync again' : 'Sync to Garmin'}
                  </Button>
                  {sync.busy && <RabbitLoader inline className="text-small" label="Sending to your watch…" />}
                  {sync.result && <SyncSummary result={sync.result} />}
                  {sync.error && <p className="text-small text-(--danger)">{sync.error}</p>}
                </div>
              ) : me.garmin.can_connect ? (
                <GarminEmpty what="workout" compact />
              ) : <p className="text-small text-(--text-muted)">Garmin isn't available on this server.</p>}
            </Field>
          </Card>
        </>
      )}

      {error && <p className="px-1 text-small text-(--danger)" role="alert">{error}</p>}
      {showProgress && step !== 'review' && sports.length > 0 && g.distance && (
        <div className="flex justify-center gap-1.5 pt-1 text-(--text-muted)" aria-hidden>
          {sports.map((s) => { const I = SPORT_ICON[s]; return I ? <I key={s} className="size-4" /> : null })}
        </div>
      )}
    </Screen>
  )
}

function typeForDistance(d: string | undefined | null): EventType {
  if (!d) return 'triathlon'
  if (d === 'other') return 'other'
  const hit = (Object.entries(TYPE_DISTANCES) as [EventType, string[]][]).find(([t, ds]) => t !== 'other' && ds.includes(d))
  return hit ? hit[0] : 'other'
}

function hasNumbers(a: Partial<AthleteFull>): boolean {
  return [a.resting_hr, a.max_hr, a.threshold_hr, a.ftp_w, a.run_threshold_pace, a.swim_css].some((v) => v != null)
}
const levelLabel = (l: AthleteFull['level']) => l === 'new' ? 'New to this' : l === 'intermediate' ? 'A few seasons in' : l === 'advanced' ? 'Experienced' : ''

function runwayHint(weeks: number): string {
  if (weeks < 4) return `${weeks} week${weeks === 1 ? '' : 's'} away: a short sharpening block and taper.`
  if (weeks < 10) return `${weeks} weeks away: a compact build and taper.`
  if (weeks > 52) return `${weeks} weeks away: the plan covers the last 52 weeks.`
  return `${weeks} weeks away: room for base, build, peak and taper.`
}

function ReviewRow({ label, value, onEdit }: { label: string; value: string; onEdit: () => void }) {
  return (
    <button type="button" onClick={onEdit} className="flex w-full items-start gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
      <span className="w-[84px] shrink-0 pt-0.5 text-meta font-semibold text-(--text-muted)">{label}</span>
      <span className="min-w-0 flex-1 text-body leading-snug text-(--text)">{value}</span>
      <span className="text-meta text-(--accent)">Edit</span>
    </button>
  )
}

export function SyncSummary({ result }: { result: SyncResult }) {
  const parts = [
    result.uploaded && `${result.uploaded} added`,
    result.unchanged && `${result.unchanged} already there`,
    result.removed && `${result.removed} removed`,
  ].filter(Boolean)
  return (
    <div className="flex flex-col gap-1 text-small">
      <p className="text-(--accent)">{parts.length ? `${parts.join(', ')}.` : 'Nothing to sync in that window.'} Open Garmin Connect and sync your watch to see them.</p>
      {result.errors.map((e, i) => (
        <p key={i} className="text-(--danger)">{e.title}{e.date ? ` (${e.date})` : ''}: {e.error}</p>
      ))}
    </div>
  )
}
