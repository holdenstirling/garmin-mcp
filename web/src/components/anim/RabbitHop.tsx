// RabbitHop: the app's rabbit mark sits at the end of a progress bar's fill. When the value
// rises it hops along to the new spot (600 ms); on first sight it is simply there. Put it
// inside the bar's ``relative`` wrapper (``.fx-bar``). Movement is transform-only: a
// full-width track slides by ``pct`` of its own width and the rabbit shifts back by ``pct``
// of its width, so it always stays within the bar (clipped layer, no page overflow).
// ``storeKey`` remembers the last value (localStorage): progress made elsewhere still hops.
import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { RabbitLogo } from '@/components/RabbitLogo'
import { reducedMotion, swapNumber } from '@/components/fx/motion'
import { cn } from '@/lib/utils'

export function RabbitHop({ pct, value, size = 14, storeKey, className }: {
  /** where the fill ends, 0-100 */
  pct: number
  /** what must rise for a hop (XP total, done count); defaults to pct */
  value?: number
  size?: number
  storeKey?: string
  className?: string
}) {
  const p = Math.max(0, Math.min(100, pct))
  const v = value ?? p
  const [shown, setShown] = useState(p)
  const [snap, setSnap] = useState(true)
  const [hop, setHop] = useState(0)
  const prev = useRef<{ v: number; p: number } | null>(null)
  // Layout effect: a hop from an older spot starts there before the first paint (no flash).
  useLayoutEffect(() => {
    let before = prev.current
    if (!before && storeKey) {
      const sv = swapNumber(`rbhop.${storeKey}`, v), sp = swapNumber(`rbhop.${storeKey}.pct`, p)
      if (sv != null && sp != null) before = { v: sv, p: sp }
    } else if (storeKey) { swapNumber(`rbhop.${storeKey}`, v); swapNumber(`rbhop.${storeKey}.pct`, p) }
    prev.current = { v, p }
    if (before && before.v === v && before.p === p) return // StrictMode re-run: keep a running hop
    if (!before || v <= before.v || reducedMotion()) { setSnap(true); setShown(p); return }
    setSnap(true); setShown(before.p <= p ? before.p : 0) // wrapped (level up): from the start
    // Two frames: the start spot paints without a transition, then the move animates.
    requestAnimationFrame(() => requestAnimationFrame(() => { setSnap(false); setShown(p); setHop((n) => n + 1) }))
  }, [v, p]) // eslint-disable-line react-hooks/exhaustive-deps
  const style = { '--rb-p': shown, '--rb-size': `${size}px` } as CSSProperties
  return (
    <span className={cn('rb-rabbit-hop', snap && 'is-snap', className)} style={style} aria-hidden="true">
      <span className="rb-rabbit-hop__track">
        <span className="rb-rabbit-hop__seat">
          <span key={hop} className={cn('rb-rabbit-hop__bunny', hop > 0 && 'is-hopping')}><RabbitLogo size={size} /></span>
        </span>
      </span>
    </span>
  )
}
