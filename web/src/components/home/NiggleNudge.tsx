// Home: one line when a tracked niggle (body.py) needs today's quick update, or Rabbit has an
// easing suggestion for the plan. Tap opens Body & niggles. Hidden otherwise.
import { useEffect, useState } from 'react'
import { Bandage, ChevronRight } from 'lucide-react'
import { NIGGLES_CHANGED, getNiggles, openBody, type Niggles } from '@/lib/body'

export function NiggleNudge({ refreshKey, onShown }: {
  refreshKey?: number
  /** after each load: whether the nudge shows (Home keeps one nudge up at a time) */
  onShown?: (shown: boolean) => void
}) {
  const [d, setD] = useState<Niggles | null>(null)
  useEffect(() => {
    let live = true
    const load = () => {
      getNiggles().then((x) => {
        if (!live) return
        setD(x)
        onShown?.(!!(x.active.find((n) => n.needs_update) || x.proposal))
      }, () => { if (live) onShown?.(false) /* hidden on error */ })
    }
    load()
    window.addEventListener(NIGGLES_CHANGED, load)
    return () => { live = false; window.removeEventListener(NIGGLES_CHANGED, load) }
  }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const due = d?.active.find((n) => n.needs_update)
  if (!d || (!due && !d.proposal)) return null
  const red = d.active.some((n) => n.assess?.red_flag.length)
  const text = red ? 'A niggle needs a professional look. Tap for details.'
    : d.proposal ? `rabbt suggests easing your plan for your ${d.active[0]?.label.toLowerCase() ?? 'niggle'}.`
      : `How's your ${due!.label.toLowerCase()} today? Quick update.`
  return (
    <button type="button" onClick={() => openBody({ view: 'niggles' })}
      className={`flex min-h-14 w-full shrink-0 items-center gap-3.5 rounded-xl border px-4 py-3.5 text-left active:opacity-80 ${red ? 'border-(--danger)/30 bg-(--danger)/5' : 'border-(--warning)/30 bg-(--warning-subtle)'}`}>
      <Bandage className={`size-6 shrink-0 ${red ? 'text-(--danger)' : 'text-(--warning-text)'}`} aria-hidden />
      <span className="min-w-0 flex-1 text-body leading-snug text-(--text)">{text}</span>
      <ChevronRight className="size-5 shrink-0 text-(--text-muted)" aria-hidden />
    </button>
  )
}
