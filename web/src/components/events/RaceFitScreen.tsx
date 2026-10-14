// Race readiness + race fit for one race: the readiness grade (status, headline, how you're
// tracking, what to do next), then course & conditions (race-fit factors, collapsed by
// default), your coach's race notes, and Rabbit's AI race strategy.
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, RefreshCw, Sparkles, StickyNote } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card, Field, Screen } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { timeAgo } from '@/lib/coach'
import { countdown, type RaceStrategy } from '@/lib/events'
import { IMPACT_LABEL, getRaceView, makeStrategy, type FitFactor, type Impact, type RaceView } from '@/lib/racefit'
import { getReadiness, type Readiness } from '@/lib/readiness'
import { ReadinessSection } from './Readiness'

const CHIP: Record<Impact, string> = {
  helps: 'bg-(--accent-subtle) text-(--accent)',
  watch: 'bg-(--warning-subtle) text-(--warning-text)',
  risk: 'bg-(--danger-subtle) text-(--danger)',
  neutral: 'bg-(--bg-elevated) text-(--text-muted)',
}

export function RaceFitScreen({ eventId, onClose }: { eventId: string; onClose: () => void }) {
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
    setRError(null)
    getReadiness(eventId).then(setR, (e) => setRError((e as Error).message)).finally(() => setRDone(true))
  }, [eventId])
  useEffect(() => { load(); loadReadiness() }, [load, loadReadiness])
  const close = () => { setClosing(true); setTimeout(onClose, 200) }

  return (
    <Screen title="Race readiness" subtitle={v ? `${v.event.name} · ${countdown(v.event.date)}` : undefined} closing={closing} onClose={close} onBack={close}>
      {(!v || !rDone) && !error && <RabbitLoader className="py-16" label="Grading your readiness" cycle={['Grading your readiness…', 'Checking your long runs…', 'Sizing up the course…']} />}
      {error && <ErrorState message={error} onRetry={load} />}
      {v && rDone && (
        <>
          <ReadinessSection r={r} error={rError} onRetry={loadReadiness} />
          <h2 className="mt-1 px-1 font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">Course & conditions</h2>
          <p className="px-1 text-[0.8824rem] leading-snug text-(--text)">{v.racefit.summary}</p>
          {v.racefit.factors.length > 0 && (
            <Card>
              <div className="divide-y divide-(--border)">
                {v.racefit.factors.map((f) => <FactorRow key={f.id} f={f} />)}
              </div>
            </Card>
          )}
          <p className="px-1 text-[0.7059rem] text-(--text-muted)">
            Based on your profile (strengths, home elevation, heat) and the race details. Add more of either for a sharper read.
          </p>
          {v.coach_notes.length > 0 && (
            <Card>
              <Field label="From your coach">
                <div className="flex flex-col gap-2.5">
                  {v.coach_notes.map((n) => (
                    <div key={n.id} className="flex gap-2">
                      <StickyNote className="mt-0.5 size-3.5 shrink-0 text-(--accent)" />
                      <div className="min-w-0">
                        <p className="whitespace-pre-wrap text-[0.8235rem] leading-snug text-(--text)">{n.text}</p>
                        <p className="text-[0.6471rem] text-(--text-muted)">{n.coach.split('@')[0]} · {timeAgo(n.ts)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </Field>
            </Card>
          )}
          <StrategyCard eventId={eventId} strategy={v.strategy} onUpdated={setV} />
        </>
      )}
    </Screen>
  )
}

function FactorRow({ f }: { f: FitFactor }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex min-h-11 w-full items-center gap-2.5 px-4 py-3 text-left active:bg-(--bg-inset)">
        <span className={cn('w-16 shrink-0 rounded-full px-2 py-0.5 text-center font-mono text-[0.6471rem] font-semibold uppercase tracking-wider', CHIP[f.impact])}>
          {IMPACT_LABEL[f.impact]}
        </span>
        <span className="shrink-0 text-[0.8824rem] font-medium text-(--text)">{f.title}</span>
        <span className="min-w-0 flex-1 truncate text-[0.7059rem] text-(--text-muted)">{open ? '' : f.detail}</span>
        <ChevronDown className={cn('size-4 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="flex flex-col gap-1.5 px-4 pb-3 text-[0.7647rem] leading-snug">
          <p className="text-(--text-secondary)">{f.detail}</p>
          {f.tip && <p className="text-(--text)"><b className="text-(--accent)">Tip:</b> {f.tip}</p>}
        </div>
      )}
    </div>
  )
}

function StrategyCard({ eventId, strategy, onUpdated }: {
  eventId: string; strategy: RaceStrategy | null; onUpdated: (v: RaceView) => void
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
      <Field label="Race strategy" hint={strategy ? `Written ${timeAgo(strategy.created)} · ${strategy.weeks_to_race} weeks out (${strategy.phase})` : 'Rabbit writes a plan for the day from your profile, this race and your training phase.'}>
        {!strategy ? (
          <Button variant="primary" className="h-10 gap-1.5 text-[0.7647rem]" loading={busy} onClick={() => void run()}>
            <Sparkles className="size-4" /> Get AI race strategy
          </Button>
        ) : (
          <div className="flex flex-col gap-2.5 text-[0.7647rem] leading-snug">
            <p className="text-[0.8235rem] text-(--text)">{strategy.summary}</p>
            {sections.filter(([, xs]) => xs.length > 0).map(([label, xs]) => (
              <div key={label}>
                <p className="font-mono text-[0.6471rem] font-semibold uppercase tracking-widest text-(--text-muted)">{label}</p>
                <ul className="mt-0.5 flex flex-col gap-0.5 text-(--text-secondary)">{xs.map((x) => <li key={x}>• {x}</li>)}</ul>
              </div>
            ))}
            {strategy.taper_notes && <p className="text-(--text-secondary)"><b className="text-(--text)">Taper:</b> {strategy.taper_notes}</p>}
            <Button variant="ghost" className="h-9 w-fit gap-1.5 px-2 text-[0.7059rem]" loading={busy} onClick={() => void run()}>
              <RefreshCw className="size-3.5" /> Refresh strategy
            </Button>
          </div>
        )}
        {error && <p className="text-[0.7059rem] text-(--danger)" role="alert">{error}</p>}
      </Field>
    </Card>
  )
}
