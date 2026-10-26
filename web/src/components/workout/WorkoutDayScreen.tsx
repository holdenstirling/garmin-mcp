// The workout page: one full-screen view for ANY plan session, past, today or ahead (server:
// workoutday.py for the day, plancal.py for exact targets and how it went). Opened from
// everywhere with lib/workoutnav openWorkout(id, date). Top to bottom: hero (date, start time,
// status), key numbers, every step with its targets (zone, heart rate, pace / watts / swim pace,
// cadence, effort, talk test), why and how, fueling, gear, weather (today), learn more, how it
// went (done), what to do about a miss, and feedback: the athlete's RPE / feel / pain / note
// plus Rabbit's take (deterministic first, then "Ask Rabbit for more"). Actions stay pinned at
// the bottom: Move, Edit, Ask Rabbit.
import { smooth } from '@/lib/scrollMotion'
import { ExerciseList } from '@/components/plan/ExerciseList'
import { RabbitInline } from '@/components/chat/RabbitText'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Bike, BookOpen, CalendarClock, Check, ChevronDown, Clock, CloudSun, Compass, Footprints, Lightbulb, MessageCircle, Moon, Pencil, Repeat, TriangleAlert, Utensils, Watch, Wind, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { shareToFriends } from '@/lib/dm'
import { ShareButton } from '@/components/ui/ShareSheet'
import { RabbitNote } from '@/components/ui/brand'
import { FuelLog, wantsFuelLog } from '@/components/body/FuelLog'
import { openBody } from '@/lib/body'
import { celebrate } from '@/components/fx'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Field, Screen } from '@/components/plan/ui'
import { fmtDay } from '@/components/plan/PlanParts'
import { HowItWent, WorkoutSteps, WorkoutSummary } from '@/components/plan/WorkoutTargets'
import { MoveSessionSheet } from '@/components/plan/MoveSheet'
import { KIND_LABEL, fmtMin, syncGarmin } from '@/lib/plan'
import { fmtDist, fmtDuration, fmtMeters, fmtSpeed } from '@/lib/format'
import { KIND_GLOSSARY, ZONE_GLOSSARY } from '@/lib/glossary'
import { fmtTime, getCalendar, openPlanDay, requestPlanFix, type CalSession, type CalView, type DistSport } from '@/lib/plancal'
import { checkinChips, createCheckin, type Checkin } from '@/lib/checkins'
import { cn } from '@/lib/utils'
import { InfoTip } from '@/components/ui/InfoTip'
import { openActivity } from '@/lib/activitynav'
import {
  CHECKLIST, fmtTemp, getWorkoutFeedback, getWorkoutToday, readChecklist, writeChecklist,
  type CheckInRequest, type Target, type Weather, type WorkoutFeedback, type WorkoutSession, type WorkoutToday, type WSection, type WStep,
} from '@/lib/workout'
import { GarminEmpty } from '@/components/garmin/GarminEmpty'
import { WeatherSection } from './WeatherSection'
import { WhoElse } from '@/components/people/WhoElse'
import { Related } from '@/components/nav/Related'
import { CalendarDays } from 'lucide-react'
import { sportIcon } from '@/lib/sportIcon'
import { FuelSection } from './FuelSection'
import { RabbitLogo } from '@/components/RabbitLogo'
import { SportTile } from '@/components/ui/SportTile'

const LOADING = ['Lacing up…', 'Loading your targets…', 'Checking the sky…', 'Stretching the hamstrings…']
const STATUS: Record<string, { label: string; cls: string }> = {
  done: { label: 'Done', cls: 'bg-(--accent) text-(--on-fill)' },
  missed: { label: 'Missed', cls: 'bg-(--danger)/10 text-(--danger)' },
  planned: { label: 'Planned', cls: 'bg-(--bg-elevated) text-(--text-secondary)' },
  skipped: { label: 'Skipped', cls: 'bg-(--bg-elevated) text-(--text-muted)' },
}

function distText(c: CalSession | undefined, imperial: boolean): string {
  if (!c) return ''
  return (Object.entries(c.km) as [DistSport, number][]).filter(([, v]) => v > 0).map(([sp, v]) => fmtDist(v, imperial, sp)).join(' + ')
}

export function WorkoutDayScreen({ sessionId, imperial, onClose, onAsk, onCheckIn }: {
  sessionId?: string
  imperial: boolean
  onClose: () => void
  onAsk?: (text: string) => void
  onCheckIn?: (p: CheckInRequest) => void
}) {
  const [sid, setSid] = useState<string | undefined>(sessionId)
  const [data, setData] = useState<WorkoutToday | null>(null)
  const [cal, setCal] = useState<CalView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [closing, setClosing] = useState(false)
  const [moving, setMoving] = useState<string | null>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)
  const load = useCallback(() => {
    setError(null)
    getWorkoutToday(sid).then(setData, (e: Error) => setError(e.message))
    // Exact targets and how it went (no plan, Garmin down: the page still works without them).
    getCalendar().then((r) => setCal(r.cal), () => setCal(null))
  }, [sid])
  useEffect(() => { load() }, [load])
  const close = () => { setClosing(true); window.setTimeout(onClose, 200) }

  const s = data?.state === 'session' ? data.session : null
  const c = s?.id ? cal?.sessions[s.id] : undefined
  const isToday = !!data && data.date === data.today
  const ahead = !!data && data.date >= data.today
  const status = c?.status ?? s?.status ?? 'planned'
  const title = s ? s.title : data?.state === 'rest' ? 'Rest day' : data?.state === 'free' ? 'Free day' : 'Workout'
  const when = data ? `${isToday ? 'Today' : fmtDay(data.date, { weekday: 'long', month: 'short', day: 'numeric' })}${s?.time ? ` · ${fmtTime(s.time)}` : ''}` : undefined
  const edit = () => { if (data) { close(); window.setTimeout(() => openPlanDay(data.date), 220) } }

  return (
    <Screen title={title} subtitle={when} onClose={close} closing={closing}
      footer={s ? (
        <>
          {s.id && ahead && status !== 'done' && (
            <Button variant="default" className="h-11 min-w-0 flex-1 gap-1.5 px-2 text-body" onClick={() => setMoving(s.id)}>
              <CalendarClock className="size-5 shrink-0" aria-hidden /> Move
            </Button>
          )}
          {s.id && (
            <Button variant="default" className="h-11 min-w-0 flex-1 gap-1.5 px-2 text-body" onClick={edit} aria-label="Edit this workout in your schedule">
              <Pencil className="size-5 shrink-0" aria-hidden /> Edit
            </Button>
          )}
          {s.id && data && (
            <ShareButton iconOnly target={{ kind: 'workout', ref: s.id, label: s.title }}
              onSendInRabbit={() => shareToFriends({ type: 'workout', ref: { kind: 'session', id: s.id!, date: data.date }, label: s.title })} />
          )}
          {s.id && status === 'done' ? (
            <Button variant="primary" className="h-11 min-w-0 flex-1 px-2 text-body"
              onClick={() => feedbackRef.current?.scrollIntoView({ behavior: smooth(), block: 'start' })}>
              How did it go?
            </Button>
          ) : onAsk && (
            <Button variant="default" className="h-11 min-w-0 flex-1 gap-1.5 px-2 text-body" aria-label="Ask rabbt"
              onClick={() => onAsk(`About my ${s.title} on ${when}: `)}>
              <MessageCircle className="size-5 shrink-0" aria-hidden /><span className="max-[359px]:hidden">Ask rabbt</span><span className="min-[360px]:hidden">Ask</span>
            </Button>
          )}
        </>
      ) : undefined}>
      {!data && !error && <WorkoutSkeleton />}
      {error && (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <p className="text-body text-(--text-muted)">{error}</p>
          <Button variant="default" onClick={load}>Try again</Button>
        </div>
      )}
      {data && data.others.length > 1 && (
        <div className="no-scrollbar -mb-2 flex gap-2 overflow-x-auto" role="tablist" aria-label="Sessions this day">
          {data.others.map((o) => {
            const on = !!s && o.id === s.id
            const I = sportIcon(o.sport)
            return (
              <button key={o.id ?? o.title} type="button" role="tab" aria-selected={on} disabled={!o.id}
                onClick={() => o.id && setSid(o.id)} className={cn('plan-chip shrink-0 gap-1.5', on && 'plan-chip--on')}>
                <I className="size-4" />{o.title}{o.status === 'done' && <Check className="size-4" />}
              </button>
            )
          })}
        </div>
      )}
      {data && s && (
        <SessionBody d={data} s={s} c={c} cal={cal} status={status} imperial={imperial} onSynced={load}
          feedbackRef={feedbackRef} onAsk={onAsk} onCheckIn={onCheckIn} onFix={() => {
            if (!s.id) return
            requestPlanFix(s.id)
            close(); window.setTimeout(() => openPlanDay(data.date), 220)
          }} />
      )}
      {data && s && s.id && s.sport !== 'rest' && (
        <WhoElse sport={s.sport} date={data.date} invite={ahead && status !== 'done'}
          share={{ type: 'workout', ref: { kind: 'session', id: s.id, date: data.date }, label: s.title }} />
      )}
      {data && (
        <Related items={[
          { key: 'day', icon: <CalendarDays className="size-5" />, label: 'This day in your plan', sub: fmtDay(data.date, { weekday: 'long', month: 'short', day: 'numeric' }),
            onClick: () => { close(); window.setTimeout(() => openPlanDay(data.date), 220) } },
          { key: 'act', icon: <Activity className="size-5" />, label: 'The recorded workout', sub: s?.activity?.name,
            onClick: (s?.activity?.id ?? c?.activity?.id) ? () => openActivity(String(s?.activity?.id ?? c?.activity?.id)) : null },
          { key: 'ask', icon: <MessageCircle className="size-5" />, label: 'Ask rabbt about it',
            onClick: onAsk && s ? () => onAsk(`About my ${s.title} on ${when}: `) : null },
        ]} link={s?.id ? { kind: 'workout', id: s.id, date: data.date } : undefined} />
      )}
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
      {moving && <MoveSessionSheet sessionId={moving} onClose={() => setMoving(null)} onMoved={() => { setMoving(null); load() }} />}
    </Screen>
  )
}

/** Placeholder at the page's real shape, so nothing jumps when the workout arrives. */
function WorkoutSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <div className="skeleton h-[112px] rounded-2xl" aria-hidden />
      <div className="skeleton h-[84px] rounded-xl" aria-hidden />
      <div className="skeleton h-[220px] rounded-xl" aria-hidden />
      <RabbitLoader className="py-4" label="Loading your workout" cycle={LOADING} />
    </div>
  )
}

export function Hero({ icon: Icon, sport, family, title, meta, line, chip }: {
  icon: typeof Bike; title: string
  /** a workout's sport (and family): shows the sport tile instead of the plain icon */
  sport?: string; family?: string | null
  /** short facts ("1h 45m", "28.6 mi", "Long"); a " · " string is split into separate facts */
  meta: string | string[]
  line: string; chip?: { label: string; cls: string }
}) {
  const facts = (Array.isArray(meta) ? meta : meta.split(' · ')).map((x) => x.trim()).filter(Boolean)
  return (
    <div className="celebrate flex flex-col gap-3.5 rounded-2xl border border-(--accent)/25 bg-(--accent-subtle) px-5 py-5">
      <div className="flex items-center gap-3">
        {sport || family ? <SportTile sport={sport} family={family} size={48} /> : (
          <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-(--accent) text-(--on-fill)">
            <Icon className="size-6" />
          </span>
        )}
        {chip && (
          <span className={cn('ml-auto flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-meta font-semibold', chip.cls)}>
            {chip.label === 'Done' && <Check className="size-4" strokeWidth={3} />}{chip.label}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="font-display text-display-sm leading-tight text-(--brand)">{title}</h3>
        {facts.length > 0 && (
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-body font-semibold text-(--accent)">
            {facts.map((f) => <span key={f}>{f}</span>)}
          </p>
        )}
      </div>
      {line && <p className="text-body-lg leading-relaxed text-(--text)">{line}</p>}
    </div>
  )
}

export function SectionCard({ title, icon: Icon, children }: { title: string; icon?: typeof Bike; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col rounded-xl border border-(--border) bg-(--bg-surface) pb-4">
      <h4 className="font-sans flex items-center gap-2 px-4 pt-4 text-lead font-semibold text-(--text)">
        {Icon && <Icon className="size-5 text-(--accent)" aria-hidden />}{title}
      </h4>
      {children}
    </section>
  )
}

function zonesIn(secs: WSection[]): number[] {
  const out = new Set<number>()
  const walk = (st: WStep[]) => { for (const x of st) { if (x.type === 'repeat') walk(x.steps); else if (x.zone) out.add(x.zone) } }
  for (const sec of secs) walk(sec.steps)
  return [...out].sort()
}

function LearnMore({ s }: { s: WorkoutSession }) {
  const [open, setOpen] = useState(false)
  const k = (s.kind && KIND_GLOSSARY[s.kind]) || (s.sport === 'brick' ? KIND_GLOSSARY.brick : undefined)
  const zones = zonesIn(s.sections)
  if (!k && !zones.length) return null
  return (
    <div className="rounded-xl border border-(--border) bg-(--bg-surface)">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex min-h-12 w-full items-center gap-2.5 px-4 text-left text-body font-medium text-(--accent)">
        <BookOpen className="size-5" aria-hidden /> <span className="flex-1">Learn more about this workout</span>
        <ChevronDown className={cn('size-5 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="flex flex-col gap-3 px-4 pb-4 text-body leading-relaxed">
          {k && (
            <dl className="flex flex-col gap-2.5">
              <div><dt className="font-semibold text-(--text)">What it is</dt><dd className="text-(--text-secondary)">{k.what}</dd></div>
              <div><dt className="font-semibold text-(--text)">Why it's in your plan</dt><dd className="text-(--text-secondary)">{k.why}</dd></div>
              <div><dt className="font-semibold text-(--text)">How it should feel</dt><dd className="text-(--text-secondary)">{k.feel}</dd></div>
            </dl>
          )}
          {zones.length > 0 && (
            <ul className="flex flex-col gap-1">
              {zones.map((z) => ZONE_GLOSSARY[z] && (
                <li key={z} className="text-(--text-secondary)"><span className="font-medium text-(--text)">{ZONE_GLOSSARY[z]!.title}:</span> {ZONE_GLOSSARY[z]!.text}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function SessionBody({ d, s, c, cal, status, imperial, onSynced, feedbackRef, onAsk, onCheckIn, onFix }: {
  d: WorkoutToday; s: WorkoutSession; c: CalSession | undefined; cal: CalView | null; status: string; imperial: boolean
  onSynced: () => void; feedbackRef: React.RefObject<HTMLDivElement | null>
  onAsk?: (text: string) => void; onCheckIn?: (p: CheckInRequest) => void; onFix: () => void
}) {
  const isToday = d.date === d.today
  const ahead = d.date >= d.today
  const [wxShown, setWxShown] = useState(false)  // the full Weather section replaces the small chip
  const dist = distText(c, imperial) || (s.meters ? (s.sport === 'swim' ? fmtMeters(s.meters, imperial) : fmtDist(s.meters / 1000, imperial)) : '')
  const meta = [s.minutes ? fmtDuration(s.minutes) : null, dist || null, s.kind ? KIND_LABEL[s.kind] ?? s.kind : null].filter((x): x is string => !!x)
  const t = c?.targets
  const note = c?.note
  return (
    <>
      <Hero icon={sportIcon(s.sport)} sport={s.sport} title={s.title} meta={meta.length ? meta : ['Workout']} line={note?.why || s.purpose}
        chip={STATUS[status] ?? STATUS.planned} />
      {s.time && (
        <p className="-mt-2 flex items-center gap-2 px-1 text-body text-(--text-secondary)">
          <Clock className="size-5" aria-hidden /> Starts at {fmtTime(s.time)}
        </p>
      )}
      {c?.adjusted && (
        <p className="flex items-start gap-2.5 rounded-xl border border-(--accent)/25 bg-(--accent-subtle) px-4 py-3 text-body leading-snug text-(--accent)">
          <RabbitLogo size={18} current className="mt-0.5 shrink-0" /> {c.adjusted}
        </p>
      )}
      {isToday && d.readiness && (
        <p className={cn('rounded-xl border px-4 py-3 text-body leading-snug',
          d.readiness.tone === 'easy' || d.readiness.tone === 'rest'
            ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)'
            : 'border-(--border) bg-(--bg-surface) text-(--text-secondary)')}>
          {d.readiness.line}
        </p>
      )}
      {status === 'missed' && (
        <div className="flex flex-col gap-2.5 rounded-xl border border-(--danger)/25 bg-(--danger)/5 px-4 py-4">
          <p className="flex items-center gap-1.5 text-body font-semibold text-(--danger)"><TriangleAlert className="size-5" aria-hidden /> Missed</p>
          {c?.missed?.why && <p className="text-small leading-snug text-(--text-secondary)">{c.missed.why}</p>}
          {s.id && c?.missed?.this_week && (
            <Button variant="default" className="h-11 gap-1.5 self-start px-4 text-body" onClick={onFix}>
              <Wrench className="size-5" aria-hidden /> Fix my week
            </Button>
          )}
        </div>
      )}
      {c?.went && <HowItWent w={c.went} imperial={imperial} sport={s.sport} />}
      {c?.activity?.id != null && (
        <Button variant="default" className="h-11 gap-1.5 self-start px-4 text-body" onClick={() => openActivity(c.activity!.id!)}>
          <Activity className="size-5" aria-hidden /> See your recorded workout
        </Button>
      )}

      {t ? (
        <>
          <SectionCard title="Key numbers"><WorkoutSummary t={t} dist={dist} imperial={imperial} /></SectionCard>
          {/* WorkoutSteps brings its own "The workout" heading */}
          <section aria-label="The workout" className="rounded-xl border border-(--border) bg-(--bg-surface) pb-4">
            <WorkoutSteps t={t} imperial={imperial} />
          </section>
        </>
      ) : (
        <>
          {s.main_targets.length > 0 && <TargetChips targets={s.main_targets} label="Main target" />}
          {s.sections.length > 0 && <Timeline sections={s.sections} />}
          {s.sections.length === 0 && s.detail && <Card><Field label="The workout"><p className="text-body text-(--text)">{s.detail}</p></Field></Card>}
        </>
      )}
      {s.exercises.length > 0 && (
        <Card>
          <Field label="Exercises">
            <ExerciseList items={[...s.exercises, ...s.prehab]} />
          </Field>
        </Card>
      )}
      {note && (note.how || note.cues) ? (note.source === 'coach' ? (
        <SectionCard title="From your coach" icon={Lightbulb}>
          <div className="flex flex-col gap-2 px-4 pt-2 text-body leading-relaxed">
            {note.how && <p className="text-(--text)">{note.how}</p>}
            {note.cues && <p className="text-(--text-secondary)"><b className="font-semibold">Cues:</b> {note.cues}</p>}
          </div>
        </SectionCard>
      ) : (
        <RabbitNote title="How to do it">
          {note.how && <p className="m-0 text-body text-(--text)">{note.how}</p>}
          {note.cues && <p className="m-0 text-body text-(--text-secondary)"><b className="font-semibold">Cues:</b> {note.cues}</p>}
        </RabbitNote>
      )) : <CueCard cue={s.cue} />}
      {s.id && ahead && status !== 'done' && <WeatherSection sessionId={s.id} imperial={imperial} onShown={setWxShown} />}
      {s.fuel_plan ? <FuelSection fp={s.fuel_plan} ahead={!!ahead && status !== 'done'} onSaved={onSynced} /> : <FuelCard s={s} />}
      {(s.gear.length > 0 || (isToday && d.weather && !wxShown)) && (
        <div className="flex flex-col gap-2">
          {s.gear.map((g) => (
            <div key={g.id} className={cn('flex items-center gap-3 rounded-xl border px-4 py-3',
              g.warning ? 'border-(--warning)/30 bg-(--warning-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
              {g.kind === 'bike' ? <Bike className="size-5 shrink-0 text-(--accent)" /> : <Footprints className="size-5 shrink-0 text-(--accent)" />}
              <span className="min-w-0 flex-1">
                <span className="block text-body font-medium text-(--text)">{g.name}</span>
                <span className={cn('block text-small', g.warning ? 'text-(--warning-text)' : 'text-(--text-muted)')}>
                  {g.warning ?? `${g.total_label} so far`}
                </span>
              </span>
            </div>
          ))}
          {isToday && d.weather && !wxShown && <WeatherChip w={d.weather} imperial={imperial} />}
        </div>
      )}
      {s.id && ahead && status !== 'done' && s.garmin.syncable && (d.garmin_connected === false
        ? <GarminEmpty what="workout" compact />
        : <WatchRow s={s} onSynced={onSynced} />)}
      <LearnMore s={s} />
      {cal?.pace_source === 'default' && s.sport === 'run' && ahead && (
        <p className="px-1 text-small leading-snug text-(--text-muted)">
          Paces start from a typical runner. Add your threshold pace in Me › Training profile, or keep training and rabbt will learn it from your runs.
        </p>
      )}
      {s.id && (status === 'done' || d.date <= d.today) && (
        <div ref={feedbackRef} className="scroll-mt-4">
          <FeedbackCard s={s} c={c} date={d.date} imperial={imperial} onAsk={onAsk}
            onVoice={onCheckIn ? () => onCheckIn({ sessionId: s.id ?? undefined, activityId: s.activity?.id ?? undefined, title: s.title }) : undefined} />
        </div>
      )}
      {s.id && (status === 'done' || d.date <= d.today) && wantsFuelLog(s.minutes, s.kind, s.sport) && (
        <FuelLog fuelKey={`s:${s.id}`} minutes={c?.went?.actual?.minutes ?? s.minutes ?? 60} sport={s.sport} title={s.title}
          date={d.date} imperial={imperial} plannedGh={s.fuel?.carbs_g_per_h ?? null} />
      )}
      {status !== 'done' && isToday && <Checklist day={d.today} sport={s.sport} />}
    </>
  )
}

export const RPE_WORD = ['', 'Very easy', 'Very easy', 'Easy', 'Easy', 'Moderate', 'Moderate', 'Hard', 'Hard', 'Very hard', 'All out']
export const FEELS = [
  { id: 'great', label: 'Great', feel: 5 }, { id: 'ok', label: 'OK', feel: 3 },
  { id: 'tough', label: 'Tough', feel: 2 }, { id: 'pain', label: 'Something hurts', feel: 2 },
] as const
export const TONE: Record<WorkoutFeedback['tone'], string> = {
  good: 'border-(--accent)/30 bg-(--accent-subtle)', info: 'border-(--border) bg-(--bg-surface)',
  ease: 'border-(--warning)/30 bg-(--warning-subtle)', care: 'border-(--danger)/30 bg-(--danger)/5',
}

/** "How did it go?" (RPE slider, feel, pain, note: saved as this session's check-in) and
 *  Rabbit's feedback: the server's deterministic read first, then "Ask Rabbit for more" with the
 *  workout's Garmin numbers and the athlete's own words prefilled (never Oura data). */
function FeedbackCard({ s, c, date, imperial, onAsk, onVoice }: {
  s: WorkoutSession; c: CalSession | undefined; date: string; imperial: boolean; onAsk?: (text: string) => void; onVoice?: () => void
}) {
  const saveBtn = useRef<HTMLButtonElement>(null)
  const [got, setGot] = useState<{ checkin: Checkin | null; feedback: WorkoutFeedback | null } | null>(null)
  const [editing, setEditing] = useState(false)
  const [rpe, setRpe] = useState(5)
  const [feel, setFeel] = useState<(typeof FEELS)[number]['id'] | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const sid = s.id!
  const load = useCallback(() => { getWorkoutFeedback(sid).then(setGot, () => setGot({ checkin: null, feedback: null })) }, [sid])
  useEffect(() => { load() }, [load])

  async function save() {
    setBusy(true); setErr(null)
    const f = FEELS.find((x) => x.id === feel)
    try {
      await createCheckin({ text: note.trim(), session_id: sid, activity_id: s.activity?.id ?? undefined, date, rpe,
        feel: f?.feel, pain: feel === 'pain' })
      if (feel !== 'pain') celebrate(saveBtn.current, 'xp') // a little hop for logging it
      else openBody({ view: 'log-niggle', affects: s.sport }) // "Something hurts": log where (body.py)
      setEditing(false); setNote(''); load()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  function askMore() {
    if (!onAsk) return
    const a = c?.went?.actual
    const u = imperial ? 'mi' : 'km'
    const did = a ? [a.minutes ? `${a.minutes} min` : '', a.km ? fmtDist(a.km, imperial, s.sport === 'swim' ? 'swim' : s.sport === 'bike' ? 'bike' : 'run') : '',
      a.pace ? `avg pace ${Math.floor((a.pace * (imperial ? 1.609344 : 1)) / 60)}:${String(Math.round((a.pace * (imperial ? 1.609344 : 1)) % 60)).padStart(2, '0')}/${u}` : '',
      a.avg_hr ? `avg HR ${Math.round(a.avg_hr)}` : '', a.cadence ? `cadence ${Math.round(a.cadence)}` : ''].filter(Boolean).join(', ') : ''
    const ck = got?.checkin
    const words = [ck?.rpe != null ? `RPE ${ck.rpe}/10` : '', ck?.feel != null ? `felt ${ck.feel}/5` : '', ck?.pain_flag ? 'something hurt' : '', ck?.text ? `"${ck.text}"` : ''].filter(Boolean).join(', ')
    onAsk(`Feedback on my ${s.title} (${fmtDay(date, { weekday: 'long', month: 'short', day: 'numeric' })}): planned ${s.minutes ? fmtDuration(s.minutes) : ''}${s.kind ? ` ${KIND_LABEL[s.kind] ?? s.kind}` : ''}.`
      + (did ? ` I did ${did}.` : '') + (words ? ` ${words}.` : '') + ' How did it go, and what should I change next time? ')
  }

  const ck = got?.checkin
  const fb = got?.feedback
  const form = editing || (got !== null && !ck)
  return (
    <section aria-label="How did it go" className="flex flex-col gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) p-4">
      <h4 className="font-sans text-lead font-semibold text-(--text)">How did it go?</h4>
      {got === null && <div className="skeleton h-[120px] rounded-lg" aria-hidden />}
      {ck && !editing && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            {checkinChips(ck).map((x) => (
              <span key={x.label} className={cn('rounded-full border px-3 py-1 text-meta font-medium',
                x.warn ? 'border-(--warning)/30 bg-(--warning-subtle) text-(--warning-text)' : 'border-(--border) text-(--text)')}>{x.label}</span>
            ))}
          </div>
          {ck.text && <p className="text-small leading-snug text-(--text-secondary)">“{ck.text}”</p>}
          <button type="button" className="hit-44 self-start text-small font-medium text-(--accent)" onClick={() => setEditing(true)}>Add another note</button>
        </div>
      )}
      {form && (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="flex items-baseline justify-between text-small text-(--text)">
              <span>Effort (RPE)</span>
              <span className="font-semibold tabular-nums text-(--accent)" aria-hidden>{rpe} of 10, {RPE_WORD[rpe]!.toLowerCase()}</span>
            </span>
            <input type="range" min={1} max={10} step={1} value={rpe} onChange={(e) => setRpe(Number(e.target.value))}
              aria-valuetext={`${rpe} out of 10, ${RPE_WORD[rpe]}`} className="h-11 w-full accent-(--accent)" />
          </label>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="How did it feel">
            {FEELS.map((f) => (
              <button key={f.id} type="button" role="radio" aria-checked={feel === f.id} onClick={() => setFeel(feel === f.id ? null : f.id)}
                className={cn('plan-chip min-h-11', feel === f.id && 'plan-chip--on', f.id === 'pain' && feel === f.id && 'border-(--danger) text-(--danger)')}>
                {f.label}
              </button>
            ))}
          </div>
          <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 600))} rows={2} placeholder="Anything else? Legs, sleep, weather… (optional)"
            aria-label="Note about this workout"
            className="min-h-11 w-full rounded-md border border-input bg-transparent px-3 py-2 text-body text-(--text) placeholder:text-(--text-muted) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
          {err && <p className="text-meta text-(--danger)" role="alert">{err}</p>}
          <div className="flex flex-wrap gap-2">
            <Button ref={saveBtn} variant="primary" className="h-11 flex-1 text-body" loading={busy} onClick={() => void save()}>Save</Button>
            {editing && <Button variant="ghost" className="h-11 px-3 text-body" onClick={() => setEditing(false)}>Cancel</Button>}
            {onVoice && <Button variant="ghost" className="h-11 px-3 text-body" onClick={onVoice}>Say it instead</Button>}
          </div>
        </div>
      )}
      {fb && (
        <div aria-live="polite">
          <RabbitNote title="rabbt's feedback" className={fb.tone === 'ease' || fb.tone === 'care' ? TONE[fb.tone] : undefined}>
            <p className="m-0 text-body font-semibold text-(--text)">{fb.headline}</p>
            {fb.lines.map((l) => <p key={l} className="m-0 text-(--text-secondary)"><RabbitInline text={l} /></p>)}
          </RabbitNote>
        </div>
      )}
      {onAsk && (ck || c?.went) && (
        <Button variant="default" className="h-11 gap-1.5 text-body" onClick={askMore}>
          <MessageCircle className="size-5" aria-hidden /> Ask rabbt for more feedback
        </Button>
      )}
    </section>
  )
}

function TargetChips({ targets, label }: { targets: Target[]; label?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <span className="px-1 text-meta font-semibold text-(--text-secondary)">{label}</span>}
      <div className="flex flex-wrap gap-2">
        {targets.map((t) => t.kind === 'rpe' ? (
          <span key={t.kind + t.label} className="inline-flex items-center"><BigChip t={t} /><InfoTip term="rpe" /></span>
        ) : <BigChip key={t.kind + t.label} t={t} />)}
      </div>
    </div>
  )
}

function BigChip({ t, small }: { t: Target; small?: boolean }) {
  return (
    <span className={cn('inline-flex items-baseline gap-1 rounded-lg font-display leading-none',
      t.kind === 'hr' ? 'bg-(--bg-elevated) text-(--text)' : 'bg-(--accent-subtle) text-(--accent)',
      small ? 'px-2 py-1 text-lead' : 'px-3 py-2 text-title-md')}>
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
              <span className="text-body font-semibold text-(--accent)">{sec.name}</span>
              <span className="text-small text-(--text-muted)">{Number.isInteger(sec.minutes) ? fmtDuration(sec.minutes) : fmtMin(sec.minutes)}</span>
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
      <div className="rounded-xl border border-(--accent)/30 px-4 py-3">
        <span className="flex items-center gap-1.5 text-meta font-semibold text-(--accent)">
          <Repeat className="size-5" /> Repeat {s.reps} times
        </span>
        <div className="mt-2 flex flex-col gap-2">{s.steps.map((x, i) => <StepRow key={i} s={x} />)}</div>
      </div>
    )
  }
  const hard = s.type === 'work'
  return (
    <div className={cn('flex flex-col gap-2 rounded-xl border px-4 py-3',
      hard ? 'border-(--accent)/40 bg-(--accent-subtle)' : 'border-(--border) bg-(--bg-surface)')}>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-display text-title leading-none text-(--text)">{s.amount}</span>
        <span className="text-body text-(--text-secondary)">{s.label}</span>
        <span className="ml-auto rounded-full bg-(--bg-inset) px-2 text-caption font-semibold text-(--text-secondary)">Zone {s.zone}, {s.zone_name}</span>
      </p>
      <div className="flex flex-wrap gap-1.5">{s.targets.map((t) => <BigChip key={t.kind + t.label} t={t} small />)}</div>
    </div>
  )
}

function CueCard({ cue }: { cue: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-(--brand)/20 bg-(--bg-surface) px-4 py-3.5">
      <Lightbulb className="mt-0.5 size-5 shrink-0 text-(--brand)" />
      <p className="text-body leading-snug text-(--text)"><b className="font-semibold">Key cue:</b> {cue}</p>
    </div>
  )
}

function FuelCard({ s }: { s: WorkoutSession }) {
  if (s.sport === 'rest' || s.sport === 'strength') return null
  return (
    <div className="flex items-start gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3.5">
      <Utensils className="mt-0.5 size-5 shrink-0 text-(--accent)" />
      {s.fuel ? (
        <div className="min-w-0 flex-1">
          <p className="text-body text-(--text)">
            <b className="font-display text-title-sm">{s.fuel.carbs_g_per_h} g</b> carbs/h
            {s.fuel.total_carbs_g != null && <span className="block text-small text-(--text-muted)">About {s.fuel.total_carbs_g} g in all</span>}
            {s.fuel.fluid_ml_per_h && <span className="block text-small text-(--text-muted)">Drink {s.fuel.fluid_ml_per_h} ml an hour</span>}
          </p>
          <p className="mt-1 text-small leading-snug text-(--text-muted)">{s.fuel.note}</p>
        </div>
      ) : (
        <p className="text-body text-(--text-secondary)">Water is enough for this one. Eat normally beforehand.</p>
      )}
    </div>
  )
}

function WeatherChip({ w, imperial }: { w: Weather; imperial: boolean }) {
  const wind = w.wind_kmh != null ? fmtSpeed(w.wind_kmh, imperial) : null
  return (
    <div className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3">
      <CloudSun className="size-5 shrink-0 text-(--accent)" />
      <span className="min-w-0 flex-1">
        <span className="block text-body text-(--text)">
          <b className="font-semibold">{fmtTemp(w.temp_c, imperial)}</b> {w.summary}
          {w.feels_c != null && w.temp_c != null && Math.abs(w.feels_c - w.temp_c) >= 3 && <span className="text-(--text-muted)"> · feels {fmtTemp(w.feels_c, imperial)}</span>}
        </span>
        <span className="block text-small text-(--text-muted)">
          {w.place}{w.rain_pct != null && w.rain_pct >= 20 ? ` · ${w.rain_pct}% rain next 3 h` : ''}
          {w.next.length > 0 && ` · ${w.next.map((h) => `${h.time} ${fmtTemp(h.temp_c, imperial)}`).join(', ')}`}
        </span>
      </span>
      {wind && <span className="flex shrink-0 items-center gap-1 text-small text-(--text-muted)"><Wind className="size-5" />{wind}</span>}
    </div>
  )
}

function WatchRow({ s, onSynced }: { s: WorkoutSession; onSynced: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (s.garmin.on_watch) {
    return (
      <p className="flex items-center gap-2 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) px-4 py-3 text-body font-medium text-(--accent)">
        <Watch className="size-5" /> On your watch <Check className="size-5" strokeWidth={3} />
      </p>
    )
  }
  const send = async () => {
    setBusy(true); setErr(null)
    try { await syncGarmin(7); onSynced() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Button variant="default" className="h-12 gap-1.5 text-body font-semibold text-(--accent)" loading={busy} onClick={() => void send()}>
        <Watch className="size-5" /> Send to watch
      </Button>
      <p className="px-1 text-small text-(--text-muted)">{err ?? 'Sends this week\'s plan to Garmin. Sync your watch to pick it up.'}</p>
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
                  className="flex min-h-11 w-full items-center gap-3 rounded-lg py-1.5 text-left active:opacity-70">
                  <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md border transition-colors',
                    on ? 'border-(--accent) bg-(--accent) text-(--on-fill)' : 'border-(--border)')}>
                    {on && <Check className="size-4" strokeWidth={3} />}
                  </span>
                  <span className={cn('text-body', on ? 'text-(--text-muted) line-through' : 'text-(--text)')}>{t}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </Field>
    </Card>
  )
}
