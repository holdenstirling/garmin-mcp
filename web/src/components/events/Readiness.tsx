// Race readiness UI: grade badge, status chip, the "How you're tracking" section for the race
// screen, and MainRaceGrade (one tappable line for the main race, used on Progress).
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { ErrorState } from '@/components/ui/ErrorState'
import { Card } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { Section } from '@/components/ui/section'
import { useTrackRefresh } from '@/components/stats/refresh'
import { STATUS_LABEL, listReadiness, mainRace, type RaceGrade, type Readiness, type ReadinessComponent, type ReadinessStatus } from '@/lib/readiness'
import { Section } from '@/components/ui/section'

const GRADE_CLS: Record<string, string> = {
  A: 'bg-(--success-subtle) text-(--success) border-(--success)/40',
  B: 'bg-(--accent-subtle) text-(--accent) border-(--accent)/40',
  C: 'bg-(--bg-elevated) text-(--text-secondary) border-(--border-strong)',
  D: 'bg-(--warning-subtle) text-(--warning-text) border-(--warning)/40',
  F: 'bg-(--warning-subtle) text-(--warning-text) border-(--warning)/40',
}
const STATUS_CLS: Record<ReadinessStatus, string> = {
  ahead: 'bg-(--success-subtle) text-(--success)',
  on_track: 'bg-(--accent-subtle) text-(--accent)',
  behind: 'bg-(--warning-subtle) text-(--warning-text)',
  at_risk: 'bg-(--danger-subtle) text-(--danger)',
}

/** The letter in a colored circle. */
export function GradeBadge({ grade, size = 'sm', className }: { grade: string; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  return (
    <span aria-label={`Readiness grade ${grade}`}
      className={cn('inline-flex shrink-0 items-center justify-center rounded-full border font-display leading-none',
        size === 'lg' ? 'size-16 text-display-lg' : size === 'md' ? 'size-11 text-title' : 'size-9 text-lead',
        GRADE_CLS[grade[0] ?? 'C'] ?? GRADE_CLS.C, className)}>
      {grade}
    </span>
  )
}

export function StatusChip({ status, className }: { status: ReadinessStatus; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-meta font-semibold', STATUS_CLS[status], className)}>
      {STATUS_LABEL[status]}
    </span>
  )
}

/** The headline without its leading status words (the chip already says them). */
export function headlineRest(h: string): string {
  const rest = h.replace(/^(ahead|on track|behind|at risk)\s*[:,]\s*(but\s+)?/i, '')
  return rest ? rest[0]!.toUpperCase() + rest.slice(1) : h
}

/** Top of the race screen: big grade, status, headline, components, "Do next". */
export function ReadinessSection({ r, error, onRetry }: { r: Readiness | null; error?: string | null; onRetry?: () => void }) {
  if (error) return <ErrorState compact message={error} onRetry={onRetry} />
  if (!r) return null
  return (
    <>
      <Card>
        <div className="flex flex-col gap-3 px-5 py-5">
          <div className="flex items-center gap-4">
            <GradeBadge grade={r.grade} size="lg" />
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <StatusChip status={r.status} />
              <span className="text-meta font-semibold tabular-nums text-(--text-secondary)">{r.score} of 100</span>
              <InfoTip label="the readiness grade" align="end"
                text="A weighted score of fitness trajectory, key sessions, consistency, course and conditions, and health. It comes from your Garmin training, plan and check-ins, and updates as you train." />
            </div>
          </div>
          <p className="text-title-sm font-semibold leading-snug text-(--text)">{headlineRest(r.headline)}</p>
          <p className="text-body leading-relaxed text-(--text-secondary)">{r.summary}</p>
        </div>
      </Card>
      <Section title="How you're tracking" description="Tap a line to see what counts.">
        <Card>
          <div className="divide-y divide-(--border)">
            {r.components.map((c) => <ComponentRow key={c.id} c={c} />)}
          </div>
        </Card>
      </Section>
      {r.actions.length > 0 && (
        <Section title="Do next">
          <Card>
            <ol className="flex flex-col gap-3 px-4 py-4">
              {r.actions.map((a, i) => (
                <li key={a} className="flex gap-3 text-body leading-snug text-(--text)">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) text-meta font-semibold text-(--accent)">{i + 1}</span>
                  <span className="min-w-0 flex-1 pt-0.5">{a}</span>
                </li>
              ))}
            </ol>
          </Card>
        </Section>
      )}
    </>
  )
}

function barCls(score: number): string {
  return score >= 85 ? 'bg-(--success)' : score >= 65 ? 'bg-(--accent)' : score >= 45 ? 'bg-(--warning)' : 'bg-(--danger)'
}

function ComponentRow({ c }: { c: ReadinessComponent }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex items-start">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex min-h-12 min-w-0 flex-1 flex-col gap-1.5 py-3.5 pl-4 text-left active:bg-(--bg-inset)">
        <span className="flex w-full items-center gap-2">
          <span className="min-w-0 flex-1 text-body font-medium text-(--text)">{c.label}</span>
          <span className="w-9 shrink-0 text-right text-meta font-semibold tabular-nums text-(--text-secondary)">{c.score}</span>
          <ChevronDown className={cn('size-5 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
        </span>
        <span className="flex w-full items-center">
          <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-(--bg-inset)" role="meter"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.score} aria-label={`${c.label} ${c.score} of 100`}>
            <span className={cn('block h-full rounded-full', barCls(c.score))} style={{ width: `${Math.max(4, c.score)}%` }} />
          </span>
        </span>
        <span className="text-small leading-snug text-(--text-secondary)">{c.detail}</span>
        {open && <span className="text-small text-(--text-muted)">Counts for {c.weight}% of the grade.</span>}
      </button>
      <InfoTip className="mr-3 mt-3.5 ml-1" label={c.label} text={c.tip} align="end" />
    </div>
  )
}

/** Race card row: grade + status + headline, tap opens the race screen. */
export function ReadinessRow({ g, onClick, extra }: { g: RaceGrade; onClick: () => void; extra?: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-12 w-full items-center gap-3 border-t border-(--border) px-4 py-3 text-left active:bg-(--bg-inset)">
      <GradeBadge grade={g.grade} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-meta font-semibold text-(--text-secondary)">Readiness and race fit</span>
          <StatusChip status={g.status} />
        </span>
        <span className="mt-1 block text-body leading-snug text-(--text)">{headlineRest(g.headline)}</span>
        {/* The finish estimate gets its own line instead of squeezing the label. */}
        {extra && <span className="mt-2 flex">{extra}</span>}
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

/**
 * Progress tab: the main race's grade in one tappable line. Loads its own data; renders
 * nothing when there's no upcoming race (or it can't load). ``onOpen`` gets the event id.
 */
export function MainRaceGrade({ onOpen, className, loadKey = 0, title }: {
  onOpen: (eventId: string) => void; className?: string
  /** bump to re-read (Progress refresh) */
  loadKey?: number
  /** a section heading above the row (Progress); only shown when there's a race */
  title?: string
}) {
  const [g, setG] = useState<RaceGrade | null>(null)
  const [error, setError] = useState(false)
  const track = useTrackRefresh()
  const load = useCallback(() => {
    setError(false)
    track(listReadiness().then((r) => setG(mainRace(r.races) ?? null), () => setError(true)))
  }, [track])
  useEffect(() => { load() }, [load, loadKey])
  if (error && !g) return <ErrorState compact message="Couldn't load your race grade." onRetry={load} className={className} />
  if (!g) return null
  const row = (
    <button type="button" onClick={() => onOpen(g.event_id)} data-usage-card="race_grade"
      className={cn('flex min-h-14 w-full items-center gap-3.5 rounded-xl border border-(--border) bg-(--bg-surface) px-4 py-3.5 text-left active:bg-(--bg-inset)', className)}>
      <GradeBadge grade={g.grade} size="md" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-body-lg font-semibold leading-snug text-(--text)">{g.name}</span>
          <StatusChip status={g.status} />
        </span>
        <span className="mt-1 block text-small leading-snug text-(--text-secondary)">{headlineRest(g.headline)}</span>
      </span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
  return title ? <Section title={title} description="How ready you are, and what to do next.">{row}</Section> : row
}

/** Coach overview: the athlete's main race grade (not tappable). */
export function RaceGradeLine({ g }: { g: RaceGrade }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <GradeBadge grade={g.grade} size="md" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-body font-medium text-(--text)">{g.name}</span>
          <StatusChip status={g.status} />
        </span>
        <span className="mt-0.5 block text-meta leading-snug text-(--text-muted)">{g.headline}</span>
      </span>
    </div>
  )
}
