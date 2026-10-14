// Count-up for big numbers (XP, streak). Eases out over 600 ms; instant with reduced motion.
// With ``storeKey`` it counts from the value you last saw (localStorage), so reopening a
// screen only animates what changed; without it, from ``from`` (0).
import { useEffect, useState } from 'react'
import { reducedMotion, swapNumber } from '@/components/fx/motion'

export function useCountUp(to: number, { from = 0, duration = 600, storeKey }: { from?: number; duration?: number; storeKey?: string } = {}): number {
  const [start] = useState(() => {
    if (!storeKey) return from
    try {
      const v = window.localStorage.getItem(`rabbit.fx.count.${storeKey}`)
      return v == null || v === '' || Number.isNaN(Number(v)) ? from : Number(v)
    } catch { return to }
  })
  const [n, setN] = useState(() => (reducedMotion() || start >= to ? to : start))
  useEffect(() => {
    if (storeKey) swapNumber(`count.${storeKey}`, to)
    if (reducedMotion() || start >= to) { setN(to); return }
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration)
      setN(Math.round(start + (to - start) * (1 - (1 - p) ** 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to]) // eslint-disable-line react-hooks/exhaustive-deps
  return n
}

/** ``<CountUp value={xp} format={(n) => n.toLocaleString()} />``: only this span re-renders.
 *  Screen readers get the final value (the ticking text is hidden from them). */
export function CountUp({ value, format = (n) => n.toLocaleString(), storeKey, className }: {
  value: number; format?: (n: number) => string; storeKey?: string; className?: string
}) {
  const n = useCountUp(value, { storeKey })
  return (
    <span className={className}>
      <span aria-hidden="true" className="tabular-nums">{format(n)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  )
}
