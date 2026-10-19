// The Day view's exact workout (server: workouttargets.py via the plan calendar): a summary
// (time, distance, average target pace and heart rate, training stress, time per zone), then one
// compact row per step with its targets as chips (heart rate, pace / power / swim pace, cadence);
// tap a row for effort out of 10 and the talk test. Also "How it went" for a finished workout
// and the one-tap "new paces" nudge.
import { RabbitInline } from '@/components/chat/RabbitText'
import { useEffect, useState } from 'react'
import { Check, ChevronDown, Gauge, HeartPulse, Footprints, RotateCw, Timer, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { fmtDist, fmtDuration } from '@/lib/format'
import { ZONE_LABEL, fmtMin } from '@/lib/plan'
import { acceptPace, dismissPace, getPaces, type PaceSuggestion } from '@/lib/paces'
import type { TargetBlock, TargetStep, Targets, Went } from '@/lib/plancal'
import { paceText } from './PlanCalendar'

const ZONE_TONE: Record<number, string> = {
  1: 'bg-(--bg-elevated)', 2: 'bg-(--accent)/35', 3: 'bg-(--accent)/60', 4: 'bg-(--accent)/85', 5: 'bg-(--brand)',
}
const SPORT_NAME: Record<string, string> = { bike: 'Bike', run: 'Run' }

const swimText = (secPer100m: number, imperial: boolean) => {
  const s = Math.round(secPer100m * (imperial ? 0.9144 : 1))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
const range = (a: string, b: string) => (a === b ? a : `${a}–${b}`)

function Chip({ icon: Icon, children, label }: { icon: typeof Zap; children: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-(--bg-inset) px-1.5 py-0.5 font-mono text-meta tabular-nums text-(--text)" aria-label={label}>
      <Icon className="size-3.5 text-(--text-muted)" aria-hidden />{children}
    </span>
  )
}

function amount(st: TargetStep) {
  return st.meters ? `${st.meters} m` : st.minutes ? fmtMin(st.minutes) : ''
}

function StepRow({ st, imperial }: { st: TargetStep; imperial: boolean }) {
  const [open, setOpen] = useState(false)
  const u = imperial ? 'mi' : 'km'
  const chips: React.ReactNode[] = []
  if (st.hr) chips.push(<Chip key="hr" icon={HeartPulse} label={`Heart rate ${st.hr[0]} to ${st.hr[1]} beats per minute`}>{range(String(st.hr[0]), String(st.hr[1]))} bpm</Chip>)
  if (st.pace) chips.push(<Chip key="p" icon={Timer} label={`Pace ${paceText(st.pace[0], imperial)} to ${paceText(st.pace[1], imperial)} per ${u}`}>{range(paceText(st.pace[0], imperial), paceText(st.pace[1], imperial))}/{u}</Chip>)
  if (st.power) chips.push(<Chip key="w" icon={Zap} label={`Power ${st.power[0]} to ${st.power[1]} watts`}>{st.power[0]}–{st.power[1]} W</Chip>)
  if (st.swim) chips.push(<Chip key="s" icon={Timer} label={`Swim pace ${swimText(st.swim[0], imperial)} to ${swimText(st.swim[1], imperial)} per 100 ${imperial ? 'yards' : 'meters'}`}>{range(swimText(st.swim[0], imperial), swimText(st.swim[1], imperial))}/100{imperial ? 'yd' : 'm'}</Chip>)
  const steps = !!st.cadence && st.cadence[0] >= 120  // running cadence (spm) vs pedalling (rpm)
  if (st.cadence) chips.push(<Chip key="c" icon={steps ? Footprints : RotateCw} label={`Cadence ${st.cadence[0]} to ${st.cadence[1]} ${steps ? 'steps' : 'pedal turns'} per minute`}>{st.cadence[0]}–{st.cadence[1]}{steps ? ' spm' : ' rpm'}</Chip>)
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-start gap-2.5 py-1.5 text-left">
        <span className={cn('mt-0.5 w-1 shrink-0 self-stretch rounded-full', ZONE_TONE[st.zone])} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-1.5">
            <span className="text-body font-semibold tabular-nums text-(--text)">{amount(st)}</span>
            <span className="text-body text-(--text)">{st.type === 'work' || st.type === 'steady' ? ZONE_LABEL[st.zone] : st.label}</span>
            <span className="ml-auto shrink-0 font-mono text-caption text-(--text-muted)">Z{st.zone}</span>
          </span>
          {chips.length > 0 && <span className="mt-1 flex flex-wrap gap-1">{chips}</span>}
          {open && (
            <span className="mt-1.5 block text-meta leading-snug text-(--text-secondary)">
              Effort {st.rpe} out of 10 · Talk test: {st.talk.toLowerCase()}.
              {st.cadence && (st.cadence[0] >= 120 ? ' Cadence is steps per minute, both feet.' : ' Cadence is pedal turns per minute.')}
            </span>
          )}
        </span>
        <ChevronDown className={cn('mt-1 size-4 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
    </li>
  )
}

function Blocks({ blocks, imperial }: { blocks: TargetBlock[]; imperial: boolean }) {
  return (
    <ol className="flex flex-col">
      {blocks.map((b, i) => b.type === 'repeat' ? (
        <li key={i} className="my-1 rounded-lg border border-(--border) px-2.5 py-1">
          <span className="text-caption font-semibold text-(--accent)">Repeat {b.reps} times</span>
          <Blocks blocks={b.steps} imperial={imperial} />
        </li>
      ) : <StepRow key={i} st={b} imperial={imperial} />)}
    </ol>
  )
}

/** Time per zone as one bar, with a legend. */
function ZoneBar({ zones }: { zones: Record<string, number> }) {
  const total = Object.values(zones).reduce((a, b) => a + b, 0)
  if (!total) return null
  const items = Object.entries(zones).map(([z, m]) => [Number(z), m] as const)
  return (
    <div className="flex flex-col gap-1" role="img" aria-label={`Time in zones: ${items.map(([z, m]) => `zone ${z} ${m} minutes`).join(', ')}`}>
      <div className="flex h-2 overflow-hidden rounded-full bg-(--bg-inset)" aria-hidden>
        {items.map(([z, m]) => <span key={z} className={ZONE_TONE[z]} style={{ width: `${(m / total) * 100}%` }} />)}
      </div>
      <div className="flex flex-wrap gap-x-3 text-caption text-(--text-muted)" aria-hidden>
        {items.map(([z, m]) => <span key={z}>Z{z} {ZONE_LABEL[z]?.toLowerCase()} {m}′</span>)}
      </div>
    </div>
  )
}

export function WorkoutSummary({ t, dist, imperial }: { t: Targets; dist: string; imperial: boolean }) {
  const s = t.summary
  const cells = ([
    ['Time', s.minutes ? fmtDuration(s.minutes) : ''],
    ['Distance', dist],
    ['Avg pace', s.run_pace ? `${paceText(s.run_pace, imperial)}/${imperial ? 'mi' : 'km'}` : ''],
    ['Avg HR', s.avg_hr ? `${s.avg_hr} bpm` : ''],
    ['Load', s.stress ? String(s.stress) : ''],
  ] as const).filter(([, v]) => !!v)
  return (
    <div className="mx-3.5 mt-3 flex flex-col gap-2 rounded-lg bg-(--bg-inset) px-3 py-2">
      <dl className="grid grid-cols-2 gap-x-3 min-[400px]:grid-cols-3 gap-y-1.5">
        {cells.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-caption text-(--text-muted) font-semibold">{k}</dt>
            <dd className="font-mono text-body font-semibold leading-tight tabular-nums text-(--text) [overflow-wrap:anywhere]">{v}</dd>
          </div>
        ))}
      </dl>
      <ZoneBar zones={s.zones} />
    </div>
  )
}

export function WorkoutSteps({ t, imperial }: { t: Targets; imperial: boolean }) {
  const groups = t.legs ? t.legs.map((l) => ({ label: SPORT_NAME[l.sport], steps: l.steps })) : [{ label: undefined, steps: t.steps ?? [] }]
  return (
    <div className="mx-3.5 mt-3 flex flex-col gap-1">
      <p className="text-caption font-semibold text-(--text-muted)">The workout · tap a step for effort</p>
      {groups.map((g, i) => (
        <div key={i} className="flex flex-col">
          {g.label && <span className="mt-1 text-meta font-semibold text-(--text-secondary)">{g.label}</span>}
          <Blocks blocks={g.steps} imperial={imperial} />
        </div>
      ))}
      {t.hr_source === 'estimated' && (
        <p className="text-meta leading-snug text-(--text-muted)">
          Heart-rate targets are estimated from the highest heart rate in your recent workouts. Add your max or threshold heart rate in Me › Profile for exact zones.
        </p>
      )}
      {t.hr_source === null && (
        <p className="text-meta leading-snug text-(--text-muted)">
          Add your max heart rate in Me › Profile to see heart-rate targets in beats per minute.
        </p>
      )}
    </div>
  )
}

const WENT_TONE: Record<Went['verdict'], string> = {
  hit: 'bg-(--accent-subtle) text-(--accent)', done: 'bg-(--accent-subtle) text-(--accent)',
  long: 'bg-(--accent-subtle) text-(--accent)', slow: 'bg-(--bg-inset) text-(--text-secondary)',
  short: 'bg-(--warning)/15 text-(--warning-text)', hard: 'bg-(--warning)/15 text-(--warning-text)',
  fast: 'bg-(--warning)/15 text-(--warning-text)',
}

export function HowItWent({ w, imperial, sport }: { w: Went; imperial: boolean; sport: string }) {
  const a = w.actual
  const facts = [
    a.km != null ? fmtDist(a.km, imperial, sport === 'swim' ? 'swim' : sport === 'bike' ? 'bike' : 'run') : '',
    a.minutes != null ? fmtDuration(a.minutes) : '',
    a.pace ? `${paceText(a.pace, imperial)}/${imperial ? 'mi' : 'km'}` : '',
    a.avg_hr ? `${Math.round(a.avg_hr)} bpm` : '',
    a.cadence ? `${Math.round(a.cadence)} ${sport === 'run' ? 'spm' : 'rpm'}` : '',
    a.power ? `${Math.round(a.power)} W` : '',
  ].filter(Boolean)
  return (
    <div className="mx-3.5 mt-3 flex flex-col gap-1.5 rounded-lg border border-(--border) px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-caption font-semibold text-(--text-muted)">How it went</span>
        <span className={cn('ml-auto rounded-full px-2 py-0.5 text-caption font-semibold', WENT_TONE[w.verdict])}>{w.headline}</span>
      </div>
      {facts.length > 0 && <p className="font-mono text-small tabular-nums text-(--text)">{facts.join(' · ')}</p>}
      {w.lines.length > 0 && (
        <div className="flex flex-col gap-0.5 text-small leading-normal text-(--text-secondary)">
          {w.lines.map((l) => <p key={l} className="m-0"><RabbitInline text={l} /></p>)}
        </div>
      )}
    </div>
  )
}

/** Rabbit spotted new training paces: show the one-tap update right in the Day view. */
export function PaceNudge({ sports }: { sports: string[] }) {
  const [sug, setSug] = useState<PaceSuggestion | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const key = sports.join(',')
  useEffect(() => {
    let live = true
    getPaces().then((v) => { if (live) setSug(v.pending.find((p) => key.split(',').includes(p.sport)) ?? null) }, () => {})
    return () => { live = false }
  }, [key])
  if (done) return <p className="flex items-center gap-1.5 px-2 text-small text-(--accent)" role="status"><Check className="size-4" aria-hidden />{done}</p>
  if (!sug) return null
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3.5 py-3" role="status">
      <p className="flex items-start gap-2 text-small leading-snug text-(--text)">
        <Gauge className="mt-0.5 size-5 shrink-0 text-(--accent)" aria-hidden />
        <span><span className="font-semibold">You're getting fitter.</span> {sug.headline}</span>
      </p>
      <div className="flex gap-2">
        <Button variant="primary" className="h-11 px-4 text-small" loading={busy}
          onClick={() => { setBusy(true); acceptPace(sug.id).then((r) => setDone(`${r.summary} Your upcoming targets now use it.`), () => setBusy(false)) }}>
          Update my targets
        </Button>
        <Button variant="ghost" className="h-11 px-3 text-small" onClick={() => { void dismissPace(sug.id).catch(() => {}); setSug(null) }}>Not now</Button>
      </div>
    </div>
  )
}
