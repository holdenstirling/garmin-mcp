// Race readiness + race fit for one race: the readiness grade (status, headline, how you're
// tracking, what to do next), then course & conditions (race-fit factors, collapsed by
// default), your coach's race notes, and Rabbit's AI race strategy with "Ask your coach"
// (a race-tied coach thread) or, without a coach, a "Find a coach" link.
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, MessageSquare, RefreshCw, Search, StickyNote } from 'lucide-react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Field, Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { athleteChat, getCoaches, timeAgo, type CoachLink } from '@/lib/coach'
import { FindCoachScreen } from '@/components/coach/FindCoachScreen'
import { ThreadView } from '@/components/coach/ThreadView'
import { countdown, type RaceStrategy } from '@/lib/events'
import { IMPACT_LABEL, getRaceView, makeStrategy, type FitFactor, type Impact, type RaceView } from '@/lib/racefit'
import { getReadiness, type Readiness } from '@/lib/readiness'
import { ReadinessSection } from './Readiness'
import { FinishEstimate } from './FinishEstimate'
import { RacePeopleSection } from './RacePeople'

const CHIP: Record<Impact, string> = {
  helps: 'bg-(--accent-subtle) text-(--accent)',
  watch: 'bg-(--warning-subtle) text-(--warning-text)',
  risk: 'bg-(--danger-subtle) text-(--danger)',
  neutral: 'bg-(--bg-elevated) text-(--text-muted)',
}

export function RaceFitScreen({ eventId, onClose, race = true }: {
  eventId: string; onClose: () => void
  /** false for group activities, trips, challenges and life events: "Event prep", no readiness grade or finish estimate */
  race?: boolean
}) {
  const [v, setV] = useState<RaceView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [r, setR] = useState<Readiness | null>(null)
  const [rError, setRError] = useState<string | null>(null)
  const [rDone, setRDone] = useState(false)
  const [closing, setClosing] = useState(false)
  const load = useCallback(() => {
    setError(null)
    getRaceView(eventId).then(setV, (e) => setError((e as Error).message))
  }, [eventId])
  const loadReadiness = useCallback(() => {
    if (!race) { setRDone(true); return }
    setRError(null)
    getReadiness(eventId).then(setR, (e) => setRError((e as Error).message)).finally(() => setRDone(true))
  }, [eventId, race])
  useEffect(() => { load(); loadReadiness() }, [load, loadReadiness])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }
  // Ask your coach: race-tied thread with the athlete's coach; no coach -> Find a coach.
  const [coaches, setCoaches] = useState<CoachLink[] | null>(null)
  const [coachThread, setCoachThread] = useState<{ id: string; coach: string; draft: string } | null>(null)
  const [findCoach, setFindCoach] = useState(false)
  const [askErr, setAskErr] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  useEffect(() => { getCoaches().then((x) => setCoaches(x.coaches), () => setCoaches([])) }, [])
  const coach = (coaches ?? []).find((c) => c.status === 'active') ?? coaches?.[0] ?? null
  async function askCoach() {
    if (!coach || !v) return
    setAsking(true); setAskErr(null)
    try {
      const t = (await athleteChat.open({ coach: coach.email, event_id: eventId })).thread
      const gaps = r ? [...r.components].sort((a, b) => a.score - b.score).slice(0, 2).map((c) => c.label.toLowerCase()) : []
      const draft = `Can we talk strategy for ${v.event.name}?` +
        (r ? ` My readiness is ${r.grade}${gaps.length ? `; biggest gaps: ${gaps.join(' and ')}` : ''}.` : '')
      setCoachThread({ id: t.id, coach: coach.email, draft: t.messages.length ? '' : draft })
    } catch (e) { setAskErr((e as Error).message) } finally { setAsking(false) }
  }
  const coachExtra = coaches === null ? null : coach ? (
    <div className="flex flex-col gap-1 border-t border-(--border) pt-2.5">
      <Button variant="default" className="h-11 w-fit gap-1.5 text-small" loading={asking} onClick={() => void askCoach()}>
        <MessageSquare className="size-5" /> Ask your coach
      </Button>
      {askErr && <p className="text-meta text-(--danger)" role="alert">{askErr}</p>}
    </div>
  ) : (
    <button type="button" onClick={() => setFindCoach(true)}
      className="hit-44 flex w-fit items-center gap-1.5 text-small text-(--accent)">
      <Search className="size-4" /> Want a human coach? Find one
    </button>
  )

  return (
    <Screen title={race ? 'Race readiness' : 'Event prep'} subtitle={v ? `${v.event.name} · ${countdown(v.event.date)}` : undefined} closing={closing} onClose={close} onBack={close}>
      {(!v || !rDone) && !error && <RabbitLoader className="py-16" label={race ? 'Grading your readiness' : 'Getting your prep ready'}
        cycle={race ? ['Grading your readiness…', 'Checking your long runs…', 'Sizing up the course…'] : ['Checking the details…', 'Sizing up the conditions…', 'Lining up your prep…']} />}
      {error && <ErrorState message={error} onRetry={load} />}
      {v && rDone && (
        <>
          {race && <ReadinessSection r={r} error={rError} onRetry={loadReadiness} />}
          {race && <FinishEstimate eventId={eventId} />}
          <RacePeopleSection eventId={eventId} eventName={v.event.name} />
          <h2 className="mt-1 px-1 text-caption font-semibold text-(--text-muted)">Course & conditions</h2>
          <p className="px-1 text-body-lg leading-snug text-(--text)">{v.racefit.summary}</p>
          {v.racefit.factors.length > 0 && (
            <Card>
              <div className="divide-y divide-(--border)">
                {v.racefit.factors.map((f) => <FactorRow key={f.id} f={f} />)}
              </div>
            </Card>
          )}
          <p className="px-1 text-meta text-(--text-muted)">
            Based on your profile (strengths, home elevation, heat) and the {race ? 'race' : 'event'} details. Add more of either for a sharper read.
          </p>
          {v.coach_notes.length > 0 && (
            <Card>
              <Field label="From your coach">
                <div className="flex flex-col gap-2.5">
                  {v.coach_notes.map((n) => (
                    <div key={n.id} className="flex gap-2">
                      <StickyNote className="mt-0.5 size-4 shrink-0 text-(--accent)" />
                      <div className="min-w-0">
                        <p className="whitespace-pre-wrap text-body leading-snug text-(--text)">{n.text}</p>
                        <p className="text-caption text-(--text-muted)">{n.coach.split('@')[0]} · {timeAgo(n.ts)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </Field>
            </Card>
          )}
          <StrategyCard eventId={eventId} strategy={v.strategy} onUpdated={setV} extra={coachExtra} race={race} />
        </>
      )}
      {coachThread && (
        <Screen title="Race chat" subtitle={coachThread.coach} onBack={() => setCoachThread(null)}>
          <ThreadView api={athleteChat} threadId={coachThread.id} me="athlete" otherName={coachThread.coach.split('@')[0]!} draft={coachThread.draft} />
        </Screen>
      )}
      {findCoach && <FindCoachScreen athleteName="" onClose={() => setFindCoach(false)} onBack={() => setFindCoach(false)} />}
    </Screen>
  )
}

function FactorRow({ f }: { f: FitFactor }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex min-h-11 w-full items-center gap-2.5 px-4 py-3 text-left active:bg-(--bg-inset)">
        <span className={cn('w-16 shrink-0 rounded-full px-2 py-0.5 text-center text-caption font-semibold', CHIP[f.impact])}>
          {IMPACT_LABEL[f.impact]}
        </span>
        <span className="shrink-0 text-body-lg font-medium text-(--text)">{f.title}</span>
        <span className="min-w-0 flex-1 truncate text-meta text-(--text-muted)">{open ? '' : f.detail}</span>
        <ChevronDown className={cn('size-5 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="flex flex-col gap-1.5 px-4 pb-3 text-small leading-snug">
          <p className="text-(--text-secondary)">{f.detail}</p>
          {f.tip && <p className="text-(--text)"><b className="text-(--accent)">Tip:</b> {f.tip}</p>}
        </div>
      )}
    </div>
  )
}

function StrategyCard({ eventId, strategy, onUpdated, extra, race }: {
  eventId: string; strategy: RaceStrategy | null; onUpdated: (v: RaceView) => void; race: boolean
  /** "Ask your coach" or "Find a coach", next to the AI strategy */
  extra?: React.ReactNode
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function run() {
    setBusy(true); setError(null)
    try { onUpdated(await makeStrategy(eventId)) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  const sections: [string, string[]][] = strategy ? [
    ['Key risks', strategy.key_risks], ['Pacing', strategy.pacing], ['Fueling', strategy.fueling],
    ['Training focus', strategy.training_focus], ['Mindset', strategy.mental],
  ] : []
  return (
    <Card>
      <Field label={race ? 'Race strategy' : 'Game plan'} hint={strategy ? `Written ${timeAgo(strategy.created)} · ${strategy.weeks_to_race} weeks out (${strategy.phase})` : `rabbt writes a plan for the day from your profile, this ${race ? 'race' : 'event'} and your training phase.`}>
        {!strategy ? (
          <Button variant="primary" className="h-10 gap-1.5 text-small" loading={busy} onClick={() => void run()}>
            <RabbitLogo size={16} current /> {race ? 'Ask rabbt for a race strategy' : 'Ask rabbt for a game plan'}
          </Button>
        ) : (
          <div className="flex flex-col gap-2.5 text-small leading-snug">
            <p className="text-body text-(--text)">{strategy.summary}</p>
            {sections.filter(([, xs]) => xs.length > 0).map(([label, xs]) => (
              <div key={label}>
                <p className="text-caption font-semibold text-(--text-muted)">{label}</p>
                <ul className="mt-0.5 flex flex-col gap-0.5 text-(--text-secondary)">{xs.map((x) => <li key={x}>• {x}</li>)}</ul>
              </div>
            ))}
            {strategy.taper_notes && <p className="text-(--text-secondary)"><b className="text-(--text)">Taper:</b> {strategy.taper_notes}</p>}
            <Button variant="ghost" className="h-9 w-fit gap-1.5 px-2 text-meta" loading={busy} onClick={() => void run()}>
              <RefreshCw className="size-4" /> Refresh strategy
            </Button>
          </div>
        )}
        {error && <p className="text-meta text-(--danger)" role="alert">{error}</p>}
        {extra}
      </Field>
    </Card>
  )
}
