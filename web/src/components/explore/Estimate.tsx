// Finish-time estimates (predict.py): "Your estimate: 1:52–2:01" on Explore cards, "Your
// estimated finish" on race detail (FinishChip, lazy, hidden on 404/errors). Calendar events
// use components/events/FinishEstimate.tsx.
import { useEffect, useState } from 'react'
import { Timer } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { cn } from '@/lib/utils'
import { fmtDuration } from '@/lib/format'
import { predictFinish, type Estimate, type Finish } from '@/lib/explore2'

/** One compact line for cards. */
export function EstimateLine({ e, className }: { e: Estimate; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 text-[0.7059rem] text-(--text-secondary)', className)}>
      <Timer className="size-3.5 shrink-0 text-(--accent)" aria-hidden />
      <span>Your estimate: <span className="font-mono font-medium text-(--text)">{e.text}</span>
        {e.label === 'rough guide' && <span className="text-(--text-muted)"> · rough guide</span>}</span>
    </span>
  )
}

const dur = (s: number) => fmtDuration(s / 60)

/** Race detail: "Your estimated finish" for the picked distance. Asks GET /api/predict lazily
 *  and renders only when it answers with an estimate (404 or any error: nothing). */
export function FinishChip({ type, distanceKm, date, climbM, elevationM }: {
  type?: string; distanceKm: number | null | undefined; date?: string; climbM?: number | null; elevationM?: number | null
}) {
  const [f, setF] = useState<Finish | null>(null)
  useEffect(() => {
    setF(null)
    if (!distanceKm) return
    let live = true
    predictFinish({ type, distanceKm, date, climbM, elevationM }).then((r) => { if (live) setF(r) })
    return () => { live = false }
  }, [type, distanceKm, date, climbM, elevationM])
  if (!f) return null
  const conf = f.confidence === 'high' ? 'Fairly tight' : f.confidence === 'medium' ? 'A decent guess' : 'A rough guide'
  const tip = `${conf}.${f.basis.length ? ` Based on: ${f.basis.join('; ')}.` : ''} Pacing, weather and the day itself move it either way.`
  return (
    <div className="flex items-center gap-2 rounded-xl bg-(--bg-elevated) px-3 py-2">
      <Timer className="size-4 shrink-0 text-(--accent)" aria-hidden />
      <span className="min-w-0 flex-1 text-[0.7647rem] text-(--text-secondary)">
        Your estimated finish <span className="font-mono font-medium text-(--text)">{dur(f.mid_s)}</span>
        <span className="text-(--text-muted)"> ({dur(f.low_s)}–{dur(f.high_s)})</span>
      </span>
      <InfoTip label="this estimate" text={tip} align="end" />
    </div>
  )
}
