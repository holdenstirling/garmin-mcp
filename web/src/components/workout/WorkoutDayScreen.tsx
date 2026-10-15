// "Ready to go": today's session before you head out (server: workoutday.py). Hero, why it
// matters, the step-by-step with targets as big chips, the key cue, fueling, gear, weather,
// watch status and a pre-run checklist ticked per day on this device.
import { useCallback, useEffect, useState } from 'react'
import {
  Activity, Bike, Check, CloudSun, Compass, Dumbbell, Footprints, Layers, Lightbulb, MessageCircle, Moon, Repeat, Utensils, Watch, Waves, Wind,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Field, Screen } from '@/components/plan/ui'
import { fmtDay } from '@/components/plan/PlanParts'
import { KIND_LABEL, fmtMin, syncGarmin } from '@/lib/plan'
import { fmtDist, fmtDuration, fmtMeters, fmtSpeed } from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  CHECKLIST, fmtTemp, getWorkoutToday, readChecklist, writeChecklist,
  type CheckInRequest, type Target, type Weather, type WorkoutSession, type WorkoutToday, type WSection, type WStep,
} from '@/lib/workout'
import { GarminEmpty } from '@/components/garmin/GarminEmpty'

const ICON: Record<string, typeof Bike> = {
  swim: Waves, bike: Bike, run: Footprints, brick: Layers, strength: Dumbbell, rest: Moon, other: Activity,
}
const LOADING = ['Lacing up…', 'Loading your targets…', 'Checking the sky…', 'Stretching the hamstrings…']

export function WorkoutDayScreen({ sessionId, imperial, onClose, onAsk, onCheckIn }: {
  sessionId?: string
  imperial: boolean
  onClose: () => void
  onAsk?: (text: string) => void
  onCheckIn?: (p: CheckInRequest) => void
}) {
  const [sid, setSid] = useState<string | undefined>(sessionId)
  const [data, setData] = useState<WorkoutToday | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const load = useCallback(() => {
    setError(null)
    getWorkoutToday(sid).then(setData, (e: Error) => setError(e.message))
  }, [sid])
  useEffect(() => { load() }, [load])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  const s = data?.state === 'session' ? data.session : null
  const title = s ? s.title : data?.state === 'rest' ? 'Rest day' : data?.state === 'free' ? 'Free day' : 'Today'
  const sub = data ? (data.date === data.today ? 'Ready to go' : fmtDay(data.date, { weekday: 'long', month: 'short', day: 'numeric' })) : undefined

  return (
    <Screen title={title} subtitle={sub} onClose={close} closing={closing}
      footer={s && (onAsk || onCheckIn) ? (
        <>
          {onAsk && (
            <Button variant="default" className="h-11 flex-1 gap-1.5 text-[0.8235rem]"
              onClick={() => onAsk(`About ${data?.date === data?.today ? "today's" : 'my'} ${s.title}: `)}>
              <MessageCircle className="size-4" /> Ask Rabbit
            </Button>
          )}
          {onCheckIn && s.status === 'done' && (
            <Button variant="primary" className="h-11 flex-1 text-[0.8235rem]"
              onClick={() => onCheckIn({ sessionId: s.id ?? undefined, activityId: s.activity?.id ?? undefined, title: s.title })}>
              How did it feel?
            </Button>
          )}
        </>
      ) : undefined}>
      {!data && !error && <RabbitLoader className="py-16" label="Loading today's workout" cycle={LOADING} />}
      {error && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <p className="text-[0.8235rem] text-(--text-muted)">{error}</p>
          <Button variant="default" onClick={load}>Try again</Button>
        </div>
      )}
      {data && data.others.length > 1 && (
        <div className="no-scrollbar -mb-2 flex gap-2 overflow-x-auto" role="tablist" aria-label="Today's sessions">
          {data.others.map((o) => {
            const on = !!s && o.id === s.id
            const I = ICON[o.sport] ?? Activity
            return (
              <button key={o.id ?? o.title} type="button" role="tab" aria-selected={on} disabled={!o.id}
                onClick={() => o.id && setSid(o.id)} className={cn('plan-chip shrink-0 gap-1.5', on && 'plan-chip--on')}>
                <I className="size-3.5" />{o.title}{o.status === 'done' && <Check className="size-3.5" />}
              </button>
            )
          })}
        </div>
      )}
      {data && s && <SessionBody d={data} s={s} imperial={imperial} onSynced={load} />}
      {data?.state === 'rest' && (
        <Hero icon={Moon} title="Rest day" meta="Recovery is training too"
          line="Sleep, eat well, maybe an easy walk. Your next session will feel better for it." />
      )}
      {data?.state === 'free' && (
        <>
          <Hero icon={Compass} title={data.has_plan ? 'Nothing planned today' : 'Your call today'} meta="30-45 min · easy"
            line={data.free.purpose} />
          <TargetChips targets={data.free.main_targets} />
          <CueCard cue={data.free.cue} />
          {data.weather && <WeatherChip w={data.weather} imperial={imperial} />}
          <Checklist day={data.today} sport="other" />
        </>
      )}
    </Screen>
  )
}

function Hero({ icon: Icon, title, meta, line, done }: { icon: typeof Bike; title: string; meta: string; line: string; done?: boolean }) {
  return (
    <div className="celebrate flex flex-col gap-3 rounded-2xl border border-(--accent)/25 bg-(--accent-subtle) px-4 py-4">
      <div className="flex items-center gap-3">
        <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)">
          <Icon className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[1.4118rem] leading-tight text-(--brand)">{title}</h3>
          <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">{meta}</p>
        </div>
        {done && (
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-(--accent) px-2 py-1 text-[0.6471rem] font-semibold text-(--on-fill)">
            <Check className="size-3.5" strokeWidth={3} /> Done
          </span>
        )}
      </div>
      <p className="text-[0.8824rem] leading-snug text-(--text)">{line}</p>
    </div>
  )
}

function SessionBody({ d, s, imperial, onSynced }: { d: WorkoutToday; s: WorkoutSession; imperial: boolean; onSynced: () => void }) {
  const meta = [s.minutes ? fmtDuration(s.minutes) : null, s.meters ? (s.sport === 'swim' ? fmtMeters(s.meters, imperial) : fmtDist(s.meters / 1000, imperial)) : null, s.kind ? KIND_LABEL[s.kind] ?? s.kind : null]
    .filter(Boolean).join(' · ')
  return (
    <>
      <Hero icon={ICON[s.sport] ?? Activity} title={s.title} meta={meta || 'Today'} line={s.purpose} done={s.status === 'done'} />
      {d.readiness && (
        <p className={cn('rounded-xl border px-3 py-2 text-[0.7647rem] leading-snug',
          d.readiness.tone === 'easy' || d.readiness.tone === 'rest'
            ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)'
            : 'border-(--border) bg-(--bg-surface) text-(--text-secondary)')}>
          {d.readiness.line}
        </p>
      )}
      {s.main_targets.length > 0 && <TargetChips targets={s.main_targets} label="Main target" />}
      {s.sections.length > 0 && <Timeline sections={s.sections} />}
      {s.sections.length === 0 && s.detail && <Card><Field label="The workout"><p className="text-[0.8235rem] text-(--text)">{s.detail}</p></Field></Card>}
      {s.exercises.length > 0 && (
        <Card>
          <Field label="Exercises">
            <ul className="flex flex-col gap-1.5">
              {[...s.exercises, ...s.prehab].map((e) => (
                <li key={e.name} className="flex gap-2 text-[0.8235rem]"><span className="flex-1 text-(--text)">{e.name}</span><span className="text-(--text-muted)">{e.dose}</span></li>
              ))}
            </ul>
          </Field>
        </Card>
      )}
      <CueCard cue={s.cue} />
      <FuelCard s={s} />
      {(s.gear.length > 0 || d.weather) && (
        <div className="flex flex-col gap-2">
          {s.gear.map((g) => (
            <div key={g.id} className={cn('flex items-center gap-3 rounded-xl border px-3 py-2.5',
              g.warning ? 'border-(--warning)/30 bg-(--warning-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
              {g.kind === 'bike' ? <Bike className="size-4 shrink-0 text-(--accent)" /> : <Footprints className="size-4 shrink-0 text-(--accent)" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8235rem] font-medium text-(--text)">{g.name}</span>
                <span className={cn('block text-[0.6471rem]', g.warning ? 'text-(--warning-text)' : 'text-(--text-muted)')}>
                  {g.warning ?? `${g.total_label} so far`}
                </span>
              </span>
            </div>
          ))}
          {d.weather && <WeatherChip w={d.weather} imperial={imperial} />}
        </div>
      )}
      {s.id && s.garmin.syncable && (d.garmin_connected === false
        ? <GarminEmpty what="workout" compact />
        : <WatchRow s={s} onSynced={onSynced} />)}
      {s.status !== 'done' && d.date === d.today && <Checklist day={d.today} sport={s.sport} />}
    </>
  )
}

function TargetChips({ targets, label }: { targets: Target[]; label?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <span className="px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</span>}
      <div className="flex flex-wrap gap-2">
        {targets.map((t) => <BigChip key={t.kind + t.label} t={t} />)}
      </div>
    </div>
  )
}

function BigChip({ t, small }: { t: Target; small?: boolean }) {
  return (
    <span className={cn('inline-flex items-baseline gap-1 rounded-lg font-display leading-none',
      t.kind === 'hr' ? 'bg-(--bg-elevated) text-(--text)' : 'bg-(--accent-subtle) text-(--accent)',
      small ? 'px-2 py-1 text-[0.9412rem]' : 'px-3 py-2 text-[1.2941rem]')}>
      {t.label}
    </span>
  )
}

function Timeline({ sections }: { sections: WSection[] }) {
  return (
    <ol className="flex flex-col gap-3" aria-label="Workout steps">
      {sections.map((sec, i) => (
        <li key={i} className="relative flex gap-3">
          <span className="flex flex-col items-center">
            <span className={cn('mt-1 size-3 shrink-0 rounded-full border-2',
              sec.kind === 'main' ? 'border-(--accent) bg-(--accent)' : 'border-(--accent) bg-(--bg)')} />
            {i < sections.length - 1 && <span className="mt-1 w-0.5 flex-1 rounded-full bg-(--accent)/25" />}
          </span>
          <div className="min-w-0 flex-1 pb-1">
            <p className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">{sec.name}</span>
              <span className="text-[0.7059rem] text-(--text-muted)">{Number.isInteger(sec.minutes) ? fmtDuration(sec.minutes) : fmtMin(sec.minutes)}</span>
            </p>
            <div className="mt-1.5 flex flex-col gap-2">{sec.steps.map((st, j) => <StepRow key={j} s={st} />)}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}

function StepRow({ s }: { s: WStep }) {
  if (s.type === 'repeat') {
    return (
      <div className="rounded-xl border border-(--accent)/30 px-3 py-2.5">
        <span className="flex items-center gap-1.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--accent)">
          <Repeat className="size-3.5" /> {s.reps} times
        </span>
        <div className="mt-2 flex flex-col gap-2">{s.steps.map((x, i) => <StepRow key={i} s={x} />)}</div>
      </div>
    )
  }
  const hard = s.type === 'work'
  return (
    <div className={cn('flex flex-col gap-1.5 rounded-xl border px-3 py-2.5',
      hard ? 'border-(--accent)/40 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <p className="flex items-baseline gap-2">
        <span className="font-display text-[1.1765rem] leading-none text-(--text)">{s.amount}</span>
        <span className="text-[0.7647rem] text-(--text-secondary)">{s.label}</span>
        <span className="ml-auto text-[0.6471rem] text-(--text-muted)">Z{s.zone} {s.zone_name}</span>
      </p>
      <div className="flex flex-wrap gap-1.5">{s.targets.map((t) => <BigChip key={t.kind + t.label} t={t} small />)}</div>
    </div>
  )
}

function CueCard({ cue }: { cue: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-(--brand)/20 bg-(--bg-surface) px-3 py-2.5">
      <Lightbulb className="mt-0.5 size-4 shrink-0 text-(--brand)" />
      <p className="text-[0.8235rem] leading-snug text-(--text)"><b className="font-semibold">Key cue:</b> {cue}</p>
    </div>
  )
}

function FuelCard({ s }: { s: WorkoutSession }) {
  if (s.sport === 'rest' || s.sport === 'strength') return null
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5">
      <Utensils className="mt-0.5 size-4 shrink-0 text-(--accent)" />
      {s.fuel ? (
        <div className="min-w-0 flex-1">
          <p className="text-[0.8235rem] text-(--text)">
            <b className="font-display text-[1.05rem]">{s.fuel.carbs_g_per_h} g</b> carbs/h
            {s.fuel.total_carbs_g != null && <span className="text-(--text-muted)"> · ≈{s.fuel.total_carbs_g} g total</span>}
            {s.fuel.fluid_ml_per_h && <span className="text-(--text-muted)"> · {s.fuel.fluid_ml_per_h} ml/h</span>}
          </p>
          <p className="text-[0.7059rem] leading-snug text-(--text-muted)">{s.fuel.note}</p>
        </div>
      ) : (
        <p className="text-[0.8235rem] text-(--text-secondary)">Water is enough for this one. Eat normally beforehand.</p>
      )}
    </div>
  )
}

function WeatherChip({ w, imperial }: { w: Weather; imperial: boolean }) {
  const wind = w.wind_kmh != null ? fmtSpeed(w.wind_kmh, imperial) : null
  return (
    <div className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3 py-2.5">
      <CloudSun className="size-4 shrink-0 text-(--accent)" />
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8235rem] text-(--text)">
          <b className="font-semibold">{fmtTemp(w.temp_c, imperial)}</b> {w.summary}
          {w.feels_c != null && w.temp_c != null && Math.abs(w.feels_c - w.temp_c) >= 3 && <span className="text-(--text-muted)"> · feels {fmtTemp(w.feels_c, imperial)}</span>}
        </span>
        <span className="block truncate text-[0.6471rem] text-(--text-muted)">
          {w.place}{w.rain_pct != null && w.rain_pct >= 20 ? ` · ${w.rain_pct}% rain next 3 h` : ''}
          {w.next.length > 0 && ` · ${w.next.map((h) => `${h.time} ${fmtTemp(h.temp_c, imperial)}`).join(', ')}`}
        </span>
      </span>
      {wind && <span className="flex shrink-0 items-center gap-1 text-[0.6471rem] text-(--text-muted)"><Wind className="size-3.5" />{wind}</span>}
    </div>
  )
}

function WatchRow({ s, onSynced }: { s: WorkoutSession; onSynced: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (s.garmin.on_watch) {
    return (
      <p className="flex items-center gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-3 py-2.5 text-[0.8235rem] font-medium text-(--accent)">
        <Watch className="size-4" /> On your watch <Check className="size-4" strokeWidth={3} />
      </p>
    )
  }
  const send = async () => {
    setBusy(true); setErr(null)
    try { await syncGarmin(7); onSynced() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Button variant="primary" className="h-11 gap-1.5 text-[0.8235rem]" loading={busy} onClick={() => void send()}>
        <Watch className="size-4" /> Send to watch
      </Button>
      <p className="px-1 text-[0.6471rem] text-(--text-muted)">{err ?? 'Sends this week\'s plan to Garmin. Sync your watch to pick it up.'}</p>
    </div>
  )
}

function Checklist({ day, sport }: { day: string; sport: string }) {
  const items = CHECKLIST[sport] ?? CHECKLIST.other!
  const [done, setDone] = useState<number[]>(() => readChecklist(day))
  const toggle = (i: number) => setDone((d) => {
    const next = d.includes(i) ? d.filter((x) => x !== i) : [...d, i]
    writeChecklist(day, next)
    return next
  })
  const all = done.length >= items.length
  return (
    <Card>
      <Field label={sport === 'swim' ? 'Pre-swim checklist' : sport === 'bike' ? 'Pre-ride checklist' : 'Pre-run checklist'}
        hint={all ? "All set. Go get it!" : undefined}>
        <ul className="flex flex-col gap-1">
          {items.map((t, i) => {
            const on = done.includes(i)
            return (
              <li key={t}>
                <button type="button" onClick={() => toggle(i)} aria-pressed={on}
                  className="flex w-full items-center gap-2.5 rounded-lg py-1.5 text-left active:opacity-70">
                  <span className={cn('flex size-5 shrink-0 items-center justify-center rounded-md border transition-colors',
                    on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border)')}>
                    {on && <Check className="size-3.5" strokeWidth={3} />}
                  </span>
                  <span className={cn('text-[0.8235rem]', on ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{t}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </Field>
    </Card>
  )
}
