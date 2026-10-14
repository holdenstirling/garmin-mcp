// Finish-time estimates (predict.py): "Your estimate: 1:52–2:01" on Explore cards and race
// detail, and a small "Predicted finish" line on Races cards and the readiness screen.
// Basis lines say where the number comes from; ultras are labelled a rough guide.
import { useEffect, useState } from 'react'
import { Timer } from 'lucide-react'
import { InfoTip } from '@/components/ui/InfoTip'
import { cn } from '@/lib/utils'
import { predictFor, type Estimate } from '@/lib/explore2'

export function basisText(e: Estimate): string {
  const conf = e.confidence === 'high' ? 'Fairly tight' : e.confidence === 'medium' ? 'A decent guess' : 'A rough guide'
  return `${conf}. Based on: ${e.basis.join('; ')}. Pacing, weather and the day itself move it either way.`
}

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

/** The detail version: line + what it's based on. */
export function EstimateBlock({ e }: { e: Estimate }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-(--bg-elevated) px-3 py-2">
      <EstimateLine e={e} className="min-w-0 flex-1" />
      <InfoTip label="this estimate" text={basisText(e)} align="end" />
    </div>
  )
}

/** "Predicted finish 3:41–3:58" for a calendar event; renders nothing without an estimate. */
export function PredictedFinish({ eventId, className }: { eventId: string; className?: string }) {
  const [e, setE] = useState<Estimate | null>(null)
  useEffect(() => {
    let live = true
    predictFor({ eventId }).then((r) => { if (live) setE(r.estimate) }, () => {})
    return () => { live = false }
  }, [eventId])
  if (!e) return null
  return (
    <span className={cn('flex items-center gap-1 text-[0.7059rem] text-(--text-secondary)', className)}>
      <Timer className="size-3.5 shrink-0 text-(--accent)" aria-hidden />
      Predicted finish <span className="font-mono font-medium text-(--text)">{e.text}</span>
      {e.label === 'rough guide' && <span className="text-(--text-muted)">· rough guide</span>}
      <InfoTip label="the predicted finish" text={basisText(e)} align="end" />
    </span>
  )
}
