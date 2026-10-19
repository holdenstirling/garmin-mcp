// "What your data says" (Progress): up to ``max`` (3; Progress shows 2) deterministic insights, "Show all" for the rest.
// Each row: impact icon + title + one line; tap to expand the numbers, a tiny chart, why it
// matters, one action and "Not now" (snoozes 7 days). Nothing changes the plan without a tap.
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, Lightbulb, TrendingUp, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/ErrorState'
import { InfoTip } from '@/components/ui/InfoTip'
import { Card } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { decideAdjust } from '@/lib/adjust'
import type { Term } from '@/lib/glossary'
import { useTrackRefresh } from '@/components/stats/refresh'
import { dismissInsight, getInsights, type Evidence, type Impact, type Insight } from '@/lib/insights'

const SHOWN = 3
/** The one term each insight leans on, explained with an (i). */
const TERM: Record<string, Term> = {
  ramp: 'ramp_rate', long: 'long_session', intensity: 'eighty_twenty', recovery: 'readiness', fitness: 'fitness',
}

const IMPACT: Record<Impact, { icon: typeof Lightbulb; color: string; bg: string; label: string }> = {
  action: { icon: Lightbulb, color: 'text-(--accent)', bg: 'bg-(--accent-subtle)', label: 'Do this' },
  watch: { icon: TriangleAlert, color: 'text-(--warning-text)', bg: 'bg-(--warning-subtle)', label: 'Keep an eye on' },
  positive: { icon: TrendingUp, color: 'text-(--accent)', bg: 'bg-(--accent-subtle)', label: 'Going well' },
}

export function InsightsCard({ refresh = 0, max = SHOWN, onOpenPlan, onOpenSession, onOpenGear, onAsk }: {
  /** bump to re-read with fresh data (Progress "Refresh") */
  refresh?: number
  /** how many show before "Show all" */
  max?: number
  onOpenPlan?: () => void; onOpenSession?: (sessionId: string) => void
  onOpenGear?: () => void; onAsk?: (text: string) => void
}) {
  const [items, setItems] = useState<Insight[] | null>(null)
  const [error, setError] = useState(false)
  const [all, setAll] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const track = useTrackRefresh()
  useEffect(() => {
    let live = true
    setError(false)
    track(getInsights(attempt > 0 || refresh > 0).then((r) => { if (live) setItems(r.insights) }, () => { if (live) setError(true) }))
    return () => { live = false }
  }, [attempt, refresh, track])
  const drop = useCallback((id: string) => {
    setItems((xs) => xs?.filter((x) => x.id !== id) ?? null)
    dismissInsight(id).catch(() => {})
  }, [])

  if (error && !items) return <ErrorState compact message="Couldn't load your insights." onRetry={() => setAttempt((n) => n + 1)} />
  if (!items || items.length === 0) return null
  const shown = all ? items : items.slice(0, max)
  return (
    <section className="flex flex-col gap-2" aria-label="What your data says">
      <h2 className="flex items-center gap-1 px-1 text-caption font-semibold text-(--text-muted)">
        What your data says
        <InfoTip label="these insights" align="start"
          text="Patterns rabbt spots in your Garmin workouts, plan, check-ins and gear, worked out with fixed rules, not guesses. Tap one for the numbers." />
      </h2>
      <Card>
        <ul className="divide-y divide-(--border)">
          {shown.map((i) => (
            <Row key={i.id} i={i} open={open === i.id} onToggle={() => setOpen((o) => (o === i.id ? null : i.id))}
              onDismiss={() => drop(i.id)} onOpenPlan={onOpenPlan} onOpenSession={onOpenSession}
              onOpenGear={onOpenGear} onAsk={onAsk} />
          ))}
        </ul>
      </Card>
      {items.length > max && (
        <button type="button" onClick={() => setAll((a) => !a)} aria-expanded={all}
          className="hit-44 self-center text-meta font-medium text-(--accent)">
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </section>
  )
}

function Row({ i, open, onToggle, onDismiss, onOpenPlan, onOpenSession, onOpenGear, onAsk }: {
  i: Insight; open: boolean; onToggle: () => void; onDismiss: () => void
  onOpenPlan?: () => void; onOpenSession?: (sessionId: string) => void; onOpenGear?: () => void; onAsk?: (text: string) => void
}) {
  const t = IMPACT[i.impact]
  const Icon = t.icon
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const a = i.action
  const run = (() => {
    if (a.kind === 'apply_adjust' && a.payload.id) {
      return async () => {
        if (!confirm) { setConfirm(true); return }
        setBusy(true)
        try {
          const r = await decideAdjust(a.payload.id!, 'apply')
          setNote(`Done: ${r.applied} session${r.applied === 1 ? '' : 's'} eased. See them in your plan.`)
          dismissInsight(i.id).catch(() => {})
        } catch (e) {
          setNote((e as Error).message || "Couldn't apply that just now.")
        } finally { setBusy(false); setConfirm(false) }
      }
    }
    if (a.kind === 'open_plan' && onOpenPlan) return onOpenPlan
    if (a.kind === 'open_session' && a.payload.session_id && (onOpenSession || onOpenPlan)) {
      return () => (onOpenSession ? onOpenSession(a.payload.session_id!) : onOpenPlan?.())
    }
    if (a.kind === 'open_gear' && onOpenGear) return onOpenGear
    if ((a.kind === 'ask_rabbit' || a.kind === 'ask_coach') && onAsk) return () => onAsk(a.payload.text ?? `About "${i.title}": `)
    return null
  })()
  return (
    <li>
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="flex min-h-11 w-full items-start gap-2.5 px-3.5 py-3 text-left active:bg-(--bg-inset)">
        <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full', t.bg, t.color)}>
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="sr-only">{t.label}: </span>
          <span className={cn('block text-body font-semibold leading-tight', i.impact === 'watch' ? 'text-(--warning-text)' : 'text-(--text)')}>{i.title}</span>
          {!open && <span className="mt-0.5 block truncate text-meta text-(--text-muted)">{i.explanation}</span>}
        </span>
        <ChevronDown className={cn('mt-1 size-5 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="flex flex-col gap-2.5 px-3.5 pb-3.5 pl-[3.25rem]">
          <p className="text-small leading-snug text-(--text)">
            {i.explanation}
            {TERM[i.id.split(':')[0]!] && <InfoTip term={TERM[i.id.split(':')[0]!]} className="ml-1" align="end" />}
          </p>
          {i.evidence && i.evidence.values.length > 0 && <Spark e={i.evidence} />}
          <p className="text-meta leading-snug text-(--text-secondary)">
            <span className="font-semibold">Why it matters: </span>{i.why}
          </p>
          {(i.confidence === 'low' || i.uses_oura) && (
            <p className="text-caption text-(--text-muted)">
              {i.confidence === 'low' ? 'Early pattern: based on only a few days. ' : ''}
              {i.uses_oura ? 'Uses your Oura data: shown here only, never sent to rabbt or your coach.' : ''}
            </p>
          )}
          {note && <p role="status" className="text-meta text-(--accent)">{note}</p>}
          <div className="flex flex-wrap items-center gap-3">
            {run && !note && (
              <Button variant="primary" className="hit-44 h-8 px-3 text-meta" disabled={busy} onClick={() => void run()}>
                {confirm ? 'Tap again to apply' : a.label}
              </Button>
            )}
            {confirm && (
              <button type="button" className="hit-44 text-meta text-(--text-muted)" onClick={() => setConfirm(false)}>Cancel</button>
            )}
            <button type="button" onClick={onDismiss} className="hit-44 text-meta text-(--text-muted) underline-offset-2 hover:underline">
              Not now
            </button>
          </div>
        </div>
      )}
    </li>
  )
}

/** Tiny chart: bars (weekly values), a line (trend) or a meter, with an optional dashed target. */
function Spark({ e }: { e: Evidence }) {
  const W = 200, H = 40
  const unit = e.unit.startsWith('%') || e.unit.startsWith('/') ? e.unit : ` ${e.unit}`
  const fmt = (v: number) => `${Math.round(v * 10) / 10}${unit}`
  if (e.kind === 'meter') {
    const pct = Math.max(0, Math.min(100, e.values[0] ?? 0))
    return (
      <div className="flex items-center gap-2" role="img" aria-label={`${Math.round(pct)}% used`}>
        <span className="h-2 flex-1 overflow-hidden rounded-full bg-(--bg-elevated)">
          <span className={cn('block h-full rounded-full', pct >= 80 ? 'bg-(--warning)' : 'bg-(--accent)')} style={{ width: `${pct}%` }} />
        </span>
        <span className="text-meta text-(--text-muted)">{Math.round(pct)}%</span>
      </div>
    )
  }
  const max = Math.max(1e-6, ...e.values, e.target ?? 0)
  const min = e.kind === 'line' ? Math.min(...e.values) * 0.9 : 0
  const y = (v: number) => H - 2 - ((v - min) / (max - min || 1)) * (H - 6)
  const n = e.values.length
  const label = e.values.map((v, k) => `${e.labels[k] ?? ''} ${fmt(v)}`).join(', ')
  return (
    <figure className="flex flex-col gap-0.5">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-10 w-full max-w-[240px]" role="img" aria-label={label} preserveAspectRatio="none">
        {e.kind === 'bars' ? e.values.map((v, k) => {
          const bw = W / n - 2, x = k * (W / n) + 1, top = y(v)
          return (
            <rect key={k} x={x} y={Math.min(top, H - 3)} width={bw} height={Math.max(1, H - 2 - top)} rx={2}
              fill="var(--accent)" opacity={k === n - 1 ? 1 : 0.55}>
              <title>{`${e.labels[k] ?? ''}: ${fmt(v)}`}</title>
            </rect>
          )
        }) : (
          <polyline fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            points={e.values.map((v, k) => `${(k / Math.max(1, n - 1)) * (W - 4) + 2},${y(v)}`).join(' ')} />
        )}
        {e.target != null && e.target <= max && (
          <line x1={0} x2={W} y1={y(e.target)} y2={y(e.target)} stroke="var(--text-muted)" strokeWidth={1}
            strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <figcaption className="flex max-w-[240px] justify-between text-caption text-(--text-muted)">
        <span>{e.labels[0]}</span>
        {e.target != null && <span>dashed: {e.kind === 'bars' && e.unit === '%' ? 'guideline' : 'target'} {fmt(e.target)}</span>}
        <span>{e.labels[n - 1]}</span>
      </figcaption>
    </figure>
  )
}
