// A one-time tip (lib/newcomer): shown once per person (stored on their profile, so not again
// on another device), dismissible, at most one per screen. Counted as seen as soon as it shows.
import { useEffect, useState } from 'react'
import { Lightbulb, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { seeTip, useNewcomer, type TipId } from '@/lib/newcomer'

export function OneTip({ id, text, className }: { id: TipId; text: string; className?: string }) {
  const n = useNewcomer()
  const [show, setShow] = useState<boolean | null>(null)
  useEffect(() => {
    if (!n || show !== null) return
    const fresh = !n.tips.includes(id)
    setShow(fresh)
    if (fresh) seeTip(id)
  }, [n, id, show])
  if (!show) return null
  return (
    <div role="note" className={cn('rb-hop-in flex items-start gap-3 rounded-xl border border-(--accent)/30 bg-(--accent-subtle) py-2 pl-3.5 pr-1', className)}>
      <Lightbulb className="mt-2 size-5 shrink-0 text-(--accent)" aria-hidden />
      <p className="m-0 min-w-0 flex-1 py-1.5 text-small leading-snug text-(--text)"><span className="font-semibold">Tip: </span>{text}</p>
      <button type="button" className="flex size-11 shrink-0 items-center justify-center text-(--text-muted)" aria-label="Got it, hide tip" onClick={() => setShow(false)}>
        <X className="size-5" aria-hidden />
      </button>
    </div>
  )
}
