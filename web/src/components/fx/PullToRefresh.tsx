// PullToRefresh: touch only. Put it first inside a scrolling container's content. Pulling down
// at the top reveals the rabbit crouching; let go past the line and it leaps and onRefresh()
// runs. If onRefresh returns a promise, the rabbit hops in place until it settles (max 10 s),
// then leaps away. Listeners are passive (scrolling is never blocked); the pull is drawn with transforms
// set directly on the element, so dragging never re-renders React. The rabbit is drawn in a
// fixed window over the top of the scroller (portaled to <body>), so it takes no layout space.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RabbitLogo } from '@/components/RabbitLogo'
import { cn } from '@/lib/utils'
import { hapticTap } from '@/lib/haptics'
import { Puff } from './shapes'

const READY = 64 // px of (damped) pull that triggers a refresh
const MAX = 96

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let p = el?.parentElement ?? null; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY
    if (o === 'auto' || o === 'scroll') return p
  }
  return null
}

export function PullToRefresh({ onRefresh, disabled }: { onRefresh: () => unknown; disabled?: boolean }) {
  const anchor = useRef<HTMLSpanElement>(null)
  const bunny = useRef<HTMLSpanElement>(null)
  const win = useRef<HTMLSpanElement>(null)
  const [phase, setPhase] = useState<'idle' | 'pull' | 'ready' | 'busy' | 'leap'>('idle')
  const phaseRef = useRef(phase)
  phaseRef.current = phase
  const cb = useRef(onRefresh)
  cb.current = onRefresh

  useEffect(() => {
    if (disabled) return
    const sc = scrollParent(anchor.current)
    if (!sc) return
    let startY: number | null = null
    let pull = 0
    let live = true
    const timers: number[] = []
    const later = (f: () => void, ms: number) => { timers.push(window.setTimeout(() => { if (live) f() }, ms)) }
    const draw = (px: number) => {
      const b = bunny.current
      if (!b) return
      b.style.transition = 'none'
      b.style.opacity = String(Math.min(1, px / 28))
      b.style.transform = `translate3d(-50%, ${Math.round(px - 40)}px, 0)`
    }
    const reset = () => {
      const b = bunny.current
      if (b) { b.style.transition = ''; b.style.opacity = '0'; b.style.transform = 'translate3d(-50%, -40px, 0)' }
    }
    const start = (e: TouchEvent) => {
      if (phaseRef.current === 'leap' || phaseRef.current === 'busy' || e.touches.length !== 1 || sc.scrollTop > 0) { startY = null; return }
      startY = e.touches[0]!.clientY; pull = 0
      const r = sc.getBoundingClientRect(), w = win.current
      if (w) { w.style.top = `${r.top}px`; w.style.left = `${r.left}px`; w.style.width = `${r.width}px` }
    }
    const move = (e: TouchEvent) => {
      if (startY == null) return
      const dy = e.touches[0]!.clientY - startY
      if (dy <= 0 || sc.scrollTop > 0) { if (pull) { pull = 0; reset(); setPhase('idle') } return }
      pull = Math.min(MAX, dy * 0.5)
      draw(pull)
      const next = pull >= READY ? 'ready' : 'pull'
      if (next !== phaseRef.current) setPhase(next)
    }
    const end = () => {
      if (startY == null) return
      startY = null
      if (pull >= READY) {
        // Busy: the rabbit settles at the rest line and hops in place; then it leaps away.
        setPhase('busy')
        hapticTap()
        const b = bunny.current
        if (b) { b.style.transition = ''; b.style.transform = 'translate3d(-50%, 24px, 0)' }
        const t0 = Date.now()
        const leap = () => later(() => {
          setPhase('leap')
          if (bunny.current) bunny.current.style.transform = '' // the leap keyframes take over
          later(() => { setPhase('idle'); reset() }, 700)
        }, Math.max(0, 450 - (Date.now() - t0)))
        let r: unknown
        try { r = cb.current() } catch { /* the screen shows its own errors */ }
        if (r && typeof (r as Promise<unknown>).then === 'function') {
          let done = false
          const once = () => { if (!done) { done = true; leap() } }
          ;(r as Promise<unknown>).then(once, once)
          later(once, 10_000)
        } else leap()
      } else { reset(); if (pull) setPhase('idle') }
      pull = 0
    }
    sc.addEventListener('touchstart', start, { passive: true })
    sc.addEventListener('touchmove', move, { passive: true })
    sc.addEventListener('touchend', end, { passive: true })
    sc.addEventListener('touchcancel', end, { passive: true })
    return () => {
      live = false
      timers.forEach((t) => window.clearTimeout(t))
      if (phaseRef.current !== 'idle') { reset(); setPhase('idle') } // never stuck mid-hop
      sc.removeEventListener('touchstart', start)
      sc.removeEventListener('touchmove', move)
      sc.removeEventListener('touchend', end)
      sc.removeEventListener('touchcancel', end)
    }
  }, [disabled])

  const layer = (
    <span ref={win} className={cn('fx-ptr', phase !== 'idle' && 'is-on')} aria-hidden="true">
      <span ref={bunny} className={cn('fx-ptr__bunny', phase === 'ready' && 'is-ready', phase === 'busy' && 'is-busy', phase === 'leap' && 'is-leap')}>
        <span className="fx-ptr__crouch"><RabbitLogo size={30} /></span>
        {phase === 'leap' && <Puff size={16} className="fx-ptr__puff" />}
      </span>
    </span>
  )
  return (
    <>
      <span ref={anchor} hidden />
      {typeof document !== 'undefined' && createPortal(layer, document.body)}
    </>
  )
}
