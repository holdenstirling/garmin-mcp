// Race readiness UI: grade badge, status chip, the "How you're tracking" section for the race
// screen, and MainRaceGrade (one tappable line for the main race, used on Progress).
import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, ListChecks } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { ErrorState } from '@/components/ui/ErrorState'
import { Card, Field } from '@/components/plan/ui'
import { cn } from '@/lib/utils'
import { STATUS_LABEL, listReadiness, mainRace, type RaceGrade, type Readiness, type ReadinessComponent, type ReadinessStatus } from '@/lib/readiness'

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
        size === 'lg' ? 'size-16 text-[1.9rem]' : size === 'md' ? 'size-11 text-[1.15rem]' : 'size-9 text-[0.9412rem]',
        GRADE_CLS[grade[0] ?? 'C'] ?? GRADE_CLS.C, className)}>
      {grade}
    </span>
  )
}

export function StatusChip({ status, className }: { status: ReadinessStatus; className?: string }) {
  return (
    <span className={cn('inline-flex shrink-0 rounded-full px-2 py-0.5 font-mono text-[0.6471rem] font-semibold uppercase tracking-wider', STATUS_CLS[status], className)}>
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
        <div className="flex items-center gap-4 px-4 py-4">
          <GradeBadge grade={r.grade} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusChip status={r.status} />
              <span className="text-[0.6471rem] text-(--text-muted)">{r.score}/100</span>
              <InfoTip label="the readiness grade" align="end"
                text="A weighted score of fitness trajectory, key sessions, consistency, course and conditions, and health. It comes from your Garmin training, plan and check-ins, and updates as you train." />
            </div>
            <p className="mt-1 text-[0.9412rem] font-medium leading-snug text-(--text)">{headlineRest(r.headline)}</p>
            <p className="mt-0.5 text-[0.7059rem] leading-snug text-(--text-muted)">{r.summary}</p>
          </div>
        </div>
      </Card>
      <Card>
        <Field label="How you're tracking">
          <div className="-mx-4 -mb-3.5 divide-y divide-(--border)">
            {r.components.map((c) => <ComponentRow key={c.id} c={c} />)}
          </div>
        </Field>
      </Card>
      {r.actions.length > 0 && (
        <Card>
          <Field label="Do next">
            <ol className="flex flex-col gap-2">
              {r.actions.map((a, i) => (
                <li key={a} className="flex gap-2.5 text-[0.8235rem] leading-snug text-(--text)">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-(--accent-subtle) font-mono text-[0.6471rem] font-semibold text-(--accent)">{i + 1}</span>
                  <span className="min-w-0 flex-1">{a}</span>
                </li>
              ))}
            </ol>
          </Field>
        </Card>
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
        className="flex min-h-11 min-w-0 flex-1 flex-col gap-1 py-2.5 pl-4 text-left active:bg-(--bg-inset)">
        <span className="flex w-full items-center gap-2.5">
          <span className="w-32 shrink-0 truncate text-[0.8235rem] font-medium text-(--text)">{c.label}</span>
          <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-(--bg-elevated)" role="meter"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.score} aria-label={`${c.label} ${c.score} of 100`}>
            <span className={cn('block h-full rounded-full', barCls(c.score))} style={{ width: `${Math.max(4, c.score)}%` }} />
          </span>
          <span className="w-7 shrink-0 text-right font-mono text-[0.6471rem] text-(--text-muted)">{c.score}</span>
          <ChevronDown className={cn('size-4 shrink-0 text-(--text-muted) transition-transform', open && 'rotate-180')} aria-hidden />
        </span>
        <span className={cn('text-[0.7059rem] leading-snug text-(--text-secondary)', !open && 'truncate')}>{c.detail}</span>
        {open && <span className="text-[0.6471rem] text-(--text-muted)">Counts for {c.weight}% of the grade.</span>}
      </button>
      <InfoTip className="mr-3 mt-3.5 ml-1" label={c.label} text={c.tip} align="end" />
    </div>
  )
}

/** Race card row: grade + status + headline, tap opens the race screen. */
export function ReadinessRow({ g, onClick }: { g: RaceGrade; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className="flex min-h-11 w-full items-center gap-2.5 border-t border-(--border) px-3.5 py-2 text-left active:bg-(--bg-inset)">
      <GradeBadge grade={g.grade} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <StatusChip status={g.status} />
          <span className="truncate text-[0.6471rem] text-(--text-muted)">Readiness & race fit</span>
        </span>
        <span className="mt-0.5 block truncate text-[0.7647rem] text-(--text)">{headlineRest(g.headline)}</span>
      </span>
      <ChevronRight className="size-3.5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

/**
 * Progress tab: the main race's grade in one tappable line. Loads its own data; renders
 * nothing when there's no upcoming race (or it can't load). ``onOpen`` gets the event id.
 */
export function MainRaceGrade({ onOpen, className }: { onOpen: (eventId: string) => void; className?: string }) {
  const [g, setG] = useState<RaceGrade | null>(null)
  const load = useCallback(() => { listReadiness().then((r) => setG(mainRace(r.races)), () => setG(null)) }, [])
  useEffect(load, [load])
  if (!g) return null
  return (
    <button type="button" onClick={() => onOpen(g.event_id)}
      className={cn('flex min-h-11 w-full items-center gap-3 rounded-xl border border-(--border) bg-(--bg-surface) px-3.5 py-3 text-left active:bg-(--bg-inset)', className)}>
      <GradeBadge grade={g.grade} size="md" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[0.8824rem] font-medium text-(--text)">{g.name}</span>
          <StatusChip status={g.status} />
        </span>
        <span className="mt-0.5 block truncate text-[0.7059rem] text-(--text-muted)">{headlineRest(g.headline)}</span>
      </span>
      <ListChecks className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}

/** Coach overview: the athlete's main race grade (not tappable). */
export function RaceGradeLine({ g }: { g: RaceGrade }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <GradeBadge grade={g.grade} size="md" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[0.8235rem] font-medium text-(--text)">{g.name}</span>
          <StatusChip status={g.status} />
        </span>
        <span className="mt-0.5 block text-[0.7059rem] leading-snug text-(--text-muted)">{g.headline}</span>
      </span>
    </div>
  )
}
