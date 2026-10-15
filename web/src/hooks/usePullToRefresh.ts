// Pull to refresh for a scrolling page (touch only). Attach `anchor` to any element inside the
// scroller; the nearest overflow-y: auto|scroll ancestor is the one pulled. Pulling down at the
// top past THRESHOLD (damped px) and letting go runs onRefresh(); a returned promise keeps the
// loader busy until it settles (max 10 s). `bunny`/`win` are the indicator's elements
// (components/fx/PullToRefresh draws the rabbit loader).
//
// It never fights native scrolling: listeners are passive (nothing is preventDefault-ed), a
// pull only starts with the scroller at the very top and a single finger moving mostly down,
// and it stands down while a sheet or overlay page is open on top (lib/overlays). Reduced
// motion: the rabbit doesn't follow the finger; it fades in at its resting spot.
import { useEffect, useRef, useState } from 'react'
import { haptic } from '@/lib/haptics'
import { overlayOver, prefersReducedMotion } from '@/lib/overlays'

export const PULL_THRESHOLD = 64
const MAX = 96
const DAMP = 0.5
const MAX_BUSY_MS = 10_000

export type PullPhase = 'idle' | 'pull' | 'ready' | 'busy' | 'leap'

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement ?? null; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if (o === 'auto' || o === 'scroll') return p
  }
  return null
}

export function usePullToRefresh(onRefresh: () => unknown, { disabled = false }: { disabled?: boolean } = {}) {
  const anchor = useRef<HTMLSpanElement>(null)
  const bunny = useRef<HTMLSpanElement>(null)
  const win = useRef<HTMLSpanElement>(null)
  const [phase, setPhase] = useState<PullPhase>('idle')
  const phaseRef = useRef(phase)
  phaseRef.current = phase
  const cb = useRef(onRefresh)
  cb.current = onRefresh

  useEffect(() => {
    if (disabled) return
    const sc = scrollParent(anchor.current)
    if (!sc) return
    const reduced = prefersReducedMotion()
    let start: { x: number; y: number } | null = null
    let pull = 0
    let live = true
    const timers: number[] = []
    const later = (f: () => void, ms: number) => { timers.push(window.setTimeout(() => { if (live) f() }, ms)) }
    const draw = (px: number) => {
      const b = bunny.current
      if (!b) return
      b.style.transition = 'none'
      b.style.opacity = String(Math.min(1, px / 28))
      b.style.transform = `translate3d(-50%, ${reduced ? 24 : Math.round(px - 40)}px, 0)`
    }
    const reset = () => {
      const b = bunny.current
      if (b) { b.style.transition = ''; b.style.opacity = '0'; b.style.transform = 'translate3d(-50%, -40px, 0)' }
    }
    const onStart = (e: TouchEvent) => {
      start = null
      if (phaseRef.current === 'leap' || phaseRef.current === 'busy' || e.touches.length !== 1 || sc.scrollTop > 0) return
      if (overlayOver(sc)) return
      const t = e.touches[0]!
      start = { x: t.clientX, y: t.clientY }
      pull = 0
      const r = sc.getBoundingClientRect(), w = win.current
      if (w) { w.style.top = `${r.top}px`; w.style.left = `${r.left}px`; w.style.width = `${r.width}px` }
    }
    const onMove = (e: TouchEvent) => {
      if (!start) return
      const t = e.touches[0]!
      const dy = t.clientY - start.y, dx = t.clientX - start.x
      // Sideways first (a tab swipe, a carousel) or scrolled away: not a pull.
      if (!pull && Math.abs(dx) > Math.abs(dy)) { start = null; return }
      if (dy <= 0 || sc.scrollTop > 0) { if (pull) { pull = 0; reset(); setPhase('idle') } return }
      pull = Math.min(MAX, dy * DAMP)
      draw(pull)
      const next = pull >= PULL_THRESHOLD ? 'ready' : 'pull'
      if (next !== phaseRef.current) setPhase(next)
    }
    const onEnd = () => {
      if (!start) return
      start = null
      if (pull >= PULL_THRESHOLD) {
        // Busy: the rabbit settles at the rest line and hops in place; then it leaps away.
        setPhase('busy')
        haptic()
        const b = bunny.current
        if (b) { b.style.transition = ''; b.style.transform = 'translate3d(-50%, 24px, 0)' }
        const t0 = Date.now()
        const leap = () => later(() => {
          setPhase('leap')
          if (bunny.current) bunny.current.style.transform = '' // the leap keyframes take over
          later(() => { setPhase('idle'); reset() }, reduced ? 0 : 700)
        }, Math.max(0, 450 - (Date.now() - t0)))
        let r: unknown
        try { r = cb.current() } catch { /* the screen shows its own errors */ }
        if (r && typeof (r as Promise<unknown>).then === 'function') {
          let done = false
          const once = () => { if (!done) { done = true; leap() } }
          ;(r as Promise<unknown>).then(once, once)
          later(once, MAX_BUSY_MS)
        } else leap()
      } else { reset(); if (pull) setPhase('idle') }
      pull = 0
    }
    sc.addEventListener('touchstart', onStart, { passive: true })
    sc.addEventListener('touchmove', onMove, { passive: true })
    sc.addEventListener('touchend', onEnd, { passive: true })
    sc.addEventListener('touchcancel', onEnd, { passive: true })
    return () => {
      live = false
      timers.forEach((t) => window.clearTimeout(t))
      if (phaseRef.current !== 'idle') { reset(); setPhase('idle') } // never stuck mid-hop
      sc.removeEventListener('touchstart', onStart)
      sc.removeEventListener('touchmove', onMove)
      sc.removeEventListener('touchend', onEnd)
      sc.removeEventListener('touchcancel', onEnd)
    }
  }, [disabled])

  return { anchor, bunny, win, phase }
}
