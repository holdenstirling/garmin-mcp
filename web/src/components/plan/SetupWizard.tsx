// Guided setup: race -> goal -> you -> your numbers -> your week -> review, then Rabbit
// builds a periodized plan and (optionally) puts the next sessions on your Garmin.
// Answers are kept as a local draft so leaving halfway loses nothing.
import { useEffect, useMemo, useState } from 'react'
import { Bike, CalendarDays, Check, Footprints, HeartPulse, Sparkles, Target, Upload, User, Waves, Watch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLogo } from '@/components/RabbitLogo'
import { ConnectGarmin } from '@/components/ConnectGarmin'
import { ATTACH_INPUT_ID } from '@/components/chat/Composer'
import type { Me, Sport } from '@/lib/api'
import {
  DISTANCES, EQUIPMENT, WEEKDAYS, cmToFtIn, fmtPace, ftInToCm, getGarminNumbers, kgToLb, lbToKg, KM_PER_MI,
  parsePace, setupPlan, sportsFor, syncGarmin, weeksUntil,
  type AthleteFull, type BuiltPlan, type GoalFull, type SyncResult,
} from '@/lib/plan'
import { Card, Chip, ChipRow, Choice, Field, MultiChoice, NumberStepper, OptionCard, Progress, Screen, StepIntro, areaCls, inputCls } from './ui'
import { PhaseStrip, WeekPreview } from './PlanParts'

const STEPS = ['intro', 'race', 'goal', 'you', 'numbers', 'week', 'review', 'done'] as const
type StepName = typeof STEPS[number]
const DRAFT_KEY = 'rabbit.setup.v1'

type Draft = {
  newGoal: boolean
  goal: Partial<GoalFull>
  athlete: Partial<AthleteFull>
  start_date: string
}

const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const TIME_RE = /^(\d{1,2}):([0-5]\d)(:([0-5]\d))?$/

function initialDraft(me: Me): Draft {
  const a = (me.athlete ?? {}) as AthleteFull
  const g = (me.goal ?? null) as GoalFull | null
  const fresh: Draft = {
    newGoal: !g,
    goal: g ? {
      title: g.title, event: g.event, distance: g.distance || undefined, date: g.date, priority: g.priority ?? 'A',
      course: g.course ?? '', goal_type: g.goal_type ?? (g.target ? 'time' : 'finish'), target_time: g.target_time ?? '',
      priorities: g.priorities ?? '', limiters: g.limiters ?? [],
    } : { priority: 'A', goal_type: 'finish', limiters: [] },
    athlete: {
      units: a.units ?? 'metric', sex: a.sex ?? null, age: a.age ?? null, height_cm: a.height_cm ?? null,
      weight_kg: a.weight_kg ?? null, level: a.level ?? null, injuries: a.injuries ?? '', experience: a.experience ?? '',
      resting_hr: a.resting_hr ?? null, max_hr: a.max_hr ?? null, threshold_hr: a.threshold_hr ?? null,
      ftp_w: a.ftp_w ?? null, run_threshold_pace: a.run_threshold_pace ?? null, swim_css: a.swim_css ?? null,
      weekly_hours: a.weekly_hours ?? null,
      available_days: a.available_days?.length ? a.available_days : ['tue', 'wed', 'thu', 'sat', 'sun'],
      long_day: a.long_day ?? 'sat', equipment: a.equipment ?? [],
    },
    start_date: todayIso(),
  }
  try {
    const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? 'null') as (Draft & { at: number }) | null
    if (saved && Date.now() - saved.at < 14 * 86_400_000) {
      return { ...fresh, ...saved, goal: { ...fresh.goal, ...saved.goal }, athlete: { ...fresh.athlete, ...saved.athlete }, start_date: todayIso() }
    }
  } catch { /* storage unavailable: start fresh */ }
  return fresh
}

const SPORT_ICON: Partial<Record<Sport, typeof Bike>> = { swim: Waves, bike: Bike, run: Footprints }

export function SetupWizard({ me, onClose, onDone, onOpenPlan, onUploadPlan, onMeChanged }: {
  me: Me
  onClose: () => void
  onDone: () => void            // plan saved (refresh goal/plan elsewhere)
  onOpenPlan: () => void
  onUploadPlan: () => void
  onMeChanged: () => void
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(me))
  const [step, setStep] = useState<StepName>('intro')
  const [closing, setClosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [plan, setPlan] = useState<BuiltPlan | null>(null)
  const [sync, setSync] = useState<{ days: number; result: SyncResult | null; busy: boolean; error: string | null }>({ days: 14, result: null, busy: false, error: null })

  useEffect(() => {
    if (step === 'done') return
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...draft, at: Date.now() })) } catch { /* ignore */ }
  }, [draft, step])

  const g = draft.goal
  const a = draft.athlete
  const imperial = a.units === 'imperial'
  const sports = sportsFor(g.distance)
  const setG = (p: Partial<GoalFull>) => setDraft((d) => ({ ...d, goal: { ...d.goal, ...p } }))
  const setA = (p: Partial<AthleteFull>) => setDraft((d) => ({ ...d, athlete: { ...d.athlete, ...p } }))
  const idx = STEPS.indexOf(step)
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  // ------------------------------------------------------- validation ---
  const weeks = weeksUntil(g.date)
  const problem = useMemo((): string | null => {
    if (step === 'race') {
      if (!g.distance) return 'Pick the race distance.'
      if (!g.date) return 'Add the race date.'
      if (g.date <= todayIso()) return 'The race date needs to be in the future.'
    }
    if (step === 'goal' && g.goal_type === 'time' && !TIME_RE.test((g.target_time ?? '').trim())) {
      return 'Enter your target time like 5:30:00 or 45:00.'
    }
    if (step === 'week') {
      if (!a.weekly_hours) return 'How many hours a week do you train now?'
      if ((a.available_days ?? []).length < 2) return 'Pick at least two training days.'
    }
    return null
  }, [step, g, a])

  const next = () => {
    if (problem) { setError(problem); return }
    setError(null); setNote(null)
    setStep(STEPS[Math.min(idx + 1, STEPS.length - 1)]!)
  }
  const back = () => { setError(null); setNote(null); setStep(STEPS[Math.max(0, idx - 1)]!) }

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

  async function build() {
    setBusy(true); setError(null)
    try {
      const goal: Partial<GoalFull> = { ...g }
      const dist = DISTANCES.find((d) => d.value === g.distance)
      goal.title = (g.title || g.event || dist?.label || 'My race').trim()
      if (g.goal_type !== 'time') goal.target_time = null
      const athlete: Partial<AthleteFull> = { ...a }
      for (const k of Object.keys(athlete) as (keyof AthleteFull)[]) {
        if (athlete[k] === '' && k !== 'injuries' && k !== 'experience') delete athlete[k]
      }
      if (athlete.long_day && !(athlete.available_days ?? []).includes(athlete.long_day)) athlete.long_day = null
      const r = await setupPlan({ athlete, goal, start_date: draft.start_date, new_goal: draft.newGoal && !!me.goal })
      setPlan(r.plan)
      try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
      setStep('done')
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
      <Button variant="default" className="h-11 flex-1 text-[0.8235rem]" onClick={close}>Done</Button>
      <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={onOpenPlan}>See my plan</Button>
    </>
  ) : (
    <>
      {idx > 1 && <Button variant="default" className="h-11 px-5 text-[0.8235rem]" onClick={back}>Back</Button>}
      {step === 'review' ? (
        <Button variant="primary" className="h-11 flex-1 gap-1.5 text-[0.8235rem]" loading={busy} onClick={() => void build()}>
          <Sparkles className="size-4" /> Build my plan
        </Button>
      ) : (
        <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]" onClick={next}>
          {step === 'numbers' && !hasNumbers(a) ? 'Skip for now' : 'Continue'}
        </Button>
      )}
    </>
  )

  return (
    <Screen title={step === 'done' ? 'Your plan' : 'Plan setup'} closing={closing} onClose={close}
      subtitle={showProgress ? `Step ${idx} of ${STEPS.length - 2}` : undefined}
      onBack={idx > 0 && step !== 'done' ? back : undefined}
      headerExtra={showProgress ? <Progress step={idx - 1} total={STEPS.length - 2} /> : undefined}
      footer={footer}>

      {step === 'intro' && (
        <>
          <div className="flex flex-col items-center px-2 pt-4 text-center">
            <span className="logo-tile mb-4 flex size-[72px] items-center justify-center rounded-[20px] bg-(--brand) shadow-md">
              <RabbitLogo size={60} />
            </span>
            <h3 className="font-display text-[1.6471rem] leading-tight text-(--brand)">Let's build your plan</h3>
            <p className="mt-2 max-w-sm text-[0.8824rem] leading-snug text-(--text-secondary)">
              A few questions about your race, your goals and your week. Rabbit turns them into a
              week-by-week plan with structured workouts, and can put them on your Garmin.
            </p>
          </div>
          <Card>
            {[
              [Target, 'Your race and goal', 'Distance, date, and what success looks like'],
              [User, 'About you', 'Experience, body and any injuries'],
              [HeartPulse, 'Your numbers', 'Heart rate, FTP and paces, if you know them'],
              [CalendarDays, 'Your week', 'Hours, training days and equipment'],
            ].map(([Icon, t, s]) => {
              const I = Icon as typeof Target
              return (
                <div key={t as string} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-(--accent-subtle) text-(--accent)"><I className="size-[17px]" /></span>
                  <span className="min-w-0">
                    <span className="block text-[0.9412rem] text-(--text)">{t as string}</span>
                    <span className="block text-[0.7647rem] text-(--text-muted)">{s as string}</span>
                  </span>
                </div>
              )
            })}
          </Card>
          <p className="px-1 text-center text-[0.7059rem] text-(--text-muted)">
            About 3 minutes.{me.garmin.connected ? ' Rabbit can fill in what Garmin already knows.' : ''}
          </p>
          <div className="flex flex-col gap-2">
            <Button variant="primary" className="h-12 text-[0.8824rem]" onClick={next}>Get started</Button>
            <Button asChild variant="default" className="h-11 gap-1.5 text-[0.8235rem]">
              <label htmlFor={ATTACH_INPUT_ID} onClick={onUploadPlan}><Upload className="size-4" /> I already have a plan</label>
            </Button>
          </div>
        </>
      )}

      {step === 'race' && (
        <>
          <StepIntro eyebrow="Your race" title="What are you training for?">
            Your plan works back from race day, so the date matters most.
          </StepIntro>
          {me.goal && (
            <Card>
              <Field label="This plan is for">
                <ChipRow>
                  <Chip selected={!draft.newGoal} onClick={() => setDraft((d) => ({ ...d, newGoal: false }))}>{me.goal.title}</Chip>
                  <Chip selected={draft.newGoal} onClick={() => setDraft((d) => ({ ...d, newGoal: true, goal: { priority: 'A', goal_type: 'finish', limiters: [] } }))}>A new race</Chip>
                </ChipRow>
              </Field>
            </Card>
          )}
          <Card>
            <Field label="Distance">
              <ChipRow>
                {DISTANCES.map((d) => (
                  <Chip key={d.value} selected={g.distance === d.value} onClick={() => setG({ distance: d.value })}>{d.label}</Chip>
                ))}
              </ChipRow>
            </Field>
            <Field label="Race name" hint="Optional. e.g. Boulder 70.3 or the Denver Half.">
              <input className={inputCls} value={g.event ?? ''} placeholder="Race name" maxLength={120}
                onChange={(e) => setG({ event: e.target.value, title: e.target.value })} />
            </Field>
            <Field label="Race date" hint={weeks != null && g.date && g.date > todayIso() ? runwayHint(weeks) : undefined}>
              <input type="date" className={inputCls} value={g.date ?? ''} min={todayIso()} onChange={(e) => setG({ date: e.target.value || null })} />
            </Field>
          </Card>
          <Card>
            <Field label="How important is it?" hint="Your A race gets the full taper. B and C races are tune-ups.">
              <Choice value={g.priority ?? 'A'} onChange={(v) => setG({ priority: v ?? 'A' })}
                options={[['A', 'A race'], ['B', 'B race'], ['C', 'Training race']]} />
            </Field>
            <Field label="Course notes" hint="Optional: hilly, hot, wetsuit, altitude…">
              <textarea className={areaCls} value={g.course ?? ''} maxLength={300} onChange={(e) => setG({ course: e.target.value })}
                placeholder="Anything about the course" />
            </Field>
          </Card>
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
              <Field label="Target time" hint="Hours:minutes:seconds, or minutes:seconds for short races.">
                <input className={inputCls} inputMode="numeric" placeholder="5:30:00" value={g.target_time ?? ''}
                  onChange={(e) => setG({ target_time: e.target.value })} />
              </Field>
            )}
            {sports.length > 1 && (
              <Field label="Which needs the most work?" hint="Rabbit adds a little extra time there.">
                <MultiChoice value={(g.limiters ?? []) as ('swim' | 'bike' | 'run')[]}
                  options={sports.filter((s): s is 'swim' | 'bike' | 'run' => s === 'swim' || s === 'bike' || s === 'run').map((s) => [s, s[0]!.toUpperCase() + s.slice(1)] as const)}
                  onChange={(v) => setG({ limiters: v })} />
              </Field>
            )}
            <Field label="Anything else that matters?" hint="Optional: worries, priorities, why this race.">
              <textarea className={areaCls} value={g.priorities ?? ''} maxLength={600} onChange={(e) => setG({ priorities: e.target.value })}
                placeholder="e.g. First half Ironman, nervous about the swim" />
            </Field>
          </Card>
        </>
      )}

      {step === 'you' && (
        <>
          <StepIntro eyebrow="About you" title="Tell Rabbit about yourself">
            This sets how hard the plan ramps up. All of it is optional except your experience.
          </StepIntro>
          {me.garmin.connected && <GarminFill busy={busy} onClick={() => void fillFromGarmin()} />}
          {note && <p className="px-1 text-[0.7647rem] text-(--accent)">{note}</p>}
          <div className="flex flex-col gap-2">
            <OptionCard selected={a.level === 'new'} title="New to this" description="First race at this distance, or under a year of steady training." onClick={() => setA({ level: 'new' })} />
            <OptionCard selected={a.level === 'intermediate'} title="A few seasons in" description="You've done races like this and train most weeks." onClick={() => setA({ level: 'intermediate' })} />
            <OptionCard selected={a.level === 'advanced'} title="Experienced" description="Years of structured training; you handle big weeks." onClick={() => setA({ level: 'advanced' })} />
          </div>
          <Card>
            <Field label="Units">
              <Choice value={a.units ?? 'metric'} onChange={(v) => setA({ units: v ?? 'metric' })} options={[['metric', 'Metric'], ['imperial', 'Imperial']]} />
            </Field>
            <Field label="Sex" hint="Optional. Helps Rabbit read heart-rate and recovery data.">
              <Choice value={a.sex ?? null} allowNone onChange={(v) => setA({ sex: v })} options={[['female', 'Female'], ['male', 'Male'], ['other', 'Other']]} />
            </Field>
            <Field label="Age">
              <NumberStepper label="age" value={a.age} min={10} max={100} onChange={(v) => setA({ age: v })} suffix="years" />
            </Field>
            <Field label="Height">
              {imperial ? (
                <HeightImperial cm={a.height_cm ?? null} onChange={(cm) => setA({ height_cm: cm })} />
              ) : (
                <NumberStepper label="height" value={a.height_cm} min={100} max={250} onChange={(v) => setA({ height_cm: v })} suffix="cm" />
              )}
            </Field>
            <Field label="Weight">
              {imperial ? (
                <NumberStepper label="weight" value={a.weight_kg ? kgToLb(a.weight_kg) : null} min={66} max={550}
                  onChange={(v) => setA({ weight_kg: v == null ? null : lbToKg(v) })} suffix="lb" />
              ) : (
                <NumberStepper label="weight" value={a.weight_kg} min={30} max={250} step={0.5} decimals={1}
                  onChange={(v) => setA({ weight_kg: v })} suffix="kg" />
              )}
            </Field>
          </Card>
          <Card>
            <Field label="Injuries or limits" hint="Optional. Rabbit keeps these in mind in every brief.">
              <textarea className={areaCls} value={a.injuries ?? ''} maxLength={500} onChange={(e) => setA({ injuries: e.target.value })}
                placeholder="e.g. Achilles gets cranky above 40 km a week" />
            </Field>
          </Card>
        </>
      )}

      {step === 'numbers' && (
        <>
          <StepIntro eyebrow="Your numbers" title="Training zones">
            These set the targets on your watch. Skip any you don't know: workouts then use
            your Garmin heart-rate zones.
          </StepIntro>
          {me.garmin.connected && <GarminFill busy={busy} onClick={() => void fillFromGarmin()} />}
          {note && <p className="px-1 text-[0.7647rem] text-(--accent)">{note}</p>}
          <Card>
            <Field label="Resting heart rate">
              <NumberStepper label="resting heart rate" value={a.resting_hr} min={25} max={120} onChange={(v) => setA({ resting_hr: v })} suffix="bpm" />
            </Field>
            <Field label="Max heart rate">
              <NumberStepper label="max heart rate" value={a.max_hr} min={100} max={230} onChange={(v) => setA({ max_hr: v })} suffix="bpm" />
            </Field>
            <Field label="Threshold heart rate" hint="Roughly your average heart rate for an all-out hour.">
              <NumberStepper label="threshold heart rate" value={a.threshold_hr} min={80} max={220} onChange={(v) => setA({ threshold_hr: v })} suffix="bpm" />
            </Field>
          </Card>
          <Card>
            {sports.includes('bike') && (
              <Field label="Cycling FTP" hint={a.weight_kg && a.ftp_w ? `${(a.ftp_w / a.weight_kg).toFixed(1)} W/kg. Bike workouts target power.` : 'Bike workouts target power when you have a power meter.'}>
                <NumberStepper label="FTP" value={a.ftp_w} min={50} max={600} step={5} onChange={(v) => setA({ ftp_w: v })} suffix="watts" />
              </Field>
            )}
            {sports.includes('run') && (
              <Field label={`Threshold run pace (per ${imperial ? 'mile' : 'km'})`} hint="About your 10K-to-half-marathon race pace. Run workouts target pace.">
                <PaceInput seconds={a.run_threshold_pace == null ? null : imperial ? a.run_threshold_pace * KM_PER_MI : a.run_threshold_pace}
                  placeholder={imperial ? '7:15' : '4:30'}
                  onChange={(s) => setA({ run_threshold_pace: s == null ? null : Math.round(imperial ? s / KM_PER_MI : s) })} />
              </Field>
            )}
            {sports.includes('swim') && (
              <Field label="Swim CSS (per 100 m)" hint="Your sustainable pace for a hard 1500 m. Sets swim distances.">
                <PaceInput seconds={a.swim_css ?? null} placeholder="1:45" onChange={(s) => setA({ swim_css: s })} />
              </Field>
            )}
          </Card>
        </>
      )}

      {step === 'week' && (
        <>
          <StepIntro eyebrow="Your week" title="When can you train?">
            Rabbit starts close to what you do now and builds gradually from there.
          </StepIntro>
          <Card>
            <Field label="Hours a week right now" hint="Average of the last month. Garmin's history helps if you're unsure.">
              <NumberStepper label="hours per week" value={a.weekly_hours} min={1} max={30} step={0.5} decimals={1}
                onChange={(v) => setA({ weekly_hours: v })} suffix="hours" />
            </Field>
            <Field label="Training days" hint={(a.available_days ?? []).length < 3 ? 'Three or more days works best.' : `${(a.available_days ?? []).length} days a week. The rest are rest days.`}>
              <MultiChoice value={a.available_days ?? []} options={WEEKDAYS} onChange={(v) => setA({ available_days: v, long_day: v.includes(a.long_day ?? '') ? a.long_day : v[v.length - 1] ?? null })} />
            </Field>
            <Field label="Long-session day" hint={sports.includes('bike') && sports.includes('run') ? 'Your long ride (or brick). The long run goes the day after.' : 'Your longest session of the week.'}>
              <Choice value={a.long_day ?? null} onChange={(v) => setA({ long_day: v })}
                options={WEEKDAYS.filter(([d]) => (a.available_days ?? []).includes(d))} />
            </Field>
          </Card>
          <Card>
            <Field label="What do you have access to?" hint={sports.includes('swim') && !(a.equipment ?? []).some((e) => e === 'pool' || e === 'open_water') && (a.equipment ?? []).length ? 'No pool or open water selected, so Rabbit will leave out swims.' : 'Optional.'}>
              <MultiChoice value={(a.equipment ?? []) as typeof EQUIPMENT[number][0][]} options={EQUIPMENT} onChange={(v) => setA({ equipment: v })} />
            </Field>
          </Card>
        </>
      )}

      {step === 'review' && (
        <>
          <StepIntro eyebrow="Review" title="Ready to build">
            Check your answers. You can change anything later and rebuild.
          </StepIntro>
          <Card>
            <ReviewRow label="Race" onEdit={() => setStep('race')}
              value={[DISTANCES.find((d) => d.value === g.distance)?.label, g.event, g.date && new Date(`${g.date}T12:00:00`).toLocaleDateString([], { dateStyle: 'medium' }), g.priority && `${g.priority} race`].filter(Boolean).join(' · ')} />
            <ReviewRow label="Goal" onEdit={() => setStep('goal')}
              value={[g.goal_type === 'time' ? `Target ${g.target_time}` : g.goal_type === 'compete' ? 'Compete' : 'Finish strong',
                (g.limiters ?? []).length ? `Focus: ${(g.limiters ?? []).join(', ')}` : ''].filter(Boolean).join(' · ')} />
            <ReviewRow label="You" onEdit={() => setStep('you')}
              value={[levelLabel(a.level), a.age && `${a.age} yrs`, a.height_cm && (imperial ? `${cmToFtIn(a.height_cm).ft}'${cmToFtIn(a.height_cm).inch}"` : `${a.height_cm} cm`),
                a.weight_kg && (imperial ? `${kgToLb(a.weight_kg)} lb` : `${a.weight_kg} kg`)].filter(Boolean).join(' · ') || 'Not set'} />
            <ReviewRow label="Numbers" onEdit={() => setStep('numbers')}
              value={[a.threshold_hr && `LTHR ${a.threshold_hr}`, a.ftp_w && `FTP ${a.ftp_w} W`,
                a.run_threshold_pace && `Run ${fmtPace(imperial ? a.run_threshold_pace * KM_PER_MI : a.run_threshold_pace)}/${imperial ? 'mi' : 'km'}`,
                a.swim_css && `CSS ${fmtPace(a.swim_css)}/100m`].filter(Boolean).join(' · ') || 'Heart-rate zones from Garmin'} />
            <ReviewRow label="Week" onEdit={() => setStep('week')}
              value={`${a.weekly_hours ?? '?'} h now · ${(a.available_days ?? []).map((d) => d[0]!.toUpperCase() + d.slice(1)).join(', ')} · long day ${a.long_day ?? '?'}`} />
          </Card>
          <Card>
            <Field label="Start the plan on" hint="Usually today. Week 1 runs to the end of this week.">
              <input type="date" className={inputCls} value={draft.start_date} min={todayIso()} max={g.date ?? undefined}
                onChange={(e) => setDraft((d) => ({ ...d, start_date: e.target.value || todayIso() }))} />
            </Field>
          </Card>
          {me.goal?.plan && !draft.newGoal && (
            <p className="px-1 text-[0.7647rem] text-(--warning)">This replaces the current plan for {me.goal.title}. Workouts already synced to Garmin get cleaned up on the next sync.</p>
          )}
        </>
      )}

      {step === 'done' && plan && (
        <>
          <div className="flex flex-col items-center px-2 pt-2 text-center">
            <span className="mb-3 flex size-12 items-center justify-center rounded-full bg-(--accent) text-white"><Check className="size-6" strokeWidth={3} /></span>
            <h3 className="font-display text-[1.5294rem] leading-tight text-(--brand)">Your plan is ready</h3>
            <p className="mt-1.5 text-[0.8235rem] text-(--text-secondary)">
              {plan.weeks.length} weeks to {g.title || 'race day'}, building from about {plan.start_hours} to {plan.peak_hours} hours a week.
            </p>
            {plan.note && <p className="mt-1.5 text-[0.7647rem] text-(--text-muted)">{plan.note}</p>}
          </div>
          <Card className="p-4"><PhaseStrip plan={plan} /></Card>
          <WeekPreview week={plan.weeks.find((w) => w.index === plan.current_week) ?? plan.weeks[0]!} />

          <Card>
            <Field label="Put it on your watch" hint="Rabbit adds upcoming sessions to your Garmin calendar as structured workouts. Re-sync anytime from the plan.">
              {me.garmin.connected ? (
                <div className="flex flex-col gap-2.5">
                  <ChipRow>
                    {[7, 14, 28].map((d) => <Chip key={d} selected={sync.days === d} onClick={() => setSync((s) => ({ ...s, days: d }))}>Next {d} days</Chip>)}
                  </ChipRow>
                  <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" loading={sync.busy} onClick={() => void doSync()}>
                    <Watch className="size-4" /> {sync.result ? 'Sync again' : 'Sync to Garmin'}
                  </Button>
                  {sync.result && <SyncSummary result={sync.result} />}
                  {sync.error && <p className="text-[0.7647rem] text-(--danger)">{sync.error}</p>}
                </div>
              ) : me.garmin.can_connect ? (
                <ConnectGarmin cooldownUntil={me.garmin.cooldown_until} onConnected={onMeChanged} />
              ) : <p className="text-[0.7647rem] text-(--text-muted)">Garmin isn't available on this server.</p>}
            </Field>
          </Card>
        </>
      )}

      {error && <p className="px-1 text-[0.7647rem] text-(--danger)" role="alert">{error}</p>}
      {showProgress && step !== 'review' && sports.length > 0 && g.distance && (
        <div className="flex justify-center gap-1.5 pt-1 text-(--text-muted)" aria-hidden>
          {sports.map((s) => { const I = SPORT_ICON[s]; return I ? <I key={s} className="size-3.5" /> : null })}
        </div>
      )}
    </Screen>
  )
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

function GarminFill({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={busy}
      className="flex items-center gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-2.5 text-left disabled:opacity-60">
      <Watch className="size-4 shrink-0 text-(--accent)" />
      <span className="min-w-0 flex-1 text-[0.8235rem] text-(--accent)">{busy ? 'Asking Garmin…' : 'Fill in from Garmin'}</span>
    </button>
  )
}

function ReviewRow({ label, value, onEdit }: { label: string; value: string; onEdit: () => void }) {
  return (
    <button type="button" onClick={onEdit} className="flex w-full items-start gap-3 px-4 py-3 text-left active:bg-(--bg-inset)">
      <span className="w-[72px] shrink-0 pt-0.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</span>
      <span className="min-w-0 flex-1 text-[0.8235rem] leading-snug text-(--text)">{value}</span>
      <span className="text-[0.7059rem] text-(--accent)">Edit</span>
    </button>
  )
}

function HeightImperial({ cm, onChange }: { cm: number | null; onChange: (cm: number | null) => void }) {
  const { ft, inch } = cm ? cmToFtIn(cm) : { ft: 5, inch: 9 }
  return (
    <div className="flex gap-3">
      <div className="flex-1"><NumberStepper label="feet" value={cm ? ft : null} min={3} max={8} onChange={(v) => onChange(v == null ? null : ftInToCm(v, inch))} suffix="ft" /></div>
      <div className="flex-1"><NumberStepper label="inches" value={cm ? inch : null} min={0} max={11} onChange={(v) => onChange(v == null ? null : ftInToCm(ft, v))} suffix="in" /></div>
    </div>
  )
}

function PaceInput({ seconds, onChange, placeholder }: { seconds: number | null; onChange: (s: number | null) => void; placeholder: string }) {
  const [text, setText] = useState(seconds != null ? fmtPace(seconds) : '')
  const [bad, setBad] = useState(false)
  useEffect(() => { setText(seconds != null ? fmtPace(seconds) : '') }, [seconds])
  return (
    <div className="flex flex-col gap-1">
      <input className={inputCls} inputMode="numeric" placeholder={placeholder} value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          if (!text.trim()) { setBad(false); onChange(null); return }
          const s = parsePace(text)
          setBad(s == null)
          if (s != null) onChange(s)
        }} />
      {bad && <span className="text-[0.7059rem] text-(--danger)">Use minutes:seconds, like {placeholder}.</span>}
    </div>
  )
}

export function SyncSummary({ result }: { result: SyncResult }) {
  const parts = [
    result.uploaded && `${result.uploaded} added`,
    result.unchanged && `${result.unchanged} already there`,
    result.removed && `${result.removed} removed`,
  ].filter(Boolean)
  return (
    <div className="flex flex-col gap-1 text-[0.7647rem]">
      <p className="text-(--accent)">{parts.length ? `${parts.join(', ')}.` : 'Nothing to sync in that window.'} Open Garmin Connect and sync your watch to see them.</p>
      {result.errors.map((e, i) => (
        <p key={i} className="text-(--danger)">{e.title}{e.date ? ` (${e.date})` : ''}: {e.error}</p>
      ))}
    </div>
  )
}
