// Home: one line when a tracked niggle (body.py) needs today's quick update, or Rabbit has an
// easing suggestion for the plan. Tap opens Body & niggles. Hidden otherwise.
import { useEffect, useState } from 'react'
import { Bandage, ChevronRight } from 'lucide-react'
import { NIGGLES_CHANGED, getNiggles, openBody, type Niggles } from '@/lib/body'

export function NiggleNudge({ refreshKey }: { refreshKey?: number }) {
  const [d, setD] = useState<Niggles | null>(null)
  useEffect(() => {
    let live = true
    const load = () => { getNiggles().then((x) => { if (live) setD(x) }, () => { /* hidden on error */ }) }
    load()
    window.addEventListener(NIGGLES_CHANGED, load)
    return () => { live = false; window.removeEventListener(NIGGLES_CHANGED, load) }
  }, [refreshKey])
  const due = d?.active.find((n) => n.needs_update)
  if (!d || (!due && !d.proposal)) return null
  const red = d.active.some((n) => n.assess?.red_flag.length)
  const text = red ? 'A niggle needs a professional look. Tap for details.'
    : d.proposal ? `rabbt suggests easing your plan for your ${d.active[0]?.label.toLowerCase() ?? 'niggle'}.`
      : `How's your ${due!.label.toLowerCase()} today? Quick update.`
  return (
    <button type="button" onClick={() => openBody({ view: 'niggles' })}
      className={`mx-4 mt-3 flex min-h-12 w-[calc(100%-2rem)] shrink-0 items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left active:opacity-80 ${red ? 'border-(--danger)/30 bg-(--danger)/5' : 'border-(--warning)/30 bg-(--warning-subtle)'}`}>
      <Bandage className={`size-4 shrink-0 ${red ? 'text-(--danger)' : 'text-(--warning-text)'}`} aria-hidden />
      <span className="min-w-0 flex-1 text-[0.8235rem] text-(--text)">{text}</span>
      <ChevronRight className="size-4 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
