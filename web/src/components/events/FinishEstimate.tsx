// Race finish-time estimates (predict.py). ``FinishChip``: "Est. 1:52–1:58" on race cards.
// ``FinishEstimate``: the race screen's "Your estimated finish" block: range bar, splits for
// triathlons, what it's based on, assumptions behind an (i), the "if you follow your plan"
// projection and the cutoff margin. Both load their own data and stay quiet on failure
// (the chip) or show a plain reason (the block).
import { useEffect, useState } from 'react'
import { Flag, Timer, TrendingUp } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { ErrorState } from '@/components/ui/ErrorState'
import { RabbitLoader } from '@/components/RabbitLoader'
import { Card } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import {
  CONF_LABEL, LEG_LABEL, fmtClock, fmtGap, hasEstimate, predictCoachEvent, predictEvent,
  type Prediction, type PredictResult,
} from '@/lib/predict'

function useEventPrediction(eventId: string, athleteId?: string) {
  const [res, setRes] = useState<PredictResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setError(null)
    const p = athleteId ? predictCoachEvent(athleteId, eventId) : predictEvent(eventId)
    p.then((r) => { if (live) setRes(r) }, (e) => { if (live) setError((e as Error).message) })
    return () => { live = false }
  }, [eventId, athleteId, tick])
  return { res, error, retry: () => { setRes(null); setTick((t) => t + 1) } }
}

/** "Est. 1:52–1:58" for a race card; nothing until (or unless) there's an estimate. */
export function FinishChip({ eventId, className }: { eventId: string; className?: string }) {
  const { res } = useEventPrediction(eventId)
  if (!hasEstimate(res)) return null
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full bg-(--bg-elevated) px-2 py-0.5 text-meta text-(--text-secondary)', className)}
      title={`${CONF_LABEL[res.confidence]}: ${res.basis[0] ?? ''}`}>
      <Timer className="size-3.5 shrink-0 text-(--accent)" aria-hidden />
      <span className="sr-only">Estimated finish</span>
      <span aria-hidden>Est.</span> <span className="whitespace-nowrap font-mono font-medium text-(--text)">{res.text}</span>
    </span>
  )
}

/** The race screen block. ``athleteId`` = a linked coach looking at an athlete's race. */
export function FinishEstimate({ eventId, athleteId, className }: { eventId: string; athleteId?: string; className?: string }) {
  const { res, error, retry } = useEventPrediction(eventId, athleteId)
  return (
    <section className={cn('flex flex-col gap-2', className)} aria-labelledby={`fe-${eventId}`}>
      <h2 id={`fe-${eventId}`} className="px-1 text-caption font-semibold text-(--text-muted)">
        Your estimated finish
      </h2>
      {error ? <ErrorState compact message={error} onRetry={retry} />
        : !res ? <RabbitLoader inline className="px-1 py-2" label="Timing your race" cycle={['Timing your race…', 'Finding your best recent efforts…', 'Adding up the climbing…']} />
          : hasEstimate(res) ? <Detail p={res} />
            : <p className="px-1 text-small leading-snug text-(--text-muted)">{res.reason}</p>}
    </section>
  )
}

function Detail({ p }: { p: Prediction }) {
  const e = p.estimate
  const tri = p.splits && p.splits.length > 0
  return (
    <Card className="flex flex-col gap-3 p-3.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-title-lg font-semibold leading-none text-(--text)">{p.text}</p>
          <p className="mt-1 text-meta text-(--text-muted)">
            Most likely ~{fmtClock(e.mid_s)} · {CONF_LABEL[p.confidence]}
          </p>
        </div>
        {p.assumptions.length > 0 && (
          <InfoTip label="this estimate" align="end"
            text={`Assumes: ${p.assumptions.join('; ')}. Pacing, weather and the day itself move it either way.`} />
        )}
      </div>
      <RangeBar p={p} />
      {tri && (
        <dl className="grid grid-cols-3 gap-1 text-center min-[360px]:grid-cols-5">
          {p.splits!.map((s) => (
            <div key={s.leg} className="min-w-0 rounded-lg bg-(--bg-elevated) px-1 py-1.5">
              <dt className="text-caption text-(--text-muted)">{LEG_LABEL[s.leg]}</dt>
              <dd className="font-mono text-meta font-medium text-(--text)">{fmtClock(s.mid_s)}</dd>
            </div>
          ))}
        </dl>
      )}
      {p.cutoff && <CutoffLine c={p.cutoff} />}
      {p.projection && (
        <p className="flex items-start gap-1.5 text-small leading-snug text-(--text)">
          <TrendingUp className="mt-0.5 size-4 shrink-0 text-(--accent)" aria-hidden />
          <span><span className="font-medium">Projection: ~{fmtClock(p.projection.mid_s)}.</span> {p.projection.note}</span>
        </p>
      )}
      <ul className="flex flex-col gap-0.5 text-meta leading-snug text-(--text-secondary)">
        {p.basis.map((b) => <li key={b}>{b}</li>)}
      </ul>
    </Card>
  )
}

/** Low–high band with the likely time, plus the cutoff when there is one. */
function RangeBar({ p }: { p: Prediction }) {
  const e = p.estimate
  const top = Math.max(e.high_s, p.cutoff?.s ?? 0)
  const lo = e.low_s * 0.97, hi = top * 1.02
  const at = (s: number) => `${Math.min(100, Math.max(0, ((s - lo) / (hi - lo)) * 100))}%`
  return (
    <div className="relative h-6" aria-hidden>
      <div className="absolute inset-x-0 top-2.5 h-1 rounded-full bg-(--bg-inset)" />
      <div className="absolute top-2 h-2 rounded-full bg-(--accent)/35" style={{ left: at(e.low_s), right: `calc(100% - ${at(e.high_s)})` }} />
      <div className="absolute top-1 h-4 w-1 -translate-x-1/2 rounded-full bg-(--accent)" style={{ left: at(e.mid_s) }} />
      {p.projection && <div className="absolute top-1.5 size-3 -translate-x-1/2 rounded-full border-2 border-(--accent) bg-(--bg-surface)" style={{ left: at(p.projection.mid_s) }} />}
      {p.cutoff && <div className="absolute top-0 h-6 w-0.5 -translate-x-1/2 bg-(--warning-text)" style={{ left: at(p.cutoff.s) }} />}
    </div>
  )
}

function CutoffLine({ c }: { c: NonNullable<Prediction['cutoff']> }) {
  const hours = `${Math.round((c.s / 3600) * 10) / 10} h`
  const text = c.status === 'safe' ? `${fmtGap(c.margin_s)} inside the ${hours} cutoff, even on a slow day`
    : c.status === 'tight' ? `${fmtGap(c.margin_s)} inside the ${hours} cutoff; a rough day could push it close`
      : `About ${fmtGap(c.margin_s)} over the ${hours} cutoff right now: pacing and hiking practice matter most`
  return (
    <p className={cn('flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-small leading-snug',
      c.status === 'safe' ? 'bg-(--success-subtle) text-(--success)' : 'bg-(--warning-subtle) text-(--warning-text)')}>
      <Flag className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{text}</span>
    </p>
  )
}
