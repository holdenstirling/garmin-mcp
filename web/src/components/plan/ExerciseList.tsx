// One list of strength (or mobility / prehab) exercises, used by the session sheet, the plan day
// and the workout screen. Structured sessions (planbuilder, strength opt-in) carry sets, reps,
// rest and a cue; older ones carry a single `dose` line.
import type { Exercise } from '@/lib/plan'
import { cn } from '@/lib/utils'

export function doseOf(e: Exercise): string {
  if (e.sets && e.reps) return `${e.sets} x ${e.reps}`
  if (e.sets) return `${e.sets} sets`
  return e.dose ?? ''
}

function restOf(s: number | null | undefined): string | null {
  if (!s || s <= 0) return null
  return s >= 60 && s % 60 === 0 ? `${s / 60} min rest` : s > 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} rest` : `${s} s rest`
}

export function ExerciseList({ items, compact = false, className }: { items: Exercise[]; compact?: boolean; className?: string }) {
  return (
    <ol className={cn('m-0 flex list-none flex-col p-0', compact ? 'gap-1' : 'gap-2.5', className)}>
      {items.map((e, i) => {
        const rest = restOf(e.rest_s)
        return (
          <li key={`${e.name}-${i}`} className="flex flex-col gap-0.5">
            <div className={cn('flex items-baseline gap-2', compact ? 'text-small' : 'text-body')}>
              <span className="min-w-0 flex-1 text-(--text)">{e.name}</span>
              <span className="shrink-0 font-semibold tabular-nums text-(--text)">{doseOf(e)}</span>
            </div>
            {!compact && (rest || e.cue) && (
              <p className="m-0 text-meta leading-snug text-(--text-muted)">
                {[rest, e.cue].filter(Boolean).join(' · ')}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
