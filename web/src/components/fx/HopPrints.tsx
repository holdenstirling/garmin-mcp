// HopPrints: when a progress bar grows, a short trail of hop prints bounds along it from the
// old fill to the new one, then fades. Put it inside a ``relative`` wrapper around the bar.
// ``value`` is what must rise (XP total, done count); ``pct`` is where the fill ends (0-100).
// With ``storeKey`` the last value is remembered across opens (localStorage), so XP earned
// while you were elsewhere still hops the next time the bar shows. Never on first sight.
import { useEffect, useRef, useState } from 'react'
import { HopPrint } from './shapes'
import { reducedMotion, swapNumber } from './motion'

export function HopPrints({ pct, value, storeKey, className }: {
  pct: number; value?: number; storeKey?: string; className?: string
}) {
  const v = value ?? pct
  const prev = useRef<{ v: number; pct: number } | null>(null)
  const timer = useRef(0)
  const [trail, setTrail] = useState<{ id: number; from: number; to: number } | null>(null)
  useEffect(() => {
    let before = prev.current
    if (!before && storeKey) {
      const stored = swapNumber(`hop.${storeKey}`, v)
      const storedPct = swapNumber(`hop.${storeKey}.pct`, pct)
      if (stored != null) before = { v: stored, pct: storedPct ?? 0 }
    } else if (storeKey) { swapNumber(`hop.${storeKey}`, v); swapNumber(`hop.${storeKey}.pct`, pct) }
    prev.current = { v, pct }
    if (before && v === before.v) return // same value (StrictMode re-run): keep any running trail
    if (!before || v < before.v || reducedMotion()) { setTrail(null); return }
    const from = before.pct <= pct ? before.pct : 0 // wrapped (level up): run from the start
    setTrail({ id: Date.now(), from: Math.max(0, from), to: Math.min(100, pct) })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setTrail(null), 1200)
  }, [v]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => window.clearTimeout(timer.current), [])
  if (!trail) return null
  const span = trail.to - trail.from
  const n = Math.max(2, Math.min(5, Math.round(span / 8) + 1))
  return (
    <span key={trail.id} className={`fx-hops ${className ?? ''}`} aria-hidden="true">
      {Array.from({ length: n }, (_, i) => {
        const at = trail.from + (span * (i + 1)) / n
        return (
          <HopPrint key={i} size={9} className="fx-hops__print"
            style={{ left: `${at}%`, top: i % 2 ? '-11px' : '-6px', animationDelay: `${i * 110}ms` }} />
        )
      })}
    </span>
  )
}
